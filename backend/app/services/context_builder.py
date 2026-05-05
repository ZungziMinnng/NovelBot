import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.world_entity import WorldEntity
from app.models.memory import Memory, Outline
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

    # 1. 核心设定（世界观，RAG 按需检索相关段落）
    world_query = scene_hint or ""
    if not world_query:
        # 后续会填充 chapter_outline，这里先查大纲作为 query
        outline_result_tmp = await session.execute(
            select(Outline).where(
                Outline.novel_id == novel.id,
                Outline.level == "chapter",
                Outline.volume == volume,
                Outline.chapter_number == chapter_number,
            )
        )
        outline_tmp = outline_result_tmp.scalar_one_or_none()
        world_query = outline_tmp.content if outline_tmp else f"第{chapter_number}章"

    world_chunks = await vector_store.asearch_similar(
        novel.id, world_query, top_k=3,
        where={"type": {"$eq": "world_setting"}},
    )
    if world_chunks:
        ctx["core_setting"] = "\n\n".join(world_chunks)
    else:
        ctx["core_setting"] = novel.core_setting[:500] if novel.core_setting else ""

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

    # 2b. 世界实体（道具/系统）
    entity_result = await session.execute(
        select(WorldEntity).where(WorldEntity.novel_id == novel.id)
    )
    entities = entity_result.scalars().all()
    ctx["world_entities"] = [
        {
            "name": e.name,
            "type": e.type,
            "description": e.description,
            "properties": e.properties or {},
            "state": e.current_state,
        }
        for e in entities
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

    # 4b. 最近的弧摘要（中间粒度：~15章，提供本卷/本弧的中程定位）
    arc_result = await session.execute(
        select(Memory)
        .where(
            Memory.novel_id == novel.id,
            Memory.memory_type == "arc_summary",
            Memory.chapter_number < chapter_number,
        )
        .order_by(Memory.chapter_number.desc())
        .limit(1)
    )
    arc_memory = arc_result.scalar_one_or_none()
    ctx["arc_summary"] = arc_memory.content if arc_memory else ""

    # 5. RAG 检索相关历史场景
    #    - 只检索近 20 章，避免拉回早已解决的远古伏笔
    #    - 排除当前章节 + rolling_summary 已覆盖的章节，避免冗余
    rag_top_k = novel.rag_top_k if novel.rag_top_k is not None else 3
    if rag_top_k > 0:
        query = scene_hint or ctx["chapter_outline"] or f"第{chapter_number}章"
        excluded_chapters = {chapter_number} | set(rolling_chapter_nums)
        rag_chapter_filter: list = [
            {"chapter_number": {"$gte": max(1, chapter_number - 20)}},
            {"type": {"$eq": "chapter_summary"}},
        ]
        if len(excluded_chapters) == 1:
            rag_chapter_filter.append({"chapter_number": {"$ne": next(iter(excluded_chapters))}})
        else:
            rag_chapter_filter.append({"chapter_number": {"$nin": list(excluded_chapters)}})
        retrieved = await vector_store.asearch_similar(
            novel.id, query, top_k=rag_top_k,
            where={"$and": rag_chapter_filter},
        )
        ctx["rag_context"] = "\n\n".join(retrieved)
    else:
        ctx["rag_context"] = ""

    # 6. 即时上下文：上一章全文（场景级衔接）
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
        prev_content = summarizer.strip_plot_suggestions(prev_chapter.content or "")
        prev_summary = prev_chapter.summary or ""
        ctx["recent_text"] = prev_content.strip() or prev_summary.strip()
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
      context_block    — 世界观 + 全书概要 + 大纲 + 近期摘要 + RAG
      chars_block      — 角色状态 + 世界实体（不含用户写作指令）
      task_instruction — 结构性写作任务（字数、章节号等）

    用户写作指令（instruction）不嵌入任何返回值，
    由 writer.py 根据 api_format 决定放置位置：
      Gemini  → assistant(model) 角色，绕过输入侧安全过滤
      OpenAI  → 最后一条 user 消息，确保模型将其视为必须遵循的指令
    """
    _SHEET_LABELS = {
        "personality": "性格", "skills": "技能",
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
            filtered_state = {k: v for k, v in state.items() if k != "known_secrets"}
            if filtered_state:
                chars_text += f"  当前状态：{json.dumps(filtered_state, ensure_ascii=False)}\n"
    chars_block = f"=== 角色状态 ===\n{chars_text.strip()}" if chars_text.strip() else ""

    # 世界实体（道具/系统）
    _TYPE_LABELS = {"item": "道具", "system": "系统"}
    entities_text = ""
    for e in ctx.get("world_entities", []):
        type_label = _TYPE_LABELS.get(e["type"], e["type"])
        props = e.get("properties", {})
        state = e.get("state", {})
        entities_text += f"【{e['name']}·{type_label}】{e['description']}\n"
        for key, val in props.items():
            if not val:
                continue
            if isinstance(val, list):
                entities_text += f"  {key}：{'、'.join(str(v) for v in val)}\n"
            elif isinstance(val, dict):
                entities_text += f"  {key}：{json.dumps(val, ensure_ascii=False)}\n"
            else:
                entities_text += f"  {key}：{val}\n"
        if state:
            entities_text += f"  当前状态：{json.dumps(state, ensure_ascii=False)}\n"
    if entities_text.strip():
        entities_block = f"=== 世界实体 ===\n{entities_text.strip()}"
        chars_block = f"{chars_block}\n\n{entities_block}" if chars_block else entities_block

    # context_block 只含纯净内容（世界观、大纲、摘要、RAG），不含角色描述
    parts = []
    if ctx.get("core_setting"):
        parts.append(f"=== 世界观设定 ===\n{ctx['core_setting']}")
    if ctx.get("book_summary"):
        parts.append(f"=== 全书概要 ===\n{ctx['book_summary']}")
    if ctx.get("arc_summary"):
        parts.append(f"=== 近期故事弧概要 ===\n{ctx['arc_summary']}")
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

    # 结构性任务描述（不含用户写作指令——由 writer.py 根据 api_format 决定指令放置位置）
    task_instruction = (
        f"=== 写作任务 ===\n"
        f"请为《{ctx.get('novel_title', '')}》写第{volume}卷"
        f"第{chapter_number}章，"
        f"风格：{ctx.get('writing_style', '')}，"
        f"目标字数 {target_words} 字（不得低于 {int(target_words * 0.9)} 字，不得超过 {int(target_words * 1.15)} 字）。"
        f"{continuity_hint}\n"
        f"直接输出正文内容，不要输出章节标题或任何前缀。"
    )

    return context_block, chars_block, task_instruction
