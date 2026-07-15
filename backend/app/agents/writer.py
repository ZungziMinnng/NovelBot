"""Writer Agent: 负责生成章节正文，支持流式输出"""
from typing import AsyncIterator, Union
from app.services import llm_client
from app.services.context_builder import format_context_for_writer
from app.prompts.loader import render

CIRCLED_NUMS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _preview_text(text: str, max_len: int = 1200) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"...({len(text)}字)"


def _truncate_messages(msgs: list[dict], max_len: int = 2000) -> list[dict]:
    result = []
    for m in msgs:
        content = m.get("content", "")
        result.append({**m, "content": _preview_text(content, max_len)})
    return result


def _build_example_turns(examples) -> list[dict]:
    """把 [{user, assistant}] 示例对转为真实的 few-shot 消息轮。两端都有内容才算一组有效示例。"""
    turns = []
    for ex in examples or []:
        u = (ex.get("user") or "").strip()
        a = (ex.get("assistant") or "").strip()
        if u and a:
            turns.append({"role": "user", "content": u})
            turns.append({"role": "assistant", "content": a})
    return turns


def _apply_deepseek_system_merge(messages: list[dict], real_model: str) -> list[dict]:
    """DeepSeek：system prompt 降级到 user message。
    DeepSeek V4 默认开启 thinking 会忽略 system message；
    即使显式关闭 thinking，DeepSeek 对 system prompt 的遵从度也较低。
    统一将 system 内容合并到最后一条 user message 以确保字数/风格约束生效。"""
    if not llm_client._is_deepseek_model(real_model):
        return messages
    system_text = ""
    new_messages = []
    for m in messages:
        if m["role"] == "system":
            system_text = m["content"]
        else:
            new_messages.append(m)
    if system_text and new_messages:
        for i in range(len(new_messages) - 1, -1, -1):
            if new_messages[i]["role"] == "user":
                new_messages[i]["content"] = (
                    f"=== 写作要求（严格遵守）===\n{system_text}\n\n"
                    + new_messages[i]["content"]
                )
                break
    return new_messages


def _number_paragraphs(text: str) -> str:
    paragraphs = [p for p in text.split("\n") if p.strip()]
    lines = []
    for i, p in enumerate(paragraphs):
        num = CIRCLED_NUMS[i] if i < len(CIRCLED_NUMS) else f"({i+1})"
        lines.append(f"{num} {p}")
    return "\n\n".join(lines)


def _format_annotations(annotations: list[dict]) -> str:
    global_notes = []
    para_notes = []
    for a in annotations:
        p = a.get("paragraph")
        if p is not None:
            num = CIRCLED_NUMS[p - 1] if 0 < p <= len(CIRCLED_NUMS) else f"({p})"
            para_notes.append(f"- 段落{num}：{a['text']}")
        else:
            global_notes.append(f"- {a['text']}")
    parts = []
    if global_notes:
        parts.append("全局批注：\n" + "\n".join(global_notes))
    if para_notes:
        parts.append("段落批注：\n" + "\n".join(para_notes))
    return "\n\n".join(parts)


async def stream_chapter(
    ctx: dict,
    instruction: str,
    target_words: int,
    writer_model: str = "",
    issues_feedback: str = "",
    writer_system_prompt: str = "",
    writer_examples: list | None = None,
    temperature: float = 0.85,
    use_custom_temperature: bool = True,
    max_tokens: int = 16384,
    gemini_thinking_level: str = "medium",
    deepseek_thinking_level: str = "high",
    gemini_stream: bool = False,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    """
    流式生成章节内容。
    yield str  → token
    yield (int, int) → (input_tokens, output_tokens) 最后一条
    """
    base_system = render(
        "writer.jinja2",
        genre=ctx.get("genre", ""),
        writing_style=ctx.get("writing_style", ""),
        target_words=target_words,
    )
    custom = writer_system_prompt.strip()
    system_source = "custom" if custom else "template"
    if custom:
        writing_style = (ctx.get("writing_style") or "").strip()
        system_content = f"{custom}\n\n【文章风格】\n{writing_style}" if writing_style else custom
    else:
        system_content = base_system
    context_block, chars_block, task_instruction = format_context_for_writer(ctx, instruction, target_words)
    recent_text = ctx.get("recent_text", "")

    # 先解析模型和格式，后续按 api_format 决定消息结构
    # model 为流转引用（ModelEntry.id 或旧 model_id），传给 dispatch 消歧；
    # real_model 为真实模型名，供 _is_deepseek_model 判断与 DevPanel 展示。
    model, api_format = llm_client.get_agent_client("writer", writer_model)
    real_model, _, _ = llm_client.resolve_model_ref(model)

    messages: list[dict] = [
        {"role": "system", "content": system_content},
    ]

    if api_format == "gemini":
        user_parts = []
        if context_block:
            user_parts.append(context_block)
        if chars_block:
            user_parts.append(chars_block)
        if recent_text:
            user_parts.append(f"=== 上章结尾 ===\n{recent_text}")
        user_parts.append(task_instruction)
        if instruction:
            user_parts.append(f"=== 写作方向（严格遵守，与其他要求冲突时以本节为准）===\n{instruction}")
        messages.append({"role": "user", "content": "\n\n".join(user_parts) or "请根据角色设定和写作任务创作小说章节。"})
    else:
        # ── OpenAI / DeepSeek / Anthropic 消息结构 ──
        # 第一条 user：所有参考资料（世界观、角色、上章内容）
        ref_parts = []
        if context_block:
            ref_parts.append(context_block)
        if chars_block:
            ref_parts.append(chars_block)
        if recent_text:
            ref_parts.append(f"=== 上章结尾 ===\n{recent_text}")
        messages.append({"role": "user", "content": "\n\n".join(ref_parts) or "请根据角色设定和写作任务创作小说章节。"})
        # assistant 确认收到参考资料
        messages.append({"role": "assistant", "content": "已了解上述背景资料、角色设定和近期剧情，准备按要求创作。"})
        # 最后一条 user：任务 + 写作指令（instruction 放最末，占据模型最重视的位置）
        directive_parts = [task_instruction]
        if instruction:
            directive_parts.append(f"=== 写作方向（严格遵守，与其他要求冲突时以本节为准）===\n{instruction}")
        messages.append({"role": "user", "content": "\n\n".join(directive_parts)})

    if issues_feedback:
        if api_format == "gemini":
            revision_text = (
                f"\n\n=== 修订要求 ===\n"
                f"审稿编辑发现以下问题，请修正后重新创作：\n{issues_feedback}\n\n"
                "请重新输出完整章节正文。"
            )
            for i in range(len(messages) - 1, -1, -1):
                if messages[i]["role"] == "user":
                    messages[i] = {**messages[i], "content": messages[i]["content"] + revision_text}
                    break
        else:
            # OpenAI / DeepSeek: assistant 表示上一版草稿，user 给出修改指令+写作方向
            messages.append({"role": "assistant", "content": "[上一版本内容]"})
            revision_parts = [f"审稿编辑发现以下问题，请修正后重新创作：\n{issues_feedback}"]
            if instruction:
                revision_parts.append(f"=== 写作方向（严格遵守）===\n{instruction}")
            revision_parts.append(
                "⚠️ 请严格按照上述写作方向要求创作（尤其是角色姓名不得更改）。\n\n"
                "请重新输出完整章节正文。"
            )
            messages.append({"role": "user", "content": "\n\n".join(revision_parts)})

    # ── few-shot 示例轮：插到 system 之后、参考资料之前 ──
    example_turns = _build_example_turns(writer_examples)
    if example_turns:
        messages[1:1] = example_turns

    messages = _apply_deepseek_system_merge(messages, real_model)

    # ── DeepSeek：根据目标字数动态限制 max_tokens ──
    # DeepSeek 不遵守提示词中的字数要求，会填满整个 token 预算。
    # 仅在关闭 thinking 时硬限制 max_tokens（中文约 1.5 token/字，取 2.0 留余量）。
    # thinking 模式需要额外 token 预算给推理过程，不做限制以免截断。
    if llm_client._is_deepseek_model(real_model) and deepseek_thinking_level == "off":
        content_tokens = int(target_words * 2.0)
        max_tokens = min(max_tokens, content_tokens)

    # 当前模型实际生效的思考档位（用于诊断展示）
    if api_format == "gemini":
        effective_thinking = gemini_thinking_level
    elif llm_client._is_deepseek_model(real_model):
        effective_thinking = deepseek_thinking_level
    else:
        effective_thinking = "off"

    # 部分模型不支持 temperature，关闭后传递 -1 由 llm_client 省略该参数
    if not use_custom_temperature:
        temperature = -1.0

    # ── Dev: 将实际 LLM 请求 payload 发给前端 DevPanel ──
    payload_diagnostics = {
        "system_chars": len(system_content),
        "system_source": system_source,
        "context_chars": len(context_block or ""),
        "characters_chars": len(chars_block or ""),
        "full_text_context_chars": len(ctx.get("full_text_context", "") or ""),
        "recent_text_chars": len(recent_text or ""),
        "instruction_chars": len(instruction or ""),
        "task_chars": len(task_instruction or ""),
        "issues_feedback_chars": len(issues_feedback or ""),
        "example_turns": len(example_turns),
        "message_roles": [m.get("role", "") for m in messages],
        "message_chars": [len(m.get("content", "")) for m in messages],
        "section_previews": {
            "system": _preview_text(system_content),
            "context": _preview_text(context_block or ""),
            "characters": _preview_text(chars_block or ""),
            "recent_text": _preview_text(recent_text or ""),
            "instruction": _preview_text(instruction or ""),
            "task": _preview_text(task_instruction or ""),
            "issues_feedback": _preview_text(issues_feedback or ""),
        },
    }

    yield {"llm_payload": {
        "model": real_model,
        "api_format": api_format,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking_level": effective_thinking,
        "diagnostics": payload_diagnostics,
        "messages": _truncate_messages(messages),
    }}

    async for item in llm_client.dispatch_chat_stream_with_usage(
        messages=messages,
        model=model,
        api_format=api_format,
        temperature=temperature,
        max_tokens=max_tokens,
        gemini_thinking_level=gemini_thinking_level,
        deepseek_thinking_level=deepseek_thinking_level,
        gemini_stream=gemini_stream,
    ):
        yield item


def _build_revision_constraints(ctx: dict) -> str:
    """修订调用的最小硬约束块：核心规则 / 用词库 / 角色名单。
    修订只需防止改坏这些硬性设定，不重发完整世界观与摘要上下文。"""
    parts = []
    if ctx.get("core_rules"):
        parts.append(
            "=== 世界观核心规则（必须严格遵守）===\n"
            f"{ctx['core_rules']}"
        )
    if ctx.get("glossary"):
        lines = [
            "=== 用词规范（必须严格遵守）===",
            "- 描写相关概念/对象时必须使用「规范用词」，严禁使用禁止写法；专有名词汉字必须与下表完全一致：",
        ]
        for g in ctx["glossary"]:
            line = f"· 用「{g['term']}」"
            if g.get("forbidden_variants"):
                line += f" —— 禁用：「{g['forbidden_variants']}」"
            if g.get("notes"):
                line += f"（{g['notes']}）"
            lines.append(line)
        parts.append("\n".join(lines))
    names = ctx.get("_all_character_names") or [c.get("name", "") for c in ctx.get("characters", [])]
    names = [n for n in names if n]
    if names:
        parts.append("=== 角色名单（姓名不得更改，不得创造同音字/形近字）===\n" + "、".join(names))
    return "\n\n".join(parts)


async def stream_chapter_revision(
    ctx: dict,
    previous_text: str,
    issues_feedback: str,
    instruction: str,
    target_words: int,
    writer_model: str = "",
    writer_system_prompt: str = "",
    temperature: float = 0.85,
    use_custom_temperature: bool = True,
    max_tokens: int = 16384,
    gemini_thinking_level: str = "medium",
    deepseek_thinking_level: str = "high",
    gemini_stream: bool = False,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    """审稿不通过后的增量修订：回传上一版全文 + 审稿意见 + 最小硬约束，
    要求只修正被指出的问题、其余保持原样。不发完整上下文、不带 few-shot。"""
    base_system = render(
        "writer.jinja2",
        genre=ctx.get("genre", ""),
        writing_style=ctx.get("writing_style", ""),
        target_words=target_words,
    )
    custom = writer_system_prompt.strip()
    system_source = "custom" if custom else "template"
    if custom:
        writing_style = (ctx.get("writing_style") or "").strip()
        system_content = f"{custom}\n\n【文章风格】\n{writing_style}" if writing_style else custom
    else:
        system_content = base_system

    constraints = _build_revision_constraints(ctx)
    directive_parts = [
        f"审稿编辑对上一版正文提出以下问题：\n{issues_feedback}",
        "请在上一版正文的基础上修订：只修正所列问题，其余内容保持原样，不要重写未被指出的部分。",
    ]
    if instruction:
        directive_parts.append(f"=== 写作方向（严格遵守）===\n{instruction}")
    directive_parts.append(f"直接输出修订后的完整章节正文（约{target_words}字），不要任何说明、标记或标题。")
    revision_directive = "\n\n".join(directive_parts)

    model, api_format = llm_client.get_agent_client("writer", writer_model)
    real_model, _, _ = llm_client.resolve_model_ref(model)

    messages: list[dict] = [{"role": "system", "content": system_content}]
    if api_format == "gemini":
        user_parts = [p for p in (
            constraints,
            f"=== 你此前生成的本章草稿 ===\n{previous_text}",
            revision_directive,
        ) if p]
        messages.append({"role": "user", "content": "\n\n".join(user_parts)})
    else:
        # user 给出约束与任务，assistant 轮承载上一版全文，最后 user 给修订指令
        first_user = f"{constraints}\n\n请根据以上约束创作本章正文。" if constraints else "请创作本章正文。"
        messages.append({"role": "user", "content": first_user})
        messages.append({"role": "assistant", "content": previous_text})
        messages.append({"role": "user", "content": revision_directive})

    messages = _apply_deepseek_system_merge(messages, real_model)

    if llm_client._is_deepseek_model(real_model) and deepseek_thinking_level == "off":
        content_tokens = int(target_words * 2.0)
        max_tokens = min(max_tokens, content_tokens)

    if api_format == "gemini":
        effective_thinking = gemini_thinking_level
    elif llm_client._is_deepseek_model(real_model):
        effective_thinking = deepseek_thinking_level
    else:
        effective_thinking = "off"

    if not use_custom_temperature:
        temperature = -1.0

    payload_diagnostics = {
        "system_chars": len(system_content),
        "system_source": system_source,
        "constraints_chars": len(constraints or ""),
        "previous_text_chars": len(previous_text or ""),
        "issues_feedback_chars": len(issues_feedback or ""),
        "instruction_chars": len(instruction or ""),
        "message_roles": [m.get("role", "") for m in messages],
        "message_chars": [len(m.get("content", "")) for m in messages],
        "section_previews": {
            "system": _preview_text(system_content),
            "constraints": _preview_text(constraints or ""),
            "previous_text": _preview_text(previous_text or ""),
            "issues_feedback": _preview_text(issues_feedback or ""),
            "instruction": _preview_text(instruction or ""),
        },
    }

    yield {"llm_payload": {
        "model": real_model,
        "api_format": api_format,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking_level": effective_thinking,
        "diagnostics": payload_diagnostics,
        "messages": _truncate_messages(messages),
    }}

    async for item in llm_client.dispatch_chat_stream_with_usage(
        messages=messages,
        model=model,
        api_format=api_format,
        temperature=temperature,
        max_tokens=max_tokens,
        gemini_thinking_level=gemini_thinking_level,
        deepseek_thinking_level=deepseek_thinking_level,
        gemini_stream=gemini_stream,
    ):
        yield item


async def stream_chapter_rewrite(
    ctx: dict,
    original_text: str,
    annotations: list[dict],
    target_words: int = 0,
    writer_model: str = "",
    writer_system_prompt: str = "",
    writer_examples: list | None = None,
    temperature: float = 0.7,
    use_custom_temperature: bool = True,
    max_tokens: int = 16384,
    gemini_thinking_level: str = "medium",
    deepseek_thinking_level: str = "high",
    gemini_stream: bool = False,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    if target_words <= 0:
        target_words = len(original_text)

    base_system = render(
        "rewriter.jinja2",
        genre=ctx.get("genre", ""),
        writing_style=ctx.get("writing_style", ""),
        target_words=target_words,
    )
    custom = writer_system_prompt.strip()
    system_source = "custom" if custom else "template"
    if custom:
        writing_style = (ctx.get("writing_style") or "").strip()
        system_content = f"{custom}\n\n【文章风格】\n{writing_style}" if writing_style else custom
    else:
        system_content = base_system
    context_block, chars_block, _ = format_context_for_writer(ctx, "", target_words)

    numbered_text = _number_paragraphs(original_text)
    annotations_text = _format_annotations(annotations)

    model, api_format = llm_client.get_agent_client("writer", writer_model)
    real_model, _, _ = llm_client.resolve_model_ref(model)

    messages: list[dict] = [
        {"role": "system", "content": system_content},
    ]

    ref_parts = []
    if context_block:
        ref_parts.append(context_block)
    if chars_block:
        ref_parts.append(chars_block)
    rewrite_parts = [
        f"以下是当前章节的内容（已标注段落编号）：\n\n{numbered_text}",
        f"请根据以下批注修改这一章，未提及的部分尽量保持原样：\n\n{annotations_text}",
        "请输出修改后的完整章节正文（不要段落编号，不要章节标题）。",
    ]
    if api_format == "gemini":
        messages.append({"role": "user", "content": "\n\n".join([*ref_parts, *rewrite_parts])})
    else:
        messages.append({"role": "user", "content": "\n\n".join(ref_parts) or "以下是需要修改的章节。"})
        messages.append({"role": "assistant", "content": "已了解背景资料，请提供需要修改的章节和批注。"})
        messages.append({"role": "user", "content": "\n\n".join(rewrite_parts)})

    # ── few-shot 示例轮：插到 system 之后、参考资料之前 ──
    example_turns = _build_example_turns(writer_examples)
    if example_turns:
        messages[1:1] = example_turns

    messages = _apply_deepseek_system_merge(messages, real_model)

    if llm_client._is_deepseek_model(real_model) and deepseek_thinking_level == "off":
        content_tokens = int(target_words * 2.0)
        max_tokens = min(max_tokens, content_tokens)

    if api_format == "gemini":
        effective_thinking = gemini_thinking_level
    elif llm_client._is_deepseek_model(real_model):
        effective_thinking = deepseek_thinking_level
    else:
        effective_thinking = "off"

    if not use_custom_temperature:
        temperature = -1.0

    payload_diagnostics = {
        "system_chars": len(system_content),
        "system_source": system_source,
        "context_chars": len(context_block or ""),
        "characters_chars": len(chars_block or ""),
        "original_text_chars": len(original_text or ""),
        "annotations_chars": len(annotations_text or ""),
        "example_turns": len(example_turns),
        "message_roles": [m.get("role", "") for m in messages],
        "message_chars": [len(m.get("content", "")) for m in messages],
        "section_previews": {
            "system": _preview_text(system_content),
            "context": _preview_text(context_block or ""),
            "characters": _preview_text(chars_block or ""),
            "original_text": _preview_text(original_text or ""),
            "annotations": _preview_text(annotations_text or ""),
        },
    }

    yield {"llm_payload": {
        "model": real_model,
        "api_format": api_format,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking_level": effective_thinking,
        "diagnostics": payload_diagnostics,
        "messages": _truncate_messages(messages),
    }}

    async for item in llm_client.dispatch_chat_stream_with_usage(
        messages=messages,
        model=model,
        api_format=api_format,
        temperature=temperature,
        max_tokens=max_tokens,
        gemini_thinking_level=gemini_thinking_level,
        deepseek_thinking_level=deepseek_thinking_level,
        gemini_stream=gemini_stream,
    ):
        yield item
