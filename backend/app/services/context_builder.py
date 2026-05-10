import asyncio
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.world_entity import WorldEntity
from app.models.location import Location
from app.models.faction import Faction
from app.models.technique import Technique
from app.models.novel_note import NovelNote
from app.models.memory import Memory, Outline
from app.services import vector_store, summarizer
from app.services.relevance_selector import (
    cfg_top_k,
    rag_hits_by_type,
    select_by_name_then_rag,
    select_notes_by_title_then_rag,
)


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
    meta: list[dict] = []
    cfg = novel.context_config or {}

    def _on(key: str) -> bool:
        return cfg.get(key, True)

    def _preview(text: str, limit: int = 80) -> str:
        text = text.strip()
        return (text[:limit] + "…") if len(text) > limit else text

    # 0. 预加载大纲、近期摘要、上一章原文（用于 world_query + 名称匹配）
    outline_result = await session.execute(
        select(Outline).where(
            Outline.novel_id == novel.id,
            Outline.level == "chapter",
            Outline.volume == volume,
            Outline.chapter_number == chapter_number,
        )
    )
    outline = outline_result.scalar_one_or_none()
    outline_content = outline.content if outline else ""

    max_summaries = novel.rolling_summary_count or 5
    rolling_text, rolling_chapter_nums = await summarizer.get_rolling_summary(
        session, novel.id, chapter_number,
        volume=volume,
        max_summaries=max_summaries,
    )

    prev_result = await session.execute(
        select(Chapter).where(
            Chapter.novel_id == novel.id,
            Chapter.number == chapter_number - 1,
            Chapter.volume == volume,
        )
    )
    prev_chapter = prev_result.scalar_one_or_none()
    prev_content = ""
    if prev_chapter:
        prev_content = summarizer.strip_plot_suggestions(prev_chapter.content or "")

    # 1. 核心设定（世界观，RAG 按需检索相关段落）
    world_query = scene_hint or outline_content or f"第{chapter_number}章"

    world_chunks = await vector_store.asearch_similar(
        novel.id, world_query, top_k=3,
        where={"type": {"$eq": "world_setting"}},
    )
    if world_chunks:
        ctx["core_setting"] = "\n\n".join(world_chunks)
    else:
        ctx["core_setting"] = novel.core_setting[:500] if novel.core_setting else ""

    if not _on("core_setting"):
        meta.append({"key": "core_setting", "label": "世界观设定", "detail": "已跳过", "source": "rag", "items": [], "content": ""})
    elif ctx["core_setting"]:
        detail = f"{len(world_chunks)}条检索" if world_chunks else "字段回退"
        meta.append({"key": "core_setting", "label": "世界观设定", "detail": detail, "source": "rag", "items": [], "content": _preview(ctx["core_setting"])})
    else:
        meta.append({"key": "core_setting", "label": "世界观设定", "detail": "空", "source": "rag", "items": [], "content": ""})

    # 名称匹配文本 = 指令 + 上一章原文 + 近期摘要 + 大纲
    name_match_text = "\n".join(filter(None, [world_query, prev_content, rolling_text, outline_content]))

    # 2b. 实体加载（名称匹配优先 → RAG 兜底 → 全量回退）
    all_characters = (await session.execute(
        select(Character).where(Character.novel_id == novel.id)
    )).scalars().all()
    all_entities = (await session.execute(
        select(WorldEntity).where(WorldEntity.novel_id == novel.id)
    )).scalars().all()
    all_locations = (await session.execute(
        select(Location).where(Location.novel_id == novel.id)
    )).scalars().all()
    all_factions = (await session.execute(
        select(Faction).where(Faction.novel_id == novel.id)
    )).scalars().all()
    all_techniques = (await session.execute(
        select(Technique).where(Technique.novel_id == novel.id)
    )).scalars().all()

    # 6 路并行向量检索（top_k 可由用户在 context_config 中自定义；0 表示关闭该类 RAG 兜底）
    char_top_k = cfg_top_k(cfg, "characters_top_k", 8)
    item_top_k = cfg_top_k(cfg, "items_top_k", 5)
    sys_top_k = cfg_top_k(cfg, "systems_top_k", 3)
    loc_top_k = cfg_top_k(cfg, "locations_top_k", 5)
    fac_top_k = cfg_top_k(cfg, "factions_top_k", 4)
    tech_top_k = cfg_top_k(cfg, "techniques_top_k", 4)
    char_hits, item_hits, sys_hits, loc_hits, fac_hits, tech_hits = await asyncio.gather(
        rag_hits_by_type(novel.id, world_query, "character", char_top_k),
        rag_hits_by_type(novel.id, world_query, "entity_item", item_top_k),
        rag_hits_by_type(novel.id, world_query, "entity_system", sys_top_k),
        rag_hits_by_type(novel.id, world_query, "location", loc_top_k),
        rag_hits_by_type(novel.id, world_query, "faction", fac_top_k),
        rag_hits_by_type(novel.id, world_query, "technique", tech_top_k),
    )

    # 角色：额外支持按 role 匹配（如指令中写"男主"匹配 role="男主" 的角色）
    role_matched = [c for c in all_characters if c.role and c.role in world_query]
    char_selection = select_by_name_then_rag(all_characters, char_hits, world_query, extra=role_matched, match_text=name_match_text, allow_full=char_top_k > 0)
    characters, char_source = char_selection.items, char_selection.source
    all_items_list = [e for e in all_entities if e.type == "item"]
    all_systems_list = [e for e in all_entities if e.type == "system"]
    item_selection = select_by_name_then_rag(all_items_list, item_hits, world_query, match_text=name_match_text, allow_full=item_top_k > 0)
    sys_selection = select_by_name_then_rag(all_systems_list, sys_hits, world_query, match_text=name_match_text, allow_full=sys_top_k > 0)
    loc_selection = select_by_name_then_rag(all_locations, loc_hits, world_query, match_text=name_match_text, allow_full=loc_top_k > 0)
    fac_selection = select_by_name_then_rag(all_factions, fac_hits, world_query, match_text=name_match_text, allow_full=fac_top_k > 0)
    tech_selection = select_by_name_then_rag(all_techniques, tech_hits, world_query, match_text=name_match_text, allow_full=tech_top_k > 0)
    items_list, items_source = item_selection.items, item_selection.source
    systems_list, sys_source = sys_selection.items, sys_selection.source
    locations, loc_source = loc_selection.items, loc_selection.source
    factions, fac_source = fac_selection.items, fac_selection.source
    techniques, tech_source = tech_selection.items, tech_selection.source

    def _rag_detail(filtered, total, unit):
        if not filtered:
            return "空"
        if len(filtered) < total:
            return f"{len(filtered)}/{total}个{unit}"
        return f"{total}个{unit}"

    # 2a. 角色
    ctx["characters"] = [
        {"name": c.name, "role": c.role, "age": c.age, "description": c.description,
         "full_sheet": c.full_sheet or {}, "state": c.current_state}
        for c in characters
    ]
    ctx["_all_character_names"] = [c.name for c in all_characters]
    if not _on("characters"):
        meta.append({"key": "characters", "label": "角色状态", "detail": "已跳过", "source": char_source, "items": [], "content": ""})
    elif characters:
        meta.append({"key": "characters", "label": "角色状态", "detail": _rag_detail(characters, len(all_characters), "角色"), "source": char_source, "items": [c.name for c in characters], "content": ""})
    else:
        meta.append({"key": "characters", "label": "角色状态", "detail": "空", "source": char_source, "items": [], "content": ""})

    # 2b. 世界实体（道具/系统）
    filtered_entities = [e for e in all_entities if e.id in {x.id for x in items_list + systems_list}]
    ctx["world_entities"] = [
        {"name": e.name, "type": e.type, "description": e.description,
         "properties": e.properties or {}, "state": e.current_state}
        for e in filtered_entities
    ]
    ctx["_all_system_names"] = [e.name for e in all_entities]
    if not _on("items"):
        meta.append({"key": "items", "label": "道具", "detail": "已跳过", "source": items_source, "items": [], "content": ""})
    elif items_list:
        meta.append({"key": "items", "label": "道具", "detail": _rag_detail(items_list, len(all_items_list), "道具"), "source": items_source, "items": [e.name for e in items_list], "content": ""})
    else:
        meta.append({"key": "items", "label": "道具", "detail": "空", "source": items_source, "items": [], "content": ""})
    if not _on("systems"):
        meta.append({"key": "systems", "label": "系统", "detail": "已跳过", "source": sys_source, "items": [], "content": ""})
    elif systems_list:
        meta.append({"key": "systems", "label": "系统", "detail": _rag_detail(systems_list, len(all_systems_list), "系统"), "source": sys_source, "items": [e.name for e in systems_list], "content": ""})
    else:
        meta.append({"key": "systems", "label": "系统", "detail": "空", "source": sys_source, "items": [], "content": ""})

    # 2c. 地点
    ctx["locations"] = [
        {"name": l.name, "type": l.type, "description": l.description}
        for l in locations
    ]
    ctx["_all_location_info"] = [
        {"name": l.name, "type": l.type, "parent_name": ""}
        for l in all_locations
    ]
    if not _on("locations"):
        meta.append({"key": "locations", "label": "地点", "detail": "已跳过", "source": loc_source, "items": [], "content": ""})
    elif locations:
        meta.append({"key": "locations", "label": "地点", "detail": _rag_detail(locations, len(all_locations), "地点"), "source": loc_source, "items": [l.name for l in locations], "content": ""})
    else:
        meta.append({"key": "locations", "label": "地点", "detail": "空", "source": loc_source, "items": [], "content": ""})

    # 2d. 势力
    ctx["factions"] = [
        {"name": f.name, "type": f.type, "description": f.description,
         "leader": f.leader, "goals": f.goals}
        for f in factions
    ]
    if not _on("factions"):
        meta.append({"key": "factions", "label": "势力", "detail": "已跳过", "source": fac_source, "items": [], "content": ""})
    elif factions:
        meta.append({"key": "factions", "label": "势力", "detail": _rag_detail(factions, len(all_factions), "势力"), "source": fac_source, "items": [f.name for f in factions], "content": ""})
    else:
        meta.append({"key": "factions", "label": "势力", "detail": "空", "source": fac_source, "items": [], "content": ""})

    # 2e. 功法/武技
    ctx["techniques"] = [
        {"name": t.name, "type": t.type, "description": t.description,
         "practitioners": t.practitioners}
        for t in techniques
    ]
    ctx["_all_technique_names"] = [t.name for t in all_techniques]
    if not _on("techniques"):
        meta.append({"key": "techniques", "label": "功法", "detail": "已跳过", "source": tech_source, "items": [], "content": ""})
    elif techniques:
        meta.append({"key": "techniques", "label": "功法", "detail": _rag_detail(techniques, len(all_techniques), "功法"), "source": tech_source, "items": [t.name for t in techniques], "content": ""})
    else:
        meta.append({"key": "techniques", "label": "功法", "detail": "空", "source": tech_source, "items": [], "content": ""})

    # 2f. 补充设定笔记（名称匹配优先 → RAG 兜底 → 全量回退）
    all_notes = (await session.execute(
        select(NovelNote).where(NovelNote.novel_id == novel.id)
    )).scalars().all()

    note_top_k = cfg_top_k(cfg, "notes_top_k", 5)
    note_hits = []
    if note_top_k > 0:
        note_hits = await rag_hits_by_type(novel.id, world_query, "novel_note", note_top_k)

    effective_text = name_match_text or world_query
    note_selection = select_notes_by_title_then_rag(
        all_notes,
        note_hits,
        world_query,
        match_text=effective_text,
        allow_full=note_top_k > 0,
    )
    notes, notes_source = note_selection.items, note_selection.source

    ctx["notes"] = [
        {"title": n.title, "content": n.content}
        for n in notes
    ]
    if not _on("notes_context"):
        meta.append({"key": "notes_context", "label": "补充设定", "detail": "已跳过", "source": notes_source, "items": [], "content": ""})
    elif notes:
        meta.append({"key": "notes_context", "label": "补充设定", "detail": _rag_detail(notes, len(all_notes), "设定"), "source": notes_source, "items": [n.title for n in notes], "content": ""})
    else:
        meta.append({"key": "notes_context", "label": "补充设定", "detail": "空", "source": notes_source, "items": [], "content": ""})

    # 3. 大纲：当前章节目标（复用上面已加载的 outline）
    ctx["chapter_outline"] = outline_content
    if not _on("chapter_outline"):
        meta.append({"key": "chapter_outline", "label": "本章大纲", "detail": "已跳过", "source": "full", "items": [], "content": ""})
    elif ctx["chapter_outline"]:
        meta.append({"key": "chapter_outline", "label": "本章大纲", "detail": "", "source": "full", "items": [], "content": _preview(ctx["chapter_outline"])})
    else:
        meta.append({"key": "chapter_outline", "label": "本章大纲", "detail": "空", "source": "full", "items": [], "content": ""})

    # 4. 最近章节摘要（复用上面已加载的 rolling_text）
    ctx["rolling_summary"] = rolling_text
    if not _on("rolling_summary"):
        meta.append({"key": "rolling_summary", "label": "近期摘要", "detail": "已跳过", "source": "full", "items": [], "content": ""})
    elif rolling_text:
        meta.append({"key": "rolling_summary", "label": "近期摘要", "detail": f"{len(rolling_chapter_nums)}章", "source": "full", "items": [], "content": _preview(rolling_text)})
    else:
        meta.append({"key": "rolling_summary", "label": "近期摘要", "detail": "空", "source": "full", "items": [], "content": ""})

    # 4b. 最近的弧摘要（中间粒度：~15章，提供本卷/本弧的中程定位）
    arc_result = await session.execute(
        select(Memory)
        .where(
            Memory.novel_id == novel.id,
            Memory.memory_type == "arc_summary",
            Memory.volume == volume,
            Memory.chapter_number < chapter_number,
        )
        .order_by(Memory.chapter_number.desc())
        .limit(1)
    )
    arc_memory = arc_result.scalar_one_or_none()
    ctx["arc_summary"] = arc_memory.content if arc_memory else ""
    if not _on("arc_summary"):
        meta.append({"key": "arc_summary", "label": "故事弧概要", "detail": "已跳过", "source": "full", "items": [], "content": ""})
    elif ctx["arc_summary"]:
        meta.append({"key": "arc_summary", "label": "故事弧概要", "detail": "", "source": "full", "items": [], "content": _preview(ctx["arc_summary"])})
    else:
        meta.append({"key": "arc_summary", "label": "故事弧概要", "detail": "空", "source": "full", "items": [], "content": ""})

    # 5. RAG 检索相关历史场景
    rag_top_k = novel.rag_top_k if novel.rag_top_k is not None else 3
    if rag_top_k > 0:
        query = scene_hint or ctx["chapter_outline"] or f"第{chapter_number}章"
        excluded_chapters = {chapter_number} | set(rolling_chapter_nums)
        rag_chapter_filter: list = [
            {"chapter_number": {"$gte": max(1, chapter_number - 20)}},
            {"type": {"$eq": "chapter_summary"}},
            {"volume": {"$eq": volume}},
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
        retrieved = []
        ctx["rag_context"] = ""
    if not _on("rag_context"):
        meta.append({"key": "rag_context", "label": "RAG历史检索", "detail": "已跳过", "source": "rag", "items": [], "content": ""})
    elif ctx["rag_context"]:
        meta.append({"key": "rag_context", "label": "RAG历史检索", "detail": f"{len(retrieved)}条检索", "source": "rag", "items": [], "content": _preview(ctx["rag_context"])})
    else:
        meta.append({"key": "rag_context", "label": "RAG历史检索", "detail": "空", "source": "rag", "items": [], "content": ""})

    # 6. 即时上下文：上一章全文（复用上面已加载的 prev_chapter）
    if prev_chapter:
        prev_summary = prev_chapter.summary or ""
        ctx["recent_text"] = prev_content.strip() or prev_summary.strip()
    else:
        ctx["recent_text"] = ""
    if not _on("recent_text"):
        meta.append({"key": "recent_text", "label": "上一章原文", "detail": "已跳过", "source": "full", "items": [], "content": ""})
    elif ctx["recent_text"]:
        meta.append({"key": "recent_text", "label": "上一章原文", "detail": "", "source": "full", "items": [], "content": _preview(ctx["recent_text"])})
    else:
        meta.append({"key": "recent_text", "label": "上一章原文", "detail": "空", "source": "full", "items": [], "content": ""})

    # 7. 全书概要（长程记忆，覆盖百章级别）
    ctx["book_summary"] = novel.book_summary or ""
    if not _on("book_summary"):
        meta.append({"key": "book_summary", "label": "全书概要", "detail": "已跳过", "source": "field", "items": [], "content": ""})
    elif ctx["book_summary"]:
        meta.append({"key": "book_summary", "label": "全书概要", "detail": "", "source": "field", "items": [], "content": _preview(ctx["book_summary"])})
    else:
        meta.append({"key": "book_summary", "label": "全书概要", "detail": "空", "source": "field", "items": [], "content": ""})

    # 8. 全文上下文（实验性功能：将前 N 章完整正文传入）
    if novel.enable_full_text_context:
        n = novel.full_text_chapters or 20
        start_ch = max(1, chapter_number - n)
        full_text_result = await session.execute(
            select(Chapter).where(
                Chapter.novel_id == novel.id,
                Chapter.volume == volume,
                Chapter.number >= start_ch,
                Chapter.number < chapter_number,
            ).order_by(Chapter.number.asc())
        )
        full_text_chapters = full_text_result.scalars().all()
        full_texts = []
        for ch in full_text_chapters:
            content = summarizer.strip_plot_suggestions(ch.content or "")
            if content.strip():
                full_texts.append(f"--- 第{ch.number}章 ---\n{content}")
        ctx["full_text_context"] = "\n\n".join(full_texts)
        if full_texts:
            meta.append({"key": "full_text_context", "label": "全文上下文", "detail": f"{len(full_texts)}章全文", "source": "full", "items": [], "content": f"前{len(full_texts)}章完整正文"})
        else:
            meta.append({"key": "full_text_context", "label": "全文上下文", "detail": "空", "source": "full", "items": [], "content": ""})
    else:
        ctx["full_text_context"] = ""

    # 9. 元信息
    ctx["novel_title"] = novel.title
    ctx["genre"] = novel.genre
    ctx["writing_style"] = novel.writing_style
    ctx["chapter_number"] = chapter_number
    ctx["volume"] = volume
    ctx["context_config"] = cfg
    ctx["_meta"] = meta

    return ctx


def format_context_for_writer(ctx: dict, instruction: str = "", target_words: int = 800) -> tuple[str, str, str]:
    """
    将 context dict 格式化为 Writer Agent 的 Prompt 输入。
    通过 ctx["context_config"] 中的开关控制各区块是否包含。
    """
    cfg = ctx.get("context_config", {})
    def _on(key: str) -> bool:
        return cfg.get(key, True)

    _SHEET_LABELS = {
        "personality": "性格", "skills": "技能",
        "appearance": "外貌", "speech_style": "说话风格",
    }

    # ── 角色状态 ──
    chars_text = ""
    if _on("characters"):
        for c in ctx.get("characters", []):
            state = c.get("state", {})
            sheet = c.get("full_sheet", {})
            age_part = f"·{c['age']}岁" if c.get('age') else ""
            chars_text += f"【{c['name']}·{c['role']}{age_part}】{c['description']}\n"
            _SKIP_SHEET_KEYS = {"sd_prompt", "natural_prompt", "character_history"}
            for key, val in sheet.items():
                if not val or key in _SKIP_SHEET_KEYS:
                    continue
                label = _SHEET_LABELS.get(key, key)
                if isinstance(val, list):
                    chars_text += f"  {label}：{'、'.join(str(v) for v in val)}\n"
                elif isinstance(val, dict):
                    chars_text += f"  {label}：{json.dumps(val, ensure_ascii=False)}\n"
                else:
                    chars_text += f"  {label}：{val}\n"
            if state:
                filtered_state = {k: v for k, v in state.items()
                                  if k not in ("known_secrets", "initial_relationships", "relationship_changes")}
                if filtered_state:
                    chars_text += f"  当前状态：{json.dumps(filtered_state, ensure_ascii=False)}\n"
                initial_rels = state.get("initial_relationships", {})
                ongoing_rels = state.get("relationship_changes", {})
                rels: dict = {}
                if isinstance(initial_rels, dict):
                    rels.update(initial_rels)
                if isinstance(ongoing_rels, dict):
                    rels.update(ongoing_rels)
                if rels:
                    chars_text += f"  人物关系：{json.dumps(rels, ensure_ascii=False)}\n"
    chars_block = f"=== 角色状态 ===\n{chars_text.strip()}" if chars_text.strip() else ""

    # ── 世界实体（道具/系统，分别受 items / systems 开关控制）──
    _TYPE_LABELS = {"item": "道具", "system": "系统"}
    _TYPE_CONFIG = {"item": "items", "system": "systems"}
    entities_text = ""
    for e in ctx.get("world_entities", []):
        cfg_key = _TYPE_CONFIG.get(e["type"], "items")
        if not _on(cfg_key):
            continue
        type_label = _TYPE_LABELS.get(e["type"], e["type"])
        props = e.get("properties", {})
        e_state = e.get("state", {})
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
        if e_state:
            entities_text += f"  当前状态：{json.dumps(e_state, ensure_ascii=False)}\n"
    if entities_text.strip():
        entities_block = f"=== 世界实体 ===\n{entities_text.strip()}"
        chars_block = f"{chars_block}\n\n{entities_block}" if chars_block else entities_block

    # ── 地点 ──
    if _on("locations"):
        loc_lines = []
        for l in ctx.get("locations", []):
            loc_lines.append(f"【{l['name']}·{l['type']}】{l['description']}")
        if loc_lines:
            loc_block = f"=== 地点 ===\n" + "\n".join(loc_lines)
            chars_block = f"{chars_block}\n\n{loc_block}" if chars_block else loc_block

    # ── 势力 ──
    if _on("factions"):
        fac_lines = []
        for f in ctx.get("factions", []):
            line = f"【{f['name']}·{f['type']}】{f['description']}"
            if f.get("leader"):
                line += f"（首领：{f['leader']}）"
            if f.get("goals"):
                line += f"\n  目标：{f['goals']}"
            fac_lines.append(line)
        if fac_lines:
            fac_block = f"=== 势力 ===\n" + "\n".join(fac_lines)
            chars_block = f"{chars_block}\n\n{fac_block}" if chars_block else fac_block

    # ── 功法/武技 ──
    if _on("techniques"):
        tech_lines = []
        for t in ctx.get("techniques", []):
            line = f"【{t['name']}·{t['type']}】{t['description']}"
            if t.get("practitioners"):
                line += f"（修习者：{t['practitioners']}）"
            tech_lines.append(line)
        if tech_lines:
            tech_block = f"=== 功法 ===\n" + "\n".join(tech_lines)
            chars_block = f"{chars_block}\n\n{tech_block}" if chars_block else tech_block

    # ── 补充设定笔记 ──
    if _on("notes_context"):
        notes_lines = []
        for n in ctx.get("notes", []):
            notes_lines.append(f"【{n['title']}】{n['content']}")
        if notes_lines:
            notes_block = f"=== 补充设定 ===\n" + "\n".join(notes_lines)
            chars_block = f"{chars_block}\n\n{notes_block}" if chars_block else notes_block

    # ── context_block（世界观、大纲、摘要、RAG）──
    parts = []
    if _on("core_setting") and ctx.get("core_setting"):
        parts.append(f"=== 世界观设定 ===\n{ctx['core_setting']}")
    if _on("book_summary") and ctx.get("book_summary"):
        parts.append(f"=== 全书概要 ===\n{ctx['book_summary']}")
    if _on("arc_summary") and ctx.get("arc_summary"):
        parts.append(f"=== 近期故事弧概要 ===\n{ctx['arc_summary']}")
    if _on("chapter_outline") and ctx.get("chapter_outline"):
        parts.append(f"=== 本章大纲 ===\n{ctx['chapter_outline']}")
    if _on("rolling_summary") and ctx.get("rolling_summary"):
        parts.append(f"=== 近期剧情摘要 ===\n{ctx['rolling_summary']}")
    if _on("rag_context") and ctx.get("rag_context"):
        parts.append(f"=== 相关历史场景（参考）===\n{ctx['rag_context']}")

    if ctx.get("full_text_context"):
        parts.append(f"=== 前文正文（全文）===\n{ctx['full_text_context']}")

    context_block = "\n\n".join(parts)

    chapter_number = ctx.get("chapter_number", 1)
    volume = ctx.get("volume", 1)
    continuity_hint = ""
    if _on("recent_text") and chapter_number > 1 and ctx.get("recent_text"):
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
