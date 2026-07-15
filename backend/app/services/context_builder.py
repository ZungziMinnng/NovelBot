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
from app.services import llm_client, vector_store, summarizer
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
from app.services.thread_selector import cap_glossary, select_story_threads


logger = logging.getLogger(__name__)

_SUMMARY_TIME_TAG_RE = re.compile(r"【\s*第\d+日(?:[^】]*)?】")
_SUMMARY_INLINE_DAY_RE = re.compile(
    r"(^|[：:\n]\s*)第\d+日(?:[·\s]*(?:清晨|上午|白天|午后|傍晚|晚上|深夜))?[，,、\s]*"
)


def _writer_reference_text(text: str) -> str:
    """Remove timeline metadata tags before passing summaries to Writer."""
    if not text:
        return ""
    text = _SUMMARY_TIME_TAG_RE.sub("", text)
    text = _SUMMARY_INLINE_DAY_RE.sub(r"\1", text)
    return text.strip()


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
    target_words: int = 5000,
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
        query = "\n".join(filter(None, [
            scene_hint.strip(),
            ctx["chapter_outline"].strip(),
            rolling_text[-1500:].strip(),
        ])) or f"第{chapter_number}章"
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
        rag_hits = await vector_store.asearch_similar_with_meta(
            novel.id, query, top_k=rag_top_k * OVERFETCH,
            where={"$and": rag_chapter_filter},
        )
        ranked_hits = diversify_historical_hits(
            rerank_by_importance(rag_hits, rag_top_k * OVERFETCH, current_chapter=chapter_number),
            rag_top_k,
        )
        retrieved = []
        retrieved_tokens = 0
        used_chapters: set = set()
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
            fallback_items = [
                f"【第{m.chapter_number}章·高重要性历史证据】{m.content}"
                for m in fallback_memories if (m.content or "").strip()
            ]
            retrieved = []
            retrieved_tokens = 0
            for item in fallback_items:
                item_tokens = estimate_tokens(item)
                if retrieved and retrieved_tokens + item_tokens > rag_budget and len(retrieved) >= minimum_rag:
                    break
                retrieved.append(item)
                retrieved_tokens += item_tokens

        # 5b. 关键词精确匹配兜底：向量检索会把「月华顿悟」这类独特短语稀释在
        # 整段查询里，这里用查询文本的中文 4-gram 与全部老章节摘要做精确交集，
        # 把向量没捞回来的相关老章节补进上下文（有独立的小额预算，不挤占向量结果）。
        kw_stmt = select(Memory).where(
            Memory.novel_id == novel.id,
            Memory.memory_type == "chapter_summary",
            Memory.chapter_number < chapter_number,
        )
        if excluded_chapters:
            kw_stmt = kw_stmt.where(~Memory.chapter_number.in_(sorted(excluded_chapters)))
        kw_memories = (await session.execute(kw_stmt.order_by(Memory.id))).scalars().all()
        kw_candidates = list({
            m.chapter_number: {"chapter_number": m.chapter_number, "content": m.content}
            for m in kw_memories
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
        ctx["rag_context"] = "\n\n".join(retrieved)
    else:
        retrieved = []
        kw_count = 0
        ctx["rag_context"] = ""
    if not _on("rag_context"):
        meta.append({"key": "rag_context", "label": "RAG历史检索", "detail": "已跳过", "source": "rag", "items": [], "content": ""})
    elif ctx["rag_context"]:
        rag_detail = f"{len(retrieved)}条检索" + (f"（含{kw_count}条关键词命中）" if kw_count else "")
        meta.append({"key": "rag_context", "label": "RAG历史检索", "detail": rag_detail, "source": "rag", "items": [], "content": _preview(ctx["rag_context"])})
    else:
        meta.append({"key": "rag_context", "label": "RAG历史检索", "detail": "空", "source": "rag", "items": [], "content": ""})

    # 6. 即时上下文：上一章全文（复用上面已加载的 prev_chapter）
    if prev_chapter:
        prev_summary = prev_chapter.summary or ""
        recent_budget = budget.allocations["recent_text"]
        raw_recent = prev_content.strip() or prev_summary.strip()
        if estimate_tokens(raw_recent) <= recent_budget:
            ctx["recent_text"] = raw_recent
        else:
            summary_block = f"【上一章摘要】{prev_summary.strip()}\n\n" if prev_summary.strip() else ""
            remaining = max(1, recent_budget - estimate_tokens(summary_block))
            tail = truncate_to_token_budget(prev_content.strip(), remaining, keep_end=True)
            ctx["recent_text"] = f"{summary_block}【上一章结尾】{tail}".strip()
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
            StoryThread.status != "abandoned",
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
    )
    if ctx["story_threads"]:
        thread_detail = (
            f"{len(ctx['story_threads'])}条有效记录"
            if len(ctx["story_threads"]) == len(story_threads)
            else f"{len(ctx['story_threads'])}/{len(story_threads)}条（预算筛选）"
        )
        meta.append({
            "key": "story_threads",
            "label": "伏笔/秘密",
            "detail": thread_detail,
            "source": "field",
            "items": [t["title"] or t["content"][:20] for t in ctx["story_threads"]],
            "content": _preview("；".join(t["content"] for t in ctx["story_threads"])),
        })

    # 9. 元信息
    ctx["novel_title"] = novel.title
    ctx["genre"] = novel.genre
    ctx["writing_style"] = novel.writing_style
    ctx["chapter_number"] = chapter_number
    ctx["volume"] = volume
    ctx["context_config"] = cfg
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


def format_context_for_writer(ctx: dict, instruction: str = "", target_words: int = 5000) -> tuple[str, str, str]:
    """
    将 context dict 格式化为 Writer Agent 的 Prompt 输入。
    通过 ctx["context_config"] 中的开关控制各区块是否包含。
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
                current_personality = state.get("personality")
                if current_personality:
                    chars_text += f"  当前性格：{current_personality}\n"
                filtered_state = {k: v for k, v in state.items()
                                  if k not in ("personality", "known_secrets", "secrets", "initial_relationships", "relationship_changes")}
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
                    if pov_name and pov_name in known_by:
                        chars_text += f"  已知秘密：{fact}\n"
                    else:
                        hidden_facts.append((c["name"], str(fact), list(known_by)))
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
    parts.append(
        "=== 参考资料使用规则 ===\n"
        "事实优先级：已确认世界观变更/核心规则 > 当前角色与实体状态 > 活跃伏笔与秘密 > 上章正文 > 有来源的历史证据 > 摘要与大纲。\n"
        "大纲和写作方向表示本章计划，不代表事件已经发生。资料未说明时，不得自行补写姓名、来历、关系、能力、物品来源或角色知情情况；同级资料冲突时回避断言。\n"
        "以下摘要中的绝对日期计数（如【第X日】、第X日、当日、次日等）只用于内部时间线排序，不属于正文文风。\n"
        "生成正文时不得把这些时间标注显式写进叙事段落；除非用户指令明确要求日期标注，否则用自然的时间过渡承接剧情。"
    )
    if _on("core_setting") and ctx.get("core_rules"):
        parts.append(
            "=== 世界观核心规则（必须严格遵守）===\n"
            "以下是本作世界观的核心规则与特殊元素，是不可违背的设定基石。"
            "生成正文时必须严格遵守，任何情节、人物能力、设定都不得与之矛盾：\n"
            f"{ctx['core_rules']}"
        )
    if _on("glossary") and ctx.get("glossary"):
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
    if _on("book_summary") and ctx.get("book_summary"):
        parts.append(f"=== 全书概要 ===\n{_writer_reference_text(ctx['book_summary'])}")
    if _on("arc_summary") and ctx.get("arc_summary"):
        parts.append(f"=== 近期故事弧概要 ===\n{_writer_reference_text(ctx['arc_summary'])}")
    if _on("chapter_outline") and ctx.get("chapter_outline"):
        parts.append(f"=== 本章大纲 ===\n{ctx['chapter_outline']}")
    if _on("rolling_summary") and ctx.get("rolling_summary"):
        parts.append(f"=== 近期剧情摘要 ===\n{_writer_reference_text(ctx['rolling_summary'])}")
    if _on("rag_context") and ctx.get("rag_context"):
        parts.append(f"=== 相关历史场景（参考）===\n{_writer_reference_text(ctx['rag_context'])}")

    if ctx.get("full_text_context"):
        parts.append(f"=== 前文正文（全文）===\n{ctx['full_text_context']}")

    context_block = "\n\n".join(parts)

    chapter_number = ctx.get("chapter_number", 1)
    volume = ctx.get("volume", 1)
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
