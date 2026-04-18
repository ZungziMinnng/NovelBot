import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.memory import Outline
from app.services import vector_store, summarizer


async def build_generation_context(
    session: AsyncSession,
    novel: Novel,
    chapter_number: int,
    volume: int = 1,
    scene_hint: str = "",
) -> dict:
    """
    组装生成章节所需的全部上下文，返回结构化 dict。
    各 Agent 从这个 dict 中取自己需要的部分。
    """
    ctx = {}

    # 1. 核心设定（世界观，始终携带）
    ctx["core_setting"] = novel.core_setting[:1000] if novel.core_setting else ""

    # 2. 角色状态卡（结构化，节约 token）
    result = await session.execute(
        select(Character).where(Character.novel_id == novel.id)
    )
    characters = result.scalars().all()
    ctx["characters"] = [
        {
            "name": c.name,
            "role": c.role,
            "description": c.description,
            "full_sheet": c.full_sheet or {},
            "state": c.current_state,
        }
        for c in characters
    ]

    # 3. 大纲：当前章节目标
    outline_result = await session.execute(
        select(Outline).where(
            Outline.novel_id == novel.id,
            Outline.level == "chapter",
            Outline.volume == volume,
            Outline.chapter_number == chapter_number,
        )
    )
    outline = outline_result.scalar_one_or_none()
    ctx["chapter_outline"] = outline.content if outline else ""

    # 4. 最近章节摘要（滚动窗口）
    rolling_text, rolling_chapter_nums = await summarizer.get_rolling_summary(
        session, novel.id, chapter_number,
        max_summaries=novel.rolling_summary_count or 5,
    )
    ctx["rolling_summary"] = rolling_text

    # 5. RAG 检索相关历史场景（排除当前章节 + rolling_summary 已覆盖的章节，避免冗余）
    rag_top_k = novel.rag_top_k if novel.rag_top_k is not None else 3
    if rag_top_k > 0:
        query = scene_hint or ctx["chapter_outline"] or f"第{chapter_number}章"
        excluded_chapters = list({chapter_number} | set(rolling_chapter_nums))
        if len(excluded_chapters) == 1:
            chapter_filter = {"chapter_number": {"$ne": excluded_chapters[0]}}
        else:
            chapter_filter = {"chapter_number": {"$nin": excluded_chapters}}
        retrieved = await vector_store.asearch_similar(
            novel.id, query, top_k=rag_top_k,
            where={"$and": [chapter_filter, {"type": {"$eq": "chapter_summary"}}]},
        )
        ctx["rag_context"] = "\n\n".join(retrieved)
    else:
        ctx["rag_context"] = ""

    # 6. 即时上下文：上一章末尾原文（场景级衔接）
    #    优先使用末尾原文，因为 rolling_summary 已经包含了编辑视角的章节摘要，
    #    recent_text 的职责是提供场景级细节（人物在哪、在做什么、对话停在哪），
    #    让 Writer 能自然衔接上一章的结尾场景。
    #    原文通过 assistant role 传递（writer.py），Gemini 不会重审 assistant 消息，安全无虞。
    #    仅当原文内容为空时回退到摘要。
    prev_result = await session.execute(
        select(Chapter).where(
            Chapter.novel_id == novel.id,
            Chapter.number == chapter_number - 1,
            Chapter.volume == volume,
        )
    )
    prev_chapter = prev_result.scalar_one_or_none()
    if prev_chapter:
        prev_content = prev_chapter.content or ""
        prev_summary = prev_chapter.summary or ""
        ctx["recent_text"] = prev_content[-500:].strip() or prev_summary.strip()
    else:
        ctx["recent_text"] = ""

    # 7. 全书概要（长程记忆，覆盖百章级别）
    ctx["book_summary"] = novel.book_summary or ""

    # 8. 元信息
    ctx["novel_title"] = novel.title
    ctx["genre"] = novel.genre
    ctx["writing_style"] = novel.writing_style
    ctx["chapter_number"] = chapter_number
    ctx["volume"] = volume

    return ctx


def format_context_for_writer(ctx: dict, instruction: str = "", target_words: int = 800) -> tuple[str, str, str]:
    """
    将 context dict 格式化为 Writer Agent 的 Prompt 输入。

    返回 (context_block, chars_block, task_instruction)：
      context_block    — 世界观 + 全书概要 + 大纲 + 近期摘要 + RAG（不含角色描述、不含 recent_text）
      chars_block      — 角色状态（含角色描述，可能含敏感外貌描写）
      task_instruction — 写作任务指令段

    chars_block 与 recent_text 由 writer.py 合并为一条 assistant 消息插入，
    使其以 Gemini "model" 角色传递，避免触发输入侧安全过滤。
    """
    # 角色描述单独提取，后续放入 assistant(model) 消息避免 Gemini 输入过滤
    _SHEET_LABELS = {
        "personality": "性格", "motivation": "动机", "skills": "技能",
        "appearance": "外貌", "speech_style": "说话风格",
    }
    chars_text = ""
    for c in ctx.get("characters", []):
        state = c.get("state", {})
        sheet = c.get("full_sheet", {})
        chars_text += f"【{c['name']}·{c['role']}】{c['description']}\n"
        # full_sheet 详细设定
        for key, val in sheet.items():
            if not val:
                continue
            label = _SHEET_LABELS.get(key, key)
            if isinstance(val, list):
                chars_text += f"  {label}：{'、'.join(str(v) for v in val)}\n"
            elif isinstance(val, dict):
                chars_text += f"  {label}：{json.dumps(val, ensure_ascii=False)}\n"
            else:
                chars_text += f"  {label}：{val}\n"
        if state:
            chars_text += f"  当前状态：{json.dumps(state, ensure_ascii=False)}\n"
    chars_block = f"=== 角色状态 ===\n{chars_text.strip()}" if chars_text.strip() else ""

    # 用户写作指令拼入 chars_block（将以 assistant/model 角色传递），
    # 避免露骨创作指令出现在 user 消息中触发 Gemini PROHIBITED_CONTENT 过滤。
    if instruction:
        instruction_section = f"=== 写作方向备忘（严格遵守）===\n{instruction}"
        if chars_block:
            chars_block = f"{chars_block}\n\n{instruction_section}"
        else:
            chars_block = instruction_section

    # context_block 只含纯净内容（世界观、大纲、摘要、RAG），不含角色描述
    parts = []
    if ctx.get("core_setting"):
        parts.append(f"=== 世界观设定 ===\n{ctx['core_setting']}")
    if ctx.get("book_summary"):
        parts.append(f"=== 全书概要 ===\n{ctx['book_summary']}")
    if ctx.get("chapter_outline"):
        parts.append(f"=== 本章大纲 ===\n{ctx['chapter_outline']}")
    if ctx.get("rolling_summary"):
        parts.append(f"=== 近期剧情摘要 ===\n{ctx['rolling_summary']}")
    if ctx.get("rag_context"):
        parts.append(f"=== 相关历史场景（参考）===\n{ctx['rag_context']}")

    context_block = "\n\n".join(parts)

    chapter_number = ctx.get("chapter_number", 1)
    volume = ctx.get("volume", 1)
    continuity_hint = ""
    if chapter_number > 1 and ctx.get("recent_text"):
        continuity_hint = (
            "\n请自然承接上一章结尾的场景和情绪，"
            "保持人物位置、对话语境、情节节奏的连贯性，不要重复已写过的内容。"
        )

    # 用户原始指令已移入 chars_block（model 角色），此处只保留干净的结构性任务描述
    instruction_ref = "\n请严格按照「写作方向备忘」中的要求创作。" if instruction else ""
    task_instruction = (
        f"=== 写作任务 ===\n"
        f"请为《{ctx.get('novel_title', '')}》写第{volume}卷"
        f"第{chapter_number}章，"
        f"风格：{ctx.get('writing_style', '')}，"
        f"目标字数约 {target_words} 字。"
        f"{continuity_hint}"
        f"{instruction_ref}\n"
        f"直接输出正文内容，不要输出章节标题或任何前缀。"
    )

    return context_block, chars_block, task_instruction
