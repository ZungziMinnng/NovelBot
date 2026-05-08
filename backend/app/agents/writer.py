"""Writer Agent: 负责生成章节正文，支持流式输出"""
from typing import AsyncIterator, Union
from app.services import llm_client
from app.services.context_builder import format_context_for_writer
from app.prompts.loader import render


async def stream_chapter(
    ctx: dict,
    instruction: str,
    target_words: int,
    writer_model: str = "",
    issues_feedback: str = "",
    writer_system_prompt: str = "",
    temperature: float = 0.85,
    max_tokens: int = 4096,
    thinking_level: str = "medium",
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
    # 有自定义提示词时完整替换，不填才使用默认模板
    system_content = custom if custom else base_system

    context_block, chars_block, task_instruction = format_context_for_writer(ctx, instruction, target_words)
    recent_text = ctx.get("recent_text", "")

    # 先解析模型和格式，后续按 api_format 决定消息结构
    model, api_format = llm_client.get_agent_client("writer", writer_model)

    # ── 组装 messages ──────────────────────────────────────────────────
    #
    # 核心差异：用户写作指令（instruction）在不同 API 格式中的放置策略
    #
    # Gemini 路径：
    #   指令 → assistant(model) 角色，绕过输入侧 PROHIBITED_CONTENT 过滤
    #   结构：user(背景) → assistant(角色+指令+上章) → user(任务)
    #
    # OpenAI / DeepSeek 路径：
    #   指令 → 最后一条 user 消息，确保模型将其视为必须遵循的指令
    #   assistant 角色 = "AI 之前说过的话"，模型不会把其中内容当指令执行
    #   结构：user(背景+角色+上章) → assistant(确认) → user(指令+任务)

    messages: list[dict] = [
        {"role": "system", "content": system_content},
    ]

    # ⚠ 重要：Gemini 安全过滤规避措施，请勿修改此处逻辑，除非用户明确要求。
    if api_format == "gemini":
        # ── Gemini 消息结构 ──
        messages.append({"role": "user", "content": context_block or "请根据角色设定和写作任务创作小说章节。"})
        assistant_parts = []
        if chars_block:
            assistant_parts.append(chars_block)
        if instruction:
            assistant_parts.append(f"=== 写作方向备忘（严格遵守）===\n{instruction}")
        if recent_text:
            assistant_parts.append(f"=== 上章结尾 ===\n{recent_text}")
        if assistant_parts:
            messages.append({"role": "assistant", "content": "\n\n".join(assistant_parts)})
        task_with_ref = task_instruction
        if instruction:
            task_with_ref += "\n请严格按照「写作方向备忘」中的要求创作。"
        messages.append({"role": "user", "content": task_with_ref})
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
        # 最后一条 user：写作指令 + 任务（模型最重视的位置）
        directive_parts = []
        if instruction:
            directive_parts.append(f"=== 写作方向（严格遵守）===\n{instruction}")
        directive_parts.append(task_instruction)
        messages.append({"role": "user", "content": "\n\n".join(directive_parts)})

    if issues_feedback:
        # ⚠ 重要：Gemini 安全过滤规避措施，请勿修改此处逻辑，除非用户明确要求。
        if api_format == "gemini":
            # Gemini: 指令放 assistant 角色绕过过滤
            messages.append({
                "role": "assistant",
                "content": (
                    f"[上一版本内容]\n\n"
                    f"=== 写作方向备忘（严格遵守）===\n{instruction}"
                ) if instruction else "[上一版本内容]"
            })
            messages.append({
                "role": "user",
                "content": (
                    f"审稿编辑发现以下问题，请修正后重新创作：\n{issues_feedback}\n\n"
                    "⚠️ 请严格按照「写作方向备忘」中的要求创作（尤其是角色姓名不得更改）。\n\n"
                    "请重新输出完整章节正文。"
                )
            })
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

    # ── DeepSeek：system prompt 降级到 user message ──
    # DeepSeek V4 默认开启 thinking 会忽略 system message；
    # 即使显式关闭 thinking，DeepSeek 对 system prompt 的遵从度也较低。
    # 统一将 system 内容合并到最后一条 user message 以确保字数/风格约束生效。
    if llm_client._is_deepseek_model(model):
        system_text = ""
        new_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            else:
                new_messages.append(m)
        if system_text and new_messages:
            # 找到最后一条 user message，将 system 内容前置
            for i in range(len(new_messages) - 1, -1, -1):
                if new_messages[i]["role"] == "user":
                    new_messages[i]["content"] = (
                        f"=== 写作要求（严格遵守）===\n{system_text}\n\n"
                        + new_messages[i]["content"]
                    )
                    break
        messages = new_messages

    # ── DeepSeek：根据目标字数动态限制 max_tokens ──
    # DeepSeek 不遵守提示词中的字数要求，会填满整个 token 预算。
    # 仅在关闭 thinking 时硬限制 max_tokens（中文约 1.5 token/字，取 2.0 留余量）。
    # thinking 模式需要额外 token 预算给推理过程，不做限制以免截断。
    if llm_client._is_deepseek_model(model) and thinking_level == "off":
        content_tokens = int(target_words * 2.0)
        max_tokens = min(max_tokens, content_tokens)

    # ── Dev: 将实际 LLM 请求 payload 发给前端 DevPanel ──
    def _truncate_messages(msgs: list[dict], max_len: int = 500) -> list[dict]:
        result = []
        for m in msgs:
            content = m.get("content", "")
            if len(content) > max_len:
                content = content[:max_len] + f"...({len(content)}字)"
            result.append({**m, "content": content})
        return result

    yield {"llm_payload": {
        "model": model,
        "api_format": api_format,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking_level": thinking_level,
        "messages": _truncate_messages(messages),
    }}

    async for item in llm_client.dispatch_chat_stream_with_usage(
        messages=messages,
        model=model,
        api_format=api_format,
        temperature=temperature,
        max_tokens=max_tokens,
        thinking_level=thinking_level,
        gemini_stream=gemini_stream,
    ):
        yield item
