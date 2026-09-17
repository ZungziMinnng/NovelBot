import asyncio
import json
import logging
import re
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
from app.models.glossary_entry import GlossaryEntry
from app.models.memory import Memory, Outline
from app.models.worldview_change import WorldviewChange
from app.models.world_rule import WorldRule
from app.models.story_thread import StoryThread
from app.models.model_library import ModelEntry
from app.services import llm_client, outline_plan, reranker, vector_store, summarizer
from app.services.context_budget import (
    DEFAULT_CONTEXT_WINDOW,
    build_context_budget,
    estimate_tokens,
    truncate_to_token_budget,
)
from app.services.relevance_selector import (
    OVERFETCH,
    cfg_top_k,
    diversify_historical_hits,
    keyword_hits,
    rag_hits_by_type,
    rerank_by_importance,
    select_by_name_then_rag,
    select_notes_by_title_then_rag,
)
from app.services.text_ranking import bm25_rank, rrf_fuse
from app.services.thread_selector import cap_glossary, select_story_threads
from app.services import prompt_rules
from app.prompts import genre_cards


logger = logging.getLogger(__name__)

_ANY_DAY_RE = re.compile(r"第(\d+)日")


def _latest_story_day(*texts: str) -> int | None:
    """取参考资料里出现过的最大绝对天数，作为“当前故事时间”锚点。

    摘要按章序累积，最大天数即最近一章的故事时间。
    """
    days = [
        int(m.group(1))
        for text in texts
        if text
        for m in _ANY_DAY_RE.finditer(text)
    ]
    return max(days) if days else None


def _text_for_reference_scan(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _character_reference_text(character: Character) -> str:
    return "\n".join(
        part for part in (
            character.description or "",
            _text_for_reference_scan(character.full_sheet or {}),
            _text_for_reference_scan(character.current_state or {}),
        )
        if part
    )


def _add_entities_referenced_by_characters(
    characters: list[Character],
    items: list[WorldEntity],
    systems: list[WorldEntity],
    all_items: list[WorldEntity],
    all_systems: list[WorldEntity],
) -> tuple[int, int]:
    """Include item/system cards mentioned inside selected character data."""
    scan_text = "\n".join(_character_reference_text(c) for c in characters)
    if not scan_text:
        return 0, 0

    selected_ids = {e.id for e in items + systems}
    added_items = 0
    added_systems = 0
    for entity in [*all_items, *all_systems]:
        name = (entity.name or "").strip()
        if entity.id in selected_ids or len(name) < 2:
            continue
        if name not in scan_text:
            continue
        if entity.type == "system":
            systems.append(entity)
            added_systems += 1
        else:
            items.append(entity)
            added_items += 1
        selected_ids.add(entity.id)
    return added_items, added_systems


async def build_generation_context(
    session: AsyncSession,
    novel: Novel,
    chapter_number: int,
    volume: int = 1,
    scene_hint: str = "",
    pov: str = "",
    target_words: int = 2500,
) -> dict:
    """
    组装生成章节所需的全部上下文，返回结构化 dict。
    各 Agent 从这个 dict 中取自己需要的部分。
    """
    # 嵌入模型配置加载失败（缺 Key/Base URL、模型未录入等）不应导致整章生成失败，
    # 退回默认模型即可：RAG 检索失败会被各 search 的 try/except 降级为空结果。
    try:
        await vector_store.ensure_embedding_configured(novel.id, session)
    except Exception:
        logger.warning("小说 %s 嵌入模型配置加载失败，回退默认模型", novel.id, exc_info=True)

    ctx = {}
    meta: list[dict] = []
    cfg = novel.context_config or {}

    context_window = DEFAULT_CONTEXT_WINDOW
    writer_ref, _ = llm_client.get_agent_client(
        "writer",
        (novel.writer_model or "").strip(),
    )
    writer_ref = (writer_ref or "").strip()
    model_entry = None
    if writer_ref.isdigit():
        model_entry = await session.get(ModelEntry, int(writer_ref))
    elif writer_ref:
        model_entry = (await session.execute(
            select(ModelEntry)
            .where(ModelEntry.model_id == writer_ref, ModelEntry.model_type == "chat")
            .order_by(ModelEntry.id)
            .limit(1)
        )).scalar_one_or_none()
    if model_entry and model_entry.context_window:
        context_window = model_entry.context_window

    input_price = float(model_entry.input_price or 0) if model_entry else 0.0
    output_price = float(model_entry.output_price or 0) if model_entry else 0.0
    currency_to_cny_rate = float(model_entry.currency_to_cny_rate or 1) if model_entry else 1.0
    ctx["_pricing"] = {
        "model_entry_id": model_entry.id if model_entry else None,
        "model_name": (model_entry.display_name or model_entry.model_id) if model_entry else writer_ref,
        "currency": (model_entry.price_currency or "CNY") if model_entry else "CNY",
        "currency_to_cny_rate": currency_to_cny_rate,
        "input_price_per_million": input_price,
        "output_price_per_million": output_price,
        "input_price_cny_per_million": input_price * currency_to_cny_rate,
        "output_price_cny_per_million": output_price * currency_to_cny_rate,
        "configured": bool(input_price or output_price),
    }

    budget = build_context_budget(
        target_words=target_words,
        context_window=context_window,
        writer_max_tokens=novel.writer_max_tokens or 16384,
        thinking_enabled=bool(getattr(novel, "enable_thinking", True)),
    )
    ctx["_budget"] = budget.to_dict()

    def _on(key: str) -> bool:
        return cfg.get(key, True)

    def _preview(text: str) -> str:
        # 不截断：上下文状态面板需要完整查看各区块内容（前端限高滚动展示）
        return text.strip()

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
    if outline and (plan_line := outline_plan.format_plan(
        chapter_role=outline.chapter_role,
        emotion_tone=outline.emotion_tone,
        emotion_intensity=outline.emotion_intensity,
        hook_type=outline.hook_type,
        hook_strength=outline.hook_strength,
    )):
        outline_content = f"{outline_content}\n【执行计划】{plan_line}".strip()

    max_summaries = novel.rolling_summary_count or 8
    rolling_text, rolling_chapter_nums = await summarizer.get_rolling_summary(
        session, novel.id, chapter_number,
        volume=volume,
        max_summaries=max_summaries,
        token_budget=budget.allocations["rolling_summary"],
        min_summaries=min(3, max_summaries),
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
    # 同一 world_query 供本函数内全部检索复用，只计算一次嵌入
    world_query_emb = await vector_store.aembed_query(novel.id, world_query)

    world_chunks = await vector_store.asearch_similar(
        novel.id, world_query, top_k=3,
        where={"type": {"$eq": "world_setting"}},
        query_embedding=world_query_emb,
    )
    if world_chunks:
        ctx["core_setting"] = "\n\n".join(world_chunks)
    else:
        ctx["core_setting"] = novel.core_setting[:500] if novel.core_setting else ""

    # 核心规则：约束型设定基石，始终完整注入（查结构化表，不走 RAG，避免被检索稀释或截断）；
    # 特殊元素属素材而非约束，改为按需选取（标题命中 → RAG → 兜底），选取逻辑在实体加载阶段
    rules_result = await session.execute(
        select(WorldRule)
        .where(WorldRule.novel_id == novel.id, WorldRule.enabled == True)  # noqa: E712
        .order_by(WorldRule.importance.desc(), WorldRule.id)
    )
    by_kind: dict[str, list[WorldRule]] = {"rule": [], "element": []}
    for r in rules_result.scalars().all():
        by_kind.setdefault(r.kind, []).append(r)
    all_elements = by_kind.get("element", [])

    def _rule_line(r: WorldRule) -> str:
        return f"【{r.title.strip()}】{r.content.strip()}" if (r.title or "").strip() else r.content.strip()

    rule_lines = [
        _rule_line(r) for r in by_kind.get("rule", [])
        if (r.content or "").strip() or (r.title or "").strip()
    ]
    ctx["core_rules"] = f"## 核心规则\n" + "\n".join(rule_lines) if rule_lines else ""

    if not _on("core_setting"):
        meta.append({"key": "core_setting", "label": "世界观设定", "detail": "已跳过", "source": "mixed", "items": [], "content": ""})
    elif ctx["core_setting"] or ctx["core_rules"]:
        bg_detail = f"{len(world_chunks)}条检索" if world_chunks else ("字段回退" if ctx["core_setting"] else "无背景")
        rules_detail = "规则常驻+" if ctx["core_rules"] else ""
        preview_src = f"{ctx['core_rules']}\n\n{ctx['core_setting']}".strip()
        meta.append({"key": "core_setting", "label": "世界观设定", "detail": f"{rules_detail}{bg_detail}", "source": "mixed", "items": [], "content": _preview(preview_src)})
    else:
        meta.append({"key": "core_setting", "label": "世界观设定", "detail": "空", "source": "mixed", "items": [], "content": ""})

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
    elem_top_k = cfg_top_k(cfg, "elements_top_k", 4)
    char_hits, item_hits, sys_hits, loc_hits, fac_hits, tech_hits, elem_hits = await asyncio.gather(
        rag_hits_by_type(novel.id, world_query, "character", char_top_k, query_embedding=world_query_emb),
        rag_hits_by_type(novel.id, world_query, "entity_item", item_top_k, query_embedding=world_query_emb),
        rag_hits_by_type(novel.id, world_query, "entity_system", sys_top_k, query_embedding=world_query_emb),
        rag_hits_by_type(novel.id, world_query, "location", loc_top_k, query_embedding=world_query_emb),
        rag_hits_by_type(novel.id, world_query, "faction", fac_top_k, query_embedding=world_query_emb),
        rag_hits_by_type(novel.id, world_query, "technique", tech_top_k, query_embedding=world_query_emb),
        rag_hits_by_type(novel.id, world_query, "world_element", elem_top_k, query_embedding=world_query_emb),
    )

    # 角色：额外支持按 role 匹配（如指令中写"男主"匹配 role="男主" 的角色）
    role_matched = [c for c in all_characters if c.role and c.role in world_query]
    char_selection = select_by_name_then_rag(all_characters, char_hits, world_query, extra=role_matched, match_text=name_match_text, allow_full=char_top_k > 0, fallback_limit=char_top_k * 2)
    characters, char_source = char_selection.items, char_selection.source
    all_items_list = [e for e in all_entities if e.type == "item"]
    all_systems_list = [e for e in all_entities if e.type == "system"]
    item_selection = select_by_name_then_rag(all_items_list, item_hits, world_query, match_text=name_match_text, allow_full=item_top_k > 0, fallback_limit=item_top_k * 2)
    sys_selection = select_by_name_then_rag(all_systems_list, sys_hits, world_query, match_text=name_match_text, allow_full=sys_top_k > 0, fallback_limit=sys_top_k * 2)
    loc_selection = select_by_name_then_rag(all_locations, loc_hits, world_query, match_text=name_match_text, allow_full=loc_top_k > 0, fallback_limit=loc_top_k * 2)
    fac_selection = select_by_name_then_rag(all_factions, fac_hits, world_query, match_text=name_match_text, allow_full=fac_top_k > 0, fallback_limit=fac_top_k * 2)
    tech_selection = select_by_name_then_rag(all_techniques, tech_hits, world_query, match_text=name_match_text, allow_full=tech_top_k > 0, fallback_limit=tech_top_k * 2)
    items_list, items_source = item_selection.items, item_selection.source
    systems_list, sys_source = sys_selection.items, sys_selection.source
    locations, loc_source = loc_selection.items, loc_selection.source
    factions, fac_source = fac_selection.items, fac_selection.source
    techniques, tech_source = tech_selection.items, tech_selection.source

    ref_items, ref_systems = _add_entities_referenced_by_characters(
        characters,
        items_list,
        systems_list,
        all_items_list,
        all_systems_list,
    )
    if ref_items:
        items_source = f"{items_source}+ref" if len(items_list) > ref_items else "ref"
    if ref_systems:
        sys_source = f"{sys_source}+ref" if len(systems_list) > ref_systems else "ref"

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

    # 本章视角角色（POV）：显式指定 > 男主 > 空（空时所有秘密都视为未知情）
    pov_name = pov.strip()
    if not pov_name:
        lead = next((c for c in all_characters if (c.role or "") in ("男主", "主角")), None)
        pov_name = lead.name if lead else ""
    ctx["pov"] = pov_name
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
         "function": e.function or "",
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
        {"name": l.name, "type": l.type, "description": l.description, "state": l.current_state}
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
    ctx["_all_faction_names"] = [f.name for f in all_factions]
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

    # 2e-2. 特殊元素（按需选取，选中的并入核心规则区块，写作时同受"必须严格遵守"约束）
    elem_selection = select_by_name_then_rag(
        all_elements, elem_hits, world_query,
        name_getter=lambda r: (r.title or "").strip() or None,
        match_text=name_match_text,
        allow_full=elem_top_k > 0,
    )
    elements, elem_source = elem_selection.items, elem_selection.source
    elem_lines = [
        _rule_line(r) for r in elements
        if (r.content or "").strip() or (r.title or "").strip()
    ]
    if elem_lines:
        elem_block = "## 特殊元素\n" + "\n".join(elem_lines)
        ctx["core_rules"] = f"{ctx['core_rules']}\n\n{elem_block}" if ctx["core_rules"] else elem_block
    if not _on("core_setting"):
        meta.append({"key": "special_elements", "label": "特殊元素", "detail": "已跳过", "source": elem_source, "items": [], "content": ""})
    elif elements:
        meta.append({"key": "special_elements", "label": "特殊元素", "detail": _rag_detail(elements, len(all_elements), "元素"), "source": elem_source, "items": [(r.title or "").strip() or r.content[:12] for r in elements], "content": ""})
    else:
        meta.append({"key": "special_elements", "label": "特殊元素", "detail": "空", "source": elem_source, "items": [], "content": ""})

    # 2f. 补充设定笔记（名称匹配优先 → RAG 兜底 → 全量回退）
    all_notes = (await session.execute(
        select(NovelNote).where(NovelNote.novel_id == novel.id)
    )).scalars().all()

    note_top_k = cfg_top_k(cfg, "notes_top_k", 5)
    note_hits = []
    if note_top_k > 0:
        note_hits = await rag_hits_by_type(novel.id, world_query, "novel_note", note_top_k, query_embedding=world_query_emb)

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

    # 2g. 用词库（全量加载后按字符预算截断，防止条目积累撑爆 prompt）
    all_glossary = (await session.execute(
        select(GlossaryEntry).where(GlossaryEntry.novel_id == novel.id)
    )).scalars().all()

    ctx["glossary"] = cap_glossary([
        {
            "term": g.term,
            "category": g.category,
            "forbidden_variants": g.forbidden_variants,
            "notes": g.notes,
        }
        for g in all_glossary
    ])
    if not _on("glossary"):
        meta.append({"key": "glossary", "label": "用词库", "detail": "已跳过", "source": "full", "items": [], "content": ""})
    elif ctx["glossary"]:
        glossary_detail = f"{len(ctx['glossary'])}条目" if len(ctx["glossary"]) == len(all_glossary) else f"{len(ctx['glossary'])}/{len(all_glossary)}条目（预算截断）"
        meta.append({"key": "glossary", "label": "用词库", "detail": glossary_detail, "source": "full", "items": [g["term"] for g in ctx["glossary"]], "content": ""})
    else:
        meta.append({"key": "glossary", "label": "用词库", "detail": "空", "source": "full", "items": [], "content": ""})

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
    overview_budget = budget.allocations["overview"]
    ctx["arc_summary"] = truncate_to_token_budget(
        arc_memory.content if arc_memory else "",
        int(overview_budget * 0.4),
    )
    if not _on("arc_summary"):
        meta.append({"key": "arc_summary", "label": "故事弧概要", "detail": "已跳过", "source": "full", "items": [], "content": ""})
    elif ctx["arc_summary"]:
        meta.append({"key": "arc_summary", "label": "故事弧概要", "detail": "", "source": "full", "items": [], "content": _preview(ctx["arc_summary"])})
    else:
        meta.append({"key": "arc_summary", "label": "故事弧概要", "detail": "空", "source": "full", "items": [], "content": ""})

    # 5. RAG 检索相关历史场景
    rag_top_k = novel.rag_top_k if novel.rag_top_k is not None else 6
    if rag_top_k > 0:
        # 查询只用「指令+大纲」：近期摘要已作为独立区块注入，混入查询会
        # 喧宾夺主（上一章的题材主导检索方向）。两者皆空才用摘要尾部兜底。
        query = "\n".join(filter(None, [
            scene_hint.strip(),
            ctx["chapter_outline"].strip(),
        ])) or rolling_text[-1500:].strip() or f"第{chapter_number}章"
        excluded_chapters = {chapter_number} | set(rolling_chapter_nums)
        # 不按卷过滤：章节号全书连续，跨卷检索让第二卷也能想起第一卷的剧情
        rag_chapter_filter: list = [
            {"chapter_number": {"$lt": chapter_number}},
            {"type": {"$eq": "chapter_summary"}},
        ]
        if len(excluded_chapters) == 1:
            rag_chapter_filter.append({"chapter_number": {"$ne": next(iter(excluded_chapters))}})
        else:
            rag_chapter_filter.append({"chapter_number": {"$nin": list(excluded_chapters)}})
        # 混合检索：向量（语义）+ BM25（关键词/专有名词）两路各排一遍，RRF 按名次融合。
        # 章节摘要语料一次查库，BM25 与后面的 4-gram 兜底共用。
        summary_stmt = select(Memory).where(
            Memory.novel_id == novel.id,
            Memory.memory_type == "chapter_summary",
            Memory.chapter_number < chapter_number,
        )
        if excluded_chapters:
            summary_stmt = summary_stmt.where(
                ~Memory.chapter_number.in_(sorted(excluded_chapters))
            )
        summary_memories = (await session.execute(summary_stmt.order_by(Memory.id))).scalars().all()
        bm25_candidates = list({
            m.chapter_number: {
                "text": m.content,
                "metadata": {"chapter_number": m.chapter_number, "importance": m.importance},
            }
            for m in summary_memories if (m.content or "").strip()
        }.values())

        rag_hits = await vector_store.asearch_similar_with_meta(
            novel.id, query, top_k=rag_top_k * OVERFETCH,
            where={"$and": rag_chapter_filter},
        )
        vector_ranked = rerank_by_importance(rag_hits, rag_top_k * OVERFETCH, current_chapter=chapter_number)
        bm25_ranked = bm25_rank(query, bm25_candidates, rag_top_k * OVERFETCH)
        fused_hits = rrf_fuse(
            vector_ranked, bm25_ranked,
            key=lambda h: (h.get("metadata") or {}).get("chapter_number"),
        )
        # 交叉编码重排：RRF 只看名次不看内容，这里对融合头部成对精读打分，
        # 分辨"词都对上但讲的不是这件事"的候选。模型不可用时原样返回。
        rerank_applied = False
        if _on("rerank"):
            fused_hits, rerank_applied = await asyncio.to_thread(
                reranker.rerank_hits, query, fused_hits,
            )
        ranked_hits = diversify_historical_hits(fused_hits, rag_top_k)
        retrieved = []
        retrieved_tokens = 0
        used_chapters: set = set()
        hit_chapter_order: list[int] = []
        rag_budget = budget.allocations["rag_context"]
        minimum_rag = min(3, rag_top_k)
        for hit in ranked_hits:
            if not hit.get("text"):
                continue
            hit_meta = hit.get("metadata") or {}
            source_chapter = hit_meta.get("chapter_number")
            label = f"【第{source_chapter}章·历史证据】" if source_chapter else "【历史证据】"
            item = f"{label}{hit['text']}"
            item_tokens = estimate_tokens(item)
            if retrieved and retrieved_tokens + item_tokens > rag_budget and len(retrieved) >= minimum_rag:
                break
            retrieved.append(item)
            retrieved_tokens += item_tokens
            if source_chapter is not None:
                used_chapters.add(source_chapter)
                if source_chapter not in hit_chapter_order:
                    hit_chapter_order.append(source_chapter)

        # Embedding 服务不可用时，保留一条确定性的 SQL 降级路径。优先取高重要性
        # 摘要，再取较近章节，避免网络故障直接清空全部历史记忆。
        if not retrieved:
            fallback_stmt = select(Memory).where(
                Memory.novel_id == novel.id,
                Memory.memory_type == "chapter_summary",
                Memory.chapter_number < chapter_number,
            )
            if excluded_chapters:
                fallback_stmt = fallback_stmt.where(
                    ~Memory.chapter_number.in_(sorted(excluded_chapters))
                )
            fallback_memories = (await session.execute(
                fallback_stmt
                .order_by(Memory.importance.desc(), Memory.chapter_number.desc())
                .limit(rag_top_k)
            )).scalars().all()
            used_chapters.update(m.chapter_number for m in fallback_memories)
            retrieved = []
            retrieved_tokens = 0
            for m in fallback_memories:
                if not (m.content or "").strip():
                    continue
                item = f"【第{m.chapter_number}章·高重要性历史证据】{m.content}"
                item_tokens = estimate_tokens(item)
                if retrieved and retrieved_tokens + item_tokens > rag_budget and len(retrieved) >= minimum_rag:
                    break
                retrieved.append(item)
                retrieved_tokens += item_tokens
                if m.chapter_number not in hit_chapter_order:
                    hit_chapter_order.append(m.chapter_number)

        # 5b. 关键词精确匹配兜底：向量检索会把「月华顿悟」这类独特短语稀释在
        # 整段查询里，这里用查询文本的中文 4-gram 与全部老章节摘要做精确交集，
        # 把向量没捞回来的相关老章节补进上下文（有独立的小额预算，不挤占向量结果）。
        kw_candidates = list({
            m.chapter_number: {"chapter_number": m.chapter_number, "content": m.content}
            for m in summary_memories
            if (m.content or "").strip() and m.chapter_number not in used_chapters
        }.values())
        kw_budget = rag_budget // 3
        kw_tokens = 0
        kw_count = 0
        for s in keyword_hits(query, kw_candidates, top_k=3):
            item = f"【第{s['chapter_number']}章·关键词命中】{s['content']}"
            item_tokens = estimate_tokens(item)
            if kw_count and kw_tokens + item_tokens > kw_budget:
                break
            retrieved.append(item)
            kw_tokens += item_tokens
            kw_count += 1
            if s["chapter_number"] not in hit_chapter_order:
                hit_chapter_order.append(s["chapter_number"])
        ctx["rag_context"] = "\n\n".join(retrieved)
    else:
        retrieved = []
        kw_count = 0
        rerank_applied = False
        hit_chapter_order = []
        ctx["rag_context"] = ""
    if not _on("rag_context"):
        meta.append({"key": "rag_context", "label": "RAG历史检索", "detail": "已跳过", "source": "rag", "items": [], "content": ""})
    elif ctx["rag_context"]:
        rag_detail = (
            f"{len(retrieved)}条检索"
            + ("（已重排）" if rerank_applied else "")
            + (f"（含{kw_count}条关键词命中）" if kw_count else "")
        )
        meta.append({"key": "rag_context", "label": "RAG历史检索", "detail": rag_detail, "source": "rag", "items": [], "content": _preview(ctx["rag_context"])})
    else:
        meta.append({"key": "rag_context", "label": "RAG历史检索", "detail": "空", "source": "rag", "items": [], "content": ""})

    # 5c. 两跳原文取段：检索已定位到章（摘要命中），第二跳回读这些章的原文，
    # 按"本章要写什么"（指令+大纲）捞出最相关的段落注入，补回摘要压缩丢掉的原文细节。
    ctx["rag_fulltext"] = ""
    fulltext_query = "\n".join(filter(None, [scene_hint.strip(), ctx["chapter_outline"].strip()]))
    if _on("rag_fulltext") and hit_chapter_order and fulltext_query:
        ctx["rag_fulltext"] = await _build_rag_fulltext(
            session, novel.id, hit_chapter_order[:3], fulltext_query,
            token_budget=budget.allocations["rag_fulltext"],
        )
        if ctx["rag_fulltext"]:
            ft_count = ctx["rag_fulltext"].count("章原文】")
            meta.append({"key": "rag_fulltext", "label": "历史原文取段", "detail": f"{ft_count}段原文", "source": "rag", "items": [], "content": _preview(ctx["rag_fulltext"])})

    # 6. 即时上下文：上一章全文（复用上面已加载的 prev_chapter）
    # 全文强制完整注入，不受 token 预算约束——衔接质量优先于成本
    if prev_chapter:
        ctx["recent_text"] = prev_content.strip() or (prev_chapter.summary or "").strip()
    else:
        ctx["recent_text"] = ""
    if not _on("recent_text"):
        meta.append({"key": "recent_text", "label": "上一章原文", "detail": "已跳过", "source": "full", "items": [], "content": ""})
    elif ctx["recent_text"]:
        meta.append({"key": "recent_text", "label": "上一章原文", "detail": "", "source": "full", "items": [], "content": _preview(ctx["recent_text"])})
    else:
        meta.append({"key": "recent_text", "label": "上一章原文", "detail": "空", "source": "full", "items": [], "content": ""})

    # 7. 全书概要（长程记忆，覆盖百章级别）
    ctx["book_summary"] = truncate_to_token_budget(
        novel.book_summary or "",
        int(overview_budget * 0.6),
    )
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

    # 8b. 世界观变更（截至本章生效的已确认条目，覆盖原世界观设定）
    wv_changes = (await session.execute(
        select(WorldviewChange).where(
            WorldviewChange.novel_id == novel.id,
            WorldviewChange.status == "confirmed",
            WorldviewChange.effective_chapter <= chapter_number,
        ).order_by(WorldviewChange.effective_chapter)
    )).scalars().all()
    ctx["worldview_changes"] = [
        {"fact": c.fact, "effective_chapter": c.effective_chapter}
        for c in wv_changes
    ]
    if wv_changes:
        meta.append({"key": "worldview_changes", "label": "世界观变更", "detail": f"{len(wv_changes)}条生效", "source": "field", "items": [], "content": _preview("；".join(c.fact for c in wv_changes))})

    # 8c. 独立伏笔/秘密库：活跃条目是确定性长期记忆，不依赖向量召回。
    story_threads = (await session.execute(
        select(StoryThread).where(
            StoryThread.novel_id == novel.id,
            # expired 与 abandoned 同样不注入：过期伏笔当悬念写会让读者觉得作者在硬圆
            StoryThread.status.notin_(("abandoned", "expired")),
            StoryThread.source_chapter < chapter_number,
        ).order_by(StoryThread.importance.desc(), StoryThread.source_chapter, StoryThread.id)
    )).scalars().all()
    ctx["story_threads"] = select_story_threads(
        [
            {
                "kind": thread.kind,
                "title": thread.title,
                "content": thread.content,
                "status": thread.status,
                "source_chapter": thread.source_chapter,
                "due_chapter": thread.due_chapter,
                "resolved_chapter": thread.resolved_chapter,
                "resolution": thread.resolution,
                "known_by": thread.known_by or [],
                "related_entities": thread.related_entities or [],
                "importance": thread.importance,
            }
            for thread in story_threads
        ],
        chapter_number,
        # 关联过滤：标注了关联名的伏笔只在相关设定入选本章上下文时载入
        active_names={
            obj.name.strip()
            for group in (characters, items_list, systems_list, locations, factions, techniques)
            for obj in group
            if (obj.name or "").strip()
        },
    )
    if ctx["story_threads"]:
        thread_detail = (
            f"{len(ctx['story_threads'])}条有效记录"
            if len(ctx["story_threads"]) == len(story_threads)
            else f"{len(ctx['story_threads'])}/{len(story_threads)}条（关联/预算筛选）"
        )
        meta.append({
            "key": "story_threads",
            "label": "伏笔/秘密",
            "detail": thread_detail,
            "source": "field",
            "items": [t["title"] or t["content"][:20] for t in ctx["story_threads"]],
            "content": _preview("；".join(t["content"] for t in ctx["story_threads"])),
        })

    # 8d. 关系里程碑：角色间情感/关系转折的确定性长期记忆（不依赖向量召回），
    # 回忆过往情感线时以此为事实基准，杜绝凭空编造"何时动心/何时决裂"。
    ctx["relationship_milestones"] = []
    milestone_rows: list[Memory] = []
    if _on("relationship_milestones"):
        milestone_rows = (await session.execute(
            select(Memory).where(
                Memory.novel_id == novel.id,
                Memory.memory_type == "relationship_milestone",
                Memory.chapter_number < chapter_number,
                Memory.in_context.is_(True),
            ).order_by(Memory.chapter_number, Memory.id)
        )).scalars().all()
        ms_budget = budget.allocations["relationship_milestones"]
        selected = milestone_rows
        if sum(estimate_tokens(m.content) for m in milestone_rows) > ms_budget:
            # 超预算按重要度优先保留，输出仍按章节顺序
            picked, used = [], 0
            for m in sorted(milestone_rows, key=lambda m: (-(m.importance or 3), m.chapter_number or 0)):
                t = estimate_tokens(m.content)
                if picked and used + t > ms_budget:
                    continue
                picked.append(m)
                used += t
            selected = sorted(picked, key=lambda m: (m.chapter_number or 0, m.id))
        ctx["relationship_milestones"] = [m.content for m in selected]
        if selected:
            ms_detail = (
                f"{len(selected)}条"
                if len(selected) == len(milestone_rows)
                else f"{len(selected)}/{len(milestone_rows)}条（预算筛选）"
            )
            meta.append({"key": "relationship_milestones", "label": "关系里程碑", "detail": ms_detail, "source": "field", "items": [], "content": _preview("；".join(ctx["relationship_milestones"]))})

    # 8e. 回忆取证：指令/大纲含回忆意图时，两跳检索——先在"定位池"里 BM25 命中相关章，
    # 再回读该章原文捞出最相关段落，让回忆戏有真实原文细节可依。
    # 定位池 = 关系里程碑（感情事实）+ 历史章节摘要（前世身世/高考/夙愿等背景硬事实——
    # 这类不进里程碑，仅靠里程碑池会漏，导致重生流写"前世"时反复现编、跨章矛盾）。
    ctx["recall_evidence"] = ""
    recall_query = "\n".join(filter(None, [scene_hint.strip(), outline_content.strip()]))
    if _on("recall_evidence") and _has_recall_intent(recall_query):
        summary_rows = (await session.execute(
            select(Memory).where(
                Memory.novel_id == novel.id,
                Memory.memory_type == "chapter_summary",
                Memory.chapter_number < chapter_number,
            ).order_by(Memory.chapter_number, Memory.id)
        )).scalars().all()
        locate_pool = list(milestone_rows) + list(summary_rows)
        if locate_pool:
            ctx["recall_evidence"] = await _build_recall_evidence(
                session, novel.id, locate_pool, recall_query,
                token_budget=budget.allocations["recall_evidence"],
            )
        if ctx["recall_evidence"]:
            meta.append({"key": "recall_evidence", "label": "回忆取证", "detail": "已触发", "source": "rag", "items": [], "content": _preview(ctx["recall_evidence"])})

    _card_override = getattr(novel, "genre_card", "") or ""
    if not cfg.get("genre_card", True):
        meta.append({"key": "genre_card", "label": "题材腔调卡", "detail": "已跳过", "source": "field", "items": [], "content": ""})
    elif _card_override == genre_cards.OFF:
        meta.append({"key": "genre_card", "label": "题材腔调卡", "detail": "本书已设为不使用", "source": "field", "items": [], "content": ""})
    else:
        _card_name = genre_cards.resolve_card_name(novel.genre, _card_override)
        meta.append({
            "key": "genre_card",
            "label": "题材腔调卡",
            "detail": (
                f"{_card_name}（{'手动指定' if _card_name == _card_override else '自动匹配'}）"
                if _card_name else f"无匹配卡（题材：{novel.genre or '未设置'}）"
            ),
            "source": "field",
            "items": [],
            "content": _preview(genre_cards.load_card(novel.genre, _card_override)),
        })

    # 9. 元信息
    ctx["novel_title"] = novel.title
    ctx["genre"] = novel.genre
    ctx["genre_card"] = _card_override
    ctx["writing_style"] = novel.writing_style
    ctx["chapter_number"] = chapter_number
    ctx["volume"] = volume
    ctx["context_config"] = cfg
    # 规则广场：由 _compose_system_prompt 追加进 system prompt。
    # 刻意不受 context_config 开关控制——多一个开关就多一条静默关掉护栏的路径
    ctx["_rules_block"] = await prompt_rules.resolve_rules_block(session, novel)
    meta.append({
        "key": "prompt_rules",
        "label": "写作规则",
        "detail": (
            f"{ctx['_rules_block'].count(chr(10) * 2) + 1} 条"
            if ctx["_rules_block"] else "未启用"
        ),
        "source": "field",
        "items": [],
        "content": _preview(ctx["_rules_block"]),
    })
    meta.insert(0, {
        "key": "dynamic_budget",
        "label": "动态上下文预算",
        "detail": f"{budget.input_budget} tokens（目标{budget.target_words}字）",
        "source": "computed",
        "items": [],
        "content": (
            f"窗口 {budget.context_window}；输出预留 {budget.output_reserve}；"
            f"滚动 {budget.allocations['rolling_summary']}；RAG {budget.allocations['rag_context']}"
        ),
    })
    ctx["_meta"] = meta

    return ctx


_RECALL_KEYWORDS = (
    "回忆", "往事", "当年", "想起", "曾经", "那时", "初见", "重逢", "旧事",
    # 重生/穿越流：主角反复回溯"前世/上一世"，同属回忆意图，必须触发取证否则每章现编
    "前世", "上辈子", "上一世", "前生", "重生", "重来", "这一世", "这辈子",
)


def _has_recall_intent(text: str) -> bool:
    return bool(text) and any(kw in text for kw in _RECALL_KEYWORDS)


def _split_paragraphs(content: str) -> list[str]:
    """把章节原文切成检索用自然段：短段（<50字）并入相邻段，长段（>600字）按句号再切。"""
    raw = [p.strip() for p in re.split(r"\n+", content) if p.strip()]
    merged: list[str] = []
    for p in raw:
        if merged and len(merged[-1]) < 50:
            merged[-1] = merged[-1] + "\n" + p
        else:
            merged.append(p)
    if len(merged) >= 2 and len(merged[-1]) < 50:
        tail = merged.pop()
        merged[-1] = merged[-1] + "\n" + tail

    result: list[str] = []
    for p in merged:
        while len(p) > 600:
            cut = p.rfind("。", 200, 600)
            if cut == -1:
                cut = 599
            result.append(p[: cut + 1])
            p = p[cut + 1:]
        if p:
            result.append(p)
    return result


def _gram_overlap_rank(query: str, texts: list[str], top_k: int) -> list[str]:
    """2-gram 重叠计数排名。BM25 的 IDF 在候选极少（1-2 条）时全为非正分而空手而归，
    这里做小语料兜底。"""
    grams = {query[i:i + 2] for i in range(len(query) - 1) if query[i:i + 2].strip()}
    if not grams:
        return []
    scored = sorted(
        ((sum(1 for g in grams if g in t), i, t) for i, t in enumerate(texts)),
        key=lambda item: (-item[0], item[1]),
    )
    return [t for score, _, t in scored[:top_k] if score > 0]


def _rank_paragraphs(query: str, paragraphs: list[str], top_k: int) -> list[str]:
    hits = bm25_rank(query, [{"text": p} for p in paragraphs], top_k=top_k)
    if hits:
        return [h["text"] for h in hits if h.get("text")]
    return _gram_overlap_rank(query, paragraphs, top_k)


async def _build_rag_fulltext(
    session: AsyncSession,
    novel_id: int,
    chapter_numbers: list[int],
    query: str,
    *,
    token_budget: int,
) -> str:
    """两跳原文取段：对检索命中的历史章节回读原文，捞与 query 最相关的段落。"""
    parts: list[str] = []
    used = 0
    for number in chapter_numbers:
        chapter = (await session.execute(
            select(Chapter).where(
                Chapter.novel_id == novel_id,
                Chapter.number == number,
            )
        )).scalars().first()
        if chapter is None or not (chapter.content or "").strip():
            continue
        paragraphs = _split_paragraphs(summarizer.strip_plot_suggestions(chapter.content))
        if not paragraphs:
            continue
        fragments = [p[:400] for p in _rank_paragraphs(query, paragraphs, top_k=2)]
        if not fragments:
            continue
        block = "\n".join(f"【第{number}章原文】{frag}" for frag in fragments)
        cost = estimate_tokens(block)
        if parts and used + cost > token_budget:
            continue
        parts.append(block)
        used += cost
    if not parts:
        return ""
    return truncate_to_token_budget("\n\n".join(parts), token_budget)


async def _build_recall_evidence(
    session: AsyncSession,
    novel_id: int,
    milestones: list[Memory],
    query: str,
    *,
    token_budget: int,
) -> str:
    """两跳取证：第一跳按里程碑相关度定位到章，第二跳回读该章原文捞最相关段落。"""
    by_id = {m.id: m for m in milestones}
    bm25_hits = bm25_rank(
        query,
        [{"text": m.content, "metadata": {"mid": m.id}} for m in milestones],
        top_k=6,
    )
    kw_hits = keyword_hits(
        query,
        [{"chapter_number": m.chapter_number, "content": m.content, "mid": m.id} for m in milestones],
        top_k=6,
    )
    fused = rrf_fuse(
        bm25_hits, kw_hits,
        key=lambda h: (h.get("metadata") or {}).get("mid", h.get("mid")),
    )
    picked: list[Memory] = []
    for hit in fused:
        mid = (hit.get("metadata") or {}).get("mid", hit.get("mid"))
        m = by_id.get(mid)
        if m is not None and m not in picked:
            picked.append(m)
        if len(picked) >= 5:  # 定位池含里程碑+摘要，同章可能重复命中，多取几条留给后面按章去重
            break
    if not picked:
        # 检索无信号时按重要度兜底：回忆意图已触发，注入真实原文段最坏也无害
        picked = sorted(
            milestones, key=lambda m: (-(m.importance or 3), m.chapter_number or 0),
        )[:3]

    parts: list[str] = []
    used = 0
    seen_chapters: set[int] = set()  # 同一章被里程碑与摘要同时命中时只回读一次
    for m in picked:
        if m.chapter_number in seen_chapters:
            continue
        chapter = (await session.execute(
            select(Chapter).where(
                Chapter.novel_id == novel_id,
                Chapter.number == m.chapter_number,
            )
        )).scalars().first()
        if chapter is None or not chapter.content:
            continue
        paragraphs = _split_paragraphs(summarizer.strip_plot_suggestions(chapter.content))
        if not paragraphs:
            continue
        fragments = [
            p[:400] for p in _rank_paragraphs(f"{m.content}\n{query}", paragraphs, top_k=2)
        ]
        if not fragments:
            continue
        origin = "\n".join(f"【第{m.chapter_number}章原文】{frag}" for frag in fragments)
        # 里程碑陈述简短且是"事实基准"，原样带上；章节摘要较长且与原文段重复，只用原文段作证
        block = (m.content + "\n" + origin) if m.memory_type == "relationship_milestone" else origin
        cost = estimate_tokens(block)
        if parts and used + cost > token_budget:
            continue
        parts.append(block)
        used += cost
        seen_chapters.add(m.chapter_number)
        if len(seen_chapters) >= 3:  # 最多回读 3 章原文，控制预算
            break
    if not parts:
        return ""
    return truncate_to_token_budget("\n\n".join(parts), token_budget)


_HISTORY_INJECT_LIMIT = 10  # 每个角色注入写作上下文的经历条数上限


async def build_progress_block(
    session: AsyncSession,
    novel: Novel,
    focus_chapter: int,
) -> str:
    """创作进度概览：已写/已确认章节数、累计字数、当前讨论的是哪一章。"""
    rows = (await session.execute(
        select(Chapter.number, Chapter.title, Chapter.status, Chapter.word_count)
        .where(Chapter.novel_id == novel.id)
        .order_by(Chapter.number)
    )).all()

    total = len(rows)
    confirmed = sum(1 for r in rows if r.status == "confirmed")
    total_words = sum(r.word_count or 0 for r in rows)
    last_num = rows[-1].number if rows else 0

    lines = ["=== 创作进度 ==="]
    lines.append(f"作品：《{novel.title}》｜类型：{novel.genre or '未设定'}｜篇幅定位：{novel.target_length or '未设定'}")
    if novel.estimated_chapters:
        lines.append(f"已写 {total} 章（其中已确认 {confirmed} 章），全书计划约 {novel.estimated_chapters} 章，累计约 {total_words} 字。")
    else:
        lines.append(f"已写 {total} 章（其中已确认 {confirmed} 章），累计约 {total_words} 字。")
    if last_num:
        lines.append(f"最新一章是第 {last_num} 章，下一章待写的是第 {last_num + 1} 章。")

    focus = next((r for r in rows if r.number == focus_chapter), None)
    if focus:
        status_label = "已确认" if focus.status == "confirmed" else "草稿"
        title_part = f"《{focus.title}》" if focus.title else ""
        lines.append(
            f"作者当前正在编辑器里看第 {focus_chapter} 章{title_part}（{status_label}，约 {focus.word_count or 0} 字）。"
            f"下面的大纲、上一章原文、检索片段都是围绕这一章组织的；作者说“这里/这章/这段”时默认指这一章。"
        )
    else:
        lines.append(
            f"作者当前定位在第 {focus_chapter} 章，这一章还没有正文（尚未生成）。"
            f"下面的资料是围绕这一章组织的；作者说“这章”时默认指这一章。"
        )
    return "\n".join(lines)


def format_context_for_writer(
    ctx: dict,
    instruction: str = "",
    target_words: int = 2500,
    for_chat: bool = False,
) -> tuple[str, str, str]:
    """
    将 context dict 格式化为 Writer Agent 的 Prompt 输入。
    通过 ctx["context_config"] 中的开关控制各区块是否包含。

    for_chat=True 供创作助手对话使用：资料内容完全相同，但改写措辞——
    去掉"生成正文时必须…"这类写作指令口吻，秘密不再走上帝视角隔离区
    （作者本人有权看全部真相），并且不返回写作任务。
    """
    cfg = ctx.get("context_config", {})
    def _on(key: str) -> bool:
        return cfg.get(key, True)

    _SHEET_LABELS = {
        "personality": "初始性格", "skills": "技能",
        "appearance": "外貌", "speech_style": "说话风格",
    }

    # ── 角色状态 ──
    pov_name = ctx.get("pov", "")
    hidden_facts: list[tuple[str, str, list]] = []  # (角色名, 秘密, 知情者) —— POV 不知情，进上帝视角隔离区
    chars_text = ""
    if _on("characters"):
        dead_names: list[str] = []
        if ctx.get("characters"):
            chars_text += "（角色\"现龄\"为出生至今的实际岁数，不是修行年限或入门年数；姐/兄/长辈等长幼称谓以实际岁数和辈分设定为准，岁数大者为长，严禁颠倒）\n"
        for c in ctx.get("characters", []):
            state = c.get("state", {})
            sheet = c.get("full_sheet", {})
            age_part = f"·现龄{c['age']}岁" if c.get('age') else ""
            alive = str(state.get("存续", "") or "")
            alive_part = f"·{alive}" if alive and alive != "存活" else ""
            if "死亡" in alive:
                dead_names.append(c['name'])
            chars_text += f"【{c['name']}·{c['role']}{age_part}{alive_part}】{c['description']}\n"
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
            history = [e for e in (sheet.get("character_history") or [])
                       if isinstance(e, dict) and e.get("content")][-_HISTORY_INJECT_LIMIT:]
            if history:
                chars_text += (
                    "  经历（近期，天数为故事内绝对日，供你把握事件间隔与时间跨度；"
                    "正文严禁出现\"第X日/第X章\"字样）：\n"
                )
                for e in history:
                    day_part = f"·第{e['day']}日" if e.get("day") else ""
                    chars_text += f"    第{e.get('chapter', '?')}章{day_part}：{e['content']}\n"
            if state:
                current_personality = state.get("personality")
                if current_personality:
                    chars_text += f"  当前性格：{current_personality}\n"
                filtered_state = {k: v for k, v in state.items()
                                  if k not in ("personality", "known_secrets", "secrets", "base_relationships", "initial_relationships", "relationship_changes", "存续")}
                if filtered_state:
                    chars_text += f"  当前状态：{json.dumps(filtered_state, ensure_ascii=False)}\n"
                legacy_known_secrets = state.get("known_secrets", []) or []
                if legacy_known_secrets:
                    chars_text += f"  该角色已知的秘密：{'；'.join(str(v) for v in legacy_known_secrets)}\n"
                # 信息不对称：按 POV 是否在知情者名单内分流
                for sec in state.get("secrets", []) or []:
                    if not isinstance(sec, dict):
                        continue
                    fact = sec.get("fact")
                    if not fact:
                        continue
                    known_by = sec.get("known_by") or []
                    if for_chat:
                        who = "、".join(known_by) if known_by else "无人知晓"
                        chars_text += f"  相关秘密：{fact}（知情者：{who}）\n"
                    elif pov_name and pov_name in known_by:
                        chars_text += f"  已知秘密：{fact}\n"
                    else:
                        hidden_facts.append((c["name"], str(fact), list(known_by)))
                base_rels = state.get("base_relationships", {})
                initial_rels = state.get("initial_relationships", {})
                ongoing_rels = state.get("relationship_changes", {})
                base_rels = base_rels if isinstance(base_rels, dict) else {}
                initial_rels = initial_rels if isinstance(initial_rels, dict) else {}
                ongoing_rels = ongoing_rels if isinstance(ongoing_rels, dict) else {}
                rel_targets = list(dict.fromkeys([*base_rels, *initial_rels, *ongoing_rels]))
                if rel_targets:
                    rel_parts = []
                    for tgt in rel_targets:
                        layers = []
                        if base_rels.get(tgt):
                            layers.append(f"基础：{base_rels[tgt]}")
                        if ongoing_rels.get(tgt):
                            layers.append(f"当前：{ongoing_rels[tgt]}")
                        elif initial_rels.get(tgt):
                            layers.append(f"初始：{initial_rels[tgt]}")
                        if layers:
                            rel_parts.append(f"{tgt}（{'；'.join(layers)}）")
                    if rel_parts:
                        chars_text += f"  人物关系（对方是{c['name']}的什么人）：{'，'.join(rel_parts)}\n"
        if dead_names:
            chars_text += f"⚠ 以下角色已死亡：{'、'.join(dead_names)}。严禁让其作为活人出场或说话，仅可在回忆、遗物、他人转述中出现。\n"
    chars_block = f"=== 角色状态 ===\n{chars_text.strip()}" if chars_text.strip() else ""

    # ── 上帝视角真相（POV 角色尚不知情，严禁表现知晓）──
    if hidden_facts:
        lines = ["=== 上帝视角真相（以下角色尚不知情）==="]
        pov_label = pov_name or "本章视角角色"
        lines.append(
            f"以下设定为剧情真相，仅供你保持设定一致与铺垫。严禁让未列入「知情者」的角色"
            f"（尤其是{pov_label}）在本章通过言行、心理或旁白表现出知晓："
        )
        for name, fact, known_by in hidden_facts:
            who = "、".join(known_by) if known_by else "无"
            lines.append(f"- 【{name}】{fact}（知情者：{who}）")
        godview_block = "\n".join(lines)
        chars_block = f"{chars_block}\n\n{godview_block}" if chars_block else godview_block

    # ── 本章大纲（追加在角色之后，贴近消息末尾的高注意力位置）──
    if _on("chapter_outline") and ctx.get("chapter_outline"):
        outline_title = "当前讨论章节的大纲（计划，未必已写）" if for_chat else "本章大纲"
        outline_block = f"=== {outline_title} ===\n{ctx['chapter_outline']}"
        chars_block = f"{chars_block}\n\n{outline_block}" if chars_block else outline_block

    # 实体/地点/势力/功法/补充设定后置到 context_block 末尾（重要性低于角色，避免把角色挤进中段低谷）
    world_parts: list[str] = []

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
        if e.get("function"):
            entities_text += f"  功能：{e['function']}\n"
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
        if for_chat:
            entities_block = (
                "=== 世界实体 ===\n"
                "（实体卡是背景资料，不代表书中角色知晓其存在。系统/金手指/隐秘至宝类实体，"
                "默认仅持有者本人知道）\n"
                f"{entities_text.strip()}"
            )
        else:
            entities_block = (
                "=== 世界实体 ===\n"
                "（实体卡是给作者的背景资料，不代表书中角色知晓其存在。系统/金手指/隐秘至宝类实体，"
                "默认仅持有者本人知道：其他角色不得在对白或心理中提及、不得表现出知情，除非资料明确列出知情人）\n"
                f"{entities_text.strip()}"
            )
        world_parts.append(entities_block)

    # ── 地点 ──
    if _on("locations"):
        loc_lines = []
        for l in ctx.get("locations", []):
            line = f"【{l['name']}·{l['type']}】{l['description']}"
            l_state = {k: v for k, v in (l.get("state") or {}).items() if v}
            if l_state:
                line += f"\n  当前状态：{json.dumps(l_state, ensure_ascii=False)}"
            loc_lines.append(line)
        if loc_lines:
            loc_block = f"=== 地点 ===\n" + "\n".join(loc_lines)
            world_parts.append(loc_block)

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
            world_parts.append(fac_block)

    # ── 功法/武技 ──
    if _on("techniques"):
        tech_lines = []
        for t in ctx.get("techniques", []):
            line = f"【{t['name']}·{t['type']}】{t['description']}"
            if t.get("practitioners"):
                line += f"（修习者：{t['practitioners']}）"
            tech_lines.append(line)
        if tech_lines:
            tech_note = (
                "（已列明修习者的功法/法术仅限修习者本人使用）\n"
                if for_chat else
                "（已列明修习者的功法/法术仅限修习者本人使用；其他角色不得凭空掌握、施展或知晓其细节，"
                "除非资料明确说明已传授/公开）\n"
            )
            tech_block = "=== 功法 ===\n" + tech_note + "\n".join(tech_lines)
            world_parts.append(tech_block)

    # ── 补充设定笔记 ──
    if _on("notes_context"):
        notes_lines = []
        for n in ctx.get("notes", []):
            notes_lines.append(f"【{n['title']}】{n['content']}")
        if notes_lines:
            notes_block = f"=== 补充设定 ===\n" + "\n".join(notes_lines)
            world_parts.append(notes_block)

    # ── context_block（世界观、摘要、RAG、前文、实体背景）──
    parts = []
    if for_chat:
        parts.append(
            "=== 参考资料使用规则 ===\n"
            "以下是这部小说的完整创作资料，供你回答作者的问题、给出建议时参照。\n"
            "事实优先级：已确认世界观变更/核心规则 > 当前角色与实体状态 > 活跃伏笔与秘密 > 上章正文 > 有来源的历史证据 > 摘要与大纲。\n"
            "大纲表示尚未落笔的计划，不代表事件已经发生——回答时要区分「已经写了的」和「计划要写的」。\n"
            "资料没写的内容就是还没定，不要当成既定事实转述；作者问到时可以直说资料里没有，并给出建议方向。\n"
            "摘要中的【第X日】是故事内绝对天数，用于推算事件间隔与时间跨度。"
        )
    else:
        parts.append(
            "=== 参考资料使用规则 ===\n"
            "事实优先级：已确认世界观变更/核心规则 > 当前角色与实体状态 > 活跃伏笔与秘密 > 上章正文 > 有来源的历史证据 > 摘要与大纲。\n"
            "大纲和写作方向表示本章计划，不代表事件已经发生。资料未说明时，不得自行补写姓名、来历、关系、能力、物品来源或角色知情情况；同级资料冲突时回避断言。\n"
            "以下摘要中的绝对日期计数（如【第X日】、第X日、当日、次日等）只用于内部时间线排序，不属于正文文风。\n"
            "生成正文时不得把这些时间标注显式写进叙事段落；除非用户指令明确要求日期标注，否则用自然的时间过渡承接剧情。"
        )
    if _on("core_setting") and ctx.get("core_rules"):
        if for_chat:
            parts.append(
                "=== 世界观核心规则 ===\n"
                "以下是本作世界观的核心规则与特殊元素，是不可违背的设定基石。"
                "给建议时不得与之矛盾；若作者的想法与这些规则冲突，请直接指出冲突点。\n"
                "注意：特殊元素中的法术/秘技/体质若未写明普及范围，默认仅资料中已确立的使用者掌握：\n"
                f"{ctx['core_rules']}"
            )
        else:
            parts.append(
                "=== 世界观核心规则（必须严格遵守）===\n"
                "以下是本作世界观的核心规则与特殊元素，是不可违背的设定基石。"
                "生成正文时必须严格遵守，任何情节、人物能力、设定都不得与之矛盾。\n"
                "注意：特殊元素中的法术/秘技/体质若未写明普及范围，默认仅资料中已确立的使用者掌握，"
                "不得让其他角色凭空会用或知晓其存在：\n"
                f"{ctx['core_rules']}"
            )
    if _on("glossary") and ctx.get("glossary"):
        if for_chat:
            glossary_lines = [
                "=== 用词规范 ===",
                "以下为作品用词规范，你在示例文字、改写建议中提到这些概念时必须遵循：",
                "- 描写相关概念/对象时，使用「规范用词」，不要使用「禁用」中列出的词汇",
                "- 专有名词（人名、地名、功法等）汉字必须与下表完全一致",
                "",
            ]
        else:
            glossary_lines = [
                "=== 用词规范（必须严格遵守）===",
                "以下为作品用词规范，生成正文时必须严格遵循：",
                "- 描写相关概念/对象时，必须使用「规范用词」，严禁使用「禁止写法」中列出的词汇",
                "- 专有名词（人名、地名、功法等）汉字必须与下表完全一致，不得自行创造同音字、形近字替代",
                "",
            ]
        for g in ctx["glossary"]:
            line = f"· 用「{g['term']}」"
            if g.get("forbidden_variants"):
                line += f" —— 禁用：「{g['forbidden_variants']}」"
            if g.get("notes"):
                line += f"（{g['notes']}）"
            glossary_lines.append(line)
        parts.append("\n".join(glossary_lines))
    if _on("genre_card"):
        card = genre_cards.load_card(ctx.get("genre", ""), ctx.get("genre_card", ""))
        if card:
            parts.append(card)
    if _on("core_setting") and ctx.get("core_setting"):
        parts.append(f"=== 世界观设定（背景参考）===\n{ctx['core_setting']}")
    if _on("core_setting") and ctx.get("worldview_changes"):
        wv_lines = [
            "=== 世界观变更（截至本章，覆盖上文设定）===",
            "以下为剧情推进中世界观的更新，与上文「世界观设定」冲突时，一律以这里为准：",
        ]
        for ch in ctx["worldview_changes"]:
            prefix = f"（第{ch['effective_chapter']}章起）" if ch.get("effective_chapter") else ""
            wv_lines.append(f"- {prefix}{ch['fact']}")
        parts.append("\n".join(wv_lines))
    if _on("story_threads") and ctx.get("story_threads"):
        thread_lines = [
            "=== 伏笔与秘密（高优先级长期事实）===",
            "这是全书悬念的账本：哪些还悬着、哪些已经收了、谁知道什么。"
            "给情节建议时要照顾这些线，别建议提前回收活跃伏笔，也别把已回收的当成还没解开。"
            if for_chat else
            "活跃伏笔不得擅自遗忘或提前回收；已回收伏笔不得再次写成未解悬念；秘密必须严格遵守知情者边界。",
        ]
        for thread in ctx["story_threads"]:
            source = f"第{thread['source_chapter']}章" if thread.get("source_chapter") else "人工设定"
            title = f"【{thread['title']}】" if thread.get("title") else ""
            entities = "、".join(thread.get("related_entities") or [])
            entity_note = f"；涉及：{entities}" if entities else ""
            if thread.get("status") == "resolved":
                # 近期已回收：压成一行提醒，只保留标题和结果，不再重复原始内容
                resolved_at = f"第{thread['resolved_chapter']}章" if thread.get("resolved_chapter") else "此前"
                resolution = thread.get("resolution") or ("已揭晓" if thread["kind"] == "secret" else "已完成回收")
                kind_label = "秘密·已揭晓" if thread["kind"] == "secret" else "伏笔·已回收"
                thread_lines.append(
                    f"- [{kind_label}]{title or thread['content'][:20]}"
                    f"（{resolved_at}回收：{resolution}；不得重新当作未解悬念）"
                )
                continue
            if thread["kind"] == "secret":
                known = "、".join(thread.get("known_by") or []) or "无人明确知晓"
                thread_lines.append(
                    f"- [秘密·未揭晓·重要度{thread['importance']}·来源{source}]{title}{thread['content']}"
                    f"（知情者：{known}{entity_note}）"
                )
            else:
                due = f"；预计第{thread['due_chapter']}章前后回收" if thread.get("due_chapter") else ""
                thread_lines.append(
                    f"- [伏笔·重要度{thread['importance']}·来源{source}]{title}{thread['content']}"
                    f"（保持活跃{due}{entity_note}）"
                )
        parts.append("\n".join(thread_lines))
    if _on("relationship_milestones") and ctx.get("relationship_milestones"):
        if for_chat:
            parts.append(
                "=== 关系里程碑（已确立事实）===\n"
                "以下是角色之间情感/关系转折的既定事实（格式：[类型] 角色 | 发生章节 | 经过）。"
                "谈到感情线时以此为准，不要编造未记录的初见/动心/表白等情节：\n"
                + "\n".join(f"- {line}" for line in ctx["relationship_milestones"])
            )
        else:
            parts.append(
                "=== 关系里程碑（已确立事实，回忆时以此为准）===\n"
                "以下是角色之间情感/关系转折的既定事实（格式：[类型] 角色 | 发生章节 | 经过）。"
                "写到回忆、追溯感情线时必须以此为准，严禁编造未记录的初见/动心/表白等情节：\n"
                + "\n".join(f"- {line}" for line in ctx["relationship_milestones"])
            )
    # 摘要保留【第X日】标记，让模型能推算事件间隔与时长；防泄漏靠写作规则 + critic 检查
    story_day = _latest_story_day(
        ctx.get("book_summary", ""),
        ctx.get("arc_summary", ""),
        ctx.get("rolling_summary", ""),
    )
    if story_day is not None:
        if for_chat:
            parts.append(
                f"=== 当前故事时间 ===\n"
                f"已写到的最后一章结束时为故事内第 {story_day} 日。参考资料中的“第X日”是故事内绝对天数，"
                f"供你推算事件间隔与时间跨度（如“潜伏了多久”“过了几年”）。"
            )
        else:
            parts.append(
                f"=== 当前故事时间 ===\n"
                f"上一章结束时为故事内第 {story_day} 日。以下参考资料中的“第X日”是故事内绝对天数，"
                f"供你推算事件间隔与时间跨度（如“潜伏了多久”“过了几年”），"
                f"严禁在正文中出现“第X日/第X章”字样，需用自然的时间过渡描写代替。"
            )
    if _on("book_summary") and ctx.get("book_summary"):
        parts.append(f"=== 全书概要 ===\n{ctx['book_summary'].strip()}")
    if _on("arc_summary") and ctx.get("arc_summary"):
        parts.append(f"=== 近期故事弧概要 ===\n{ctx['arc_summary'].strip()}")
    if _on("rolling_summary") and ctx.get("rolling_summary"):
        parts.append(f"=== 近期剧情摘要 ===\n{ctx['rolling_summary'].strip()}")
    if _on("rag_context") and ctx.get("rag_context"):
        parts.append(f"=== 相关历史场景（参考）===\n{ctx['rag_context'].strip()}")
    if _on("rag_fulltext") and ctx.get("rag_fulltext"):
        parts.append(
            "=== 历史章节原文片段（真实原文）===\n"
            + ("以下是与当前话题相关的历史章节真实原文片段，引用前文细节（对话、称谓、场景）时以此为准：\n"
               if for_chat else
               "以下是与本章内容相关的历史章节真实原文片段，呼应前文时的细节（对话、称谓、场景）应与此一致：\n")
            + f"{ctx['rag_fulltext']}"
        )
    if _on("recall_evidence") and ctx.get("recall_evidence"):
        parts.append(
            "=== 回忆取证（历史章节原文片段）===\n"
            + ("以下是与当前话题相关的历史章节真实原文，谈到往事细节时取材于此，不要另行虚构：\n"
               if for_chat else
               "以下是与本章回忆相关的历史章节真实原文，回忆往事的细节（对话、场景、动作）应取材于此，不得另行虚构：\n")
            + f"{ctx['recall_evidence']}"
        )

    if ctx.get("full_text_context"):
        parts.append(f"=== 前文正文（全文）===\n{ctx['full_text_context']}")

    parts.extend(world_parts)

    context_block = "\n\n".join(parts)

    chapter_number = ctx.get("chapter_number", 1)
    volume = ctx.get("volume", 1)

    # 对话助手不承担写章节任务，第三个返回值留空
    if for_chat:
        return context_block, chars_block, ""

    continuity_hint = ""
    if _on("recent_text") and chapter_number > 1 and ctx.get("recent_text"):
        continuity_hint = (
            "\n除非写作方向另有安排（如时间跳跃、场景切换），请自然承接上一章结尾的场景和情绪，"
            "保持人物位置、对话语境、情节节奏的连贯性，不要重复已写过的内容。"
        )

    # 结构性任务描述（不含用户写作指令——由 writer.py 根据 api_format 决定指令放置位置）
    task_instruction = (
        f"=== 写作任务 ===\n"
        f"请写第{volume}卷"
        f"第{chapter_number}章，"
        f"类型：{ctx.get('genre', '')}，"
        f"风格：{ctx.get('writing_style', '')}，"
        f"目标字数 {target_words} 字（不得低于 {int(target_words * 0.9)} 字，不得超过 {int(target_words * 1.15)} 字）。"
        f"{continuity_hint}\n"
        f"正文中不要显式写出参考摘要里的第X日、当日、次日等时间线标注；需要表达时间推进时，用自然叙事过渡。\n"
        f"直接输出正文内容，不要输出章节标题或任何前缀。"
    )
    if hidden_facts:
        task_instruction += (
            "\n严格遵守「上帝视角真相」区块：未列入知情者的角色，本章不得通过言行、心理或旁白"
            "流露出对这些真相的知晓，可用于制造伏笔与戏剧反差。"
        )

    return context_block, chars_block, task_instruction
