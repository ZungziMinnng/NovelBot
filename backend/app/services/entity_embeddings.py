"""
实体向量嵌入管理：角色、道具、系统、地点、势力、功法。
在 CRUD 路由中 hook，确保向量库与 SQL 同步。
"""
import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services import vector_store
from app.models.character import Character
from app.models.world_entity import WorldEntity
from app.models.location import Location
from app.models.faction import Faction
from app.models.technique import Technique
from app.models.world_rule import WorldRule

log = logging.getLogger(__name__)

# ── 嵌入文本构建 ──────────────────────────────────────────────────────────

def _state_snippet(state, limit: int = 300) -> str:
    """将 current_state 压成一行加入嵌入文本，让检索能命中角色/实体的最新状态。"""
    if not isinstance(state, dict) or not state:
        return ""
    parts = []
    for key, val in state.items():
        if isinstance(val, list):
            val_str = "、".join(str(v) for v in val if v)
        elif isinstance(val, dict):
            val_str = "; ".join(f"{k}:{v}" for k, v in val.items() if v)
        else:
            val_str = str(val) if val else ""
        if val_str:
            parts.append(f"{key}={val_str}")
    if not parts:
        return ""
    text = "当前状态: " + "; ".join(parts)
    return text[:limit]


def _char_text(c: Character) -> str:
    parts = [f"{c.name} ({c.role})"]
    if c.description:
        parts.append(c.description)
    sheet = c.full_sheet if isinstance(c.full_sheet, dict) else {}
    appearance = sheet.get("appearance")
    if appearance:
        parts.append(f"外貌: {appearance}")
    state = _state_snippet(c.current_state)
    if state:
        parts.append(state)
    return "\n".join(parts)


def _entity_text(e: WorldEntity) -> str:
    type_label = "道具" if e.type == "item" else "系统"
    parts = [f"{e.name} ({type_label})", e.description or ""]
    if e.function:
        parts.append(f"功能: {e.function}")
    state = _state_snippet(e.current_state)
    if state:
        parts.append(state)
    return "\n".join(p for p in parts if p)


def _entity_type_key(e: WorldEntity) -> str:
    return f"entity_{e.type}"


def _location_text(loc: Location, parent_name: str = "") -> str:
    parts = [f"{loc.name} ({loc.type})"]
    if parent_name:
        parts[0] += f" [{parent_name}]"
    if loc.description:
        parts.append(loc.description)
    state = _state_snippet(loc.current_state)
    if state:
        parts.append(state)
    return "\n".join(parts)


def _faction_text(f: Faction) -> str:
    parts = [f"{f.name} ({f.type})"]
    if f.description:
        parts.append(f.description)
    if f.goals:
        parts.append(f"目标: {f.goals}")
    return "\n".join(parts)


def _technique_text(t: Technique) -> str:
    return f"{t.name} ({t.type})\n{t.description or ''}"


def _world_element_text(r: WorldRule) -> str:
    title = (r.title or "").strip()
    return f"{title} (特殊元素)\n{r.content or ''}" if title else (r.content or "")


# ── 单条嵌入 / 删除 ──────────────────────────────────────────────────────

async def _safe_embed(novel_id: int, doc_id: str, text: str, meta: dict) -> None:
    """实体向量写入是 CRUD 的附带同步，失败不应影响已提交的数据库写入。"""
    try:
        await vector_store.astore_text(novel_id, doc_id, text, meta)
    except Exception:
        log.warning(
            "实体向量写入失败（已忽略，不影响数据保存）: novel=%s doc=%s",
            novel_id, doc_id, exc_info=True,
        )


async def embed_character(novel_id: int, char: Character) -> None:
    doc_id = f"character_{char.id}"
    text = _char_text(char)
    meta = {"type": "character", "entity_id": char.id, "name": char.name}
    await _safe_embed(novel_id, doc_id, text, meta)


async def embed_world_entity(novel_id: int, entity: WorldEntity) -> None:
    type_key = _entity_type_key(entity)
    doc_id = f"{type_key}_{entity.id}"
    text = _entity_text(entity)
    meta = {"type": type_key, "entity_id": entity.id, "name": entity.name, "importance": entity.importance}
    await _safe_embed(novel_id, doc_id, text, meta)


async def embed_location(novel_id: int, loc: Location, parent_name: str = "") -> None:
    doc_id = f"location_{loc.id}"
    text = _location_text(loc, parent_name)
    meta = {"type": "location", "entity_id": loc.id, "name": loc.name, "importance": loc.importance}
    await _safe_embed(novel_id, doc_id, text, meta)


async def embed_faction(novel_id: int, fac: Faction) -> None:
    doc_id = f"faction_{fac.id}"
    text = _faction_text(fac)
    meta = {"type": "faction", "entity_id": fac.id, "name": fac.name, "importance": fac.importance}
    await _safe_embed(novel_id, doc_id, text, meta)


async def embed_technique(novel_id: int, tech: Technique) -> None:
    doc_id = f"technique_{tech.id}"
    text = _technique_text(tech)
    meta = {"type": "technique", "entity_id": tech.id, "name": tech.name, "importance": tech.importance}
    await _safe_embed(novel_id, doc_id, text, meta)


async def embed_world_element(novel_id: int, rule: WorldRule) -> None:
    doc_id = f"world_element_{rule.id}"
    text = _world_element_text(rule)
    meta = {"type": "world_element", "entity_id": rule.id, "name": (rule.title or "").strip(), "importance": rule.importance}
    await _safe_embed(novel_id, doc_id, text, meta)


async def remove_entity_embedding(novel_id: int, type_key: str, db_id: int) -> None:
    doc_id = f"{type_key}_{db_id}"
    await vector_store.adelete_docs(novel_id, [doc_id])


async def reembed_updated(
    session: AsyncSession,
    novel_id: int,
    *,
    char_ids: list[int] | None = None,
    entity_ids: list[int] | None = None,
    location_ids: list[int] | None = None,
) -> None:
    """状态更新落库后按 id 重查并重嵌，让检索能命中最新状态。失败仅告警。"""
    try:
        if char_ids:
            chars = (await session.execute(
                select(Character).where(Character.id.in_(char_ids))
            )).scalars().all()
            for c in chars:
                await embed_character(novel_id, c)
        if entity_ids:
            ents = (await session.execute(
                select(WorldEntity).where(WorldEntity.id.in_(entity_ids))
            )).scalars().all()
            for e in ents:
                await embed_world_entity(novel_id, e)
        if location_ids:
            locs = (await session.execute(
                select(Location).where(Location.id.in_(location_ids))
            )).scalars().all()
            parent_ids = [l.parent_id for l in locs if l.parent_id]
            parent_map: dict[int, str] = {}
            if parent_ids:
                parents = (await session.execute(
                    select(Location).where(Location.id.in_(parent_ids))
                )).scalars().all()
                parent_map = {p.id: p.name for p in parents}
            for l in locs:
                await embed_location(novel_id, l, parent_map.get(l.parent_id, ""))
    except Exception:
        log.warning("状态更新后重嵌向量失败（已忽略）: novel=%s", novel_id, exc_info=True)


# ── 批量重建 ─────────────────────────────────────────────────────────────

async def reindex_all_entities(session: AsyncSession, novel_id: int) -> dict:
    await vector_store.ensure_embedding_configured(novel_id, session)

    counts: dict[str, int] = {}
    batch: list[tuple[str, str, dict]] = []

    chars = (await session.execute(
        select(Character).where(Character.novel_id == novel_id)
    )).scalars().all()
    for c in chars:
        doc_id = f"character_{c.id}"
        batch.append((doc_id, _char_text(c), {"type": "character", "entity_id": c.id, "name": c.name}))
    counts["character"] = len(chars)

    entities = (await session.execute(
        select(WorldEntity).where(WorldEntity.novel_id == novel_id)
    )).scalars().all()
    for e in entities:
        type_key = _entity_type_key(e)
        doc_id = f"{type_key}_{e.id}"
        batch.append((doc_id, _entity_text(e), {"type": type_key, "entity_id": e.id, "name": e.name, "importance": e.importance}))
    counts["entity_item"] = sum(1 for e in entities if e.type == "item")
    counts["entity_system"] = sum(1 for e in entities if e.type == "system")

    # 地点需要 parent_name
    locations = (await session.execute(
        select(Location).where(Location.novel_id == novel_id)
    )).scalars().all()
    loc_map = {loc.id: loc for loc in locations}
    for loc in locations:
        parent_name = loc_map[loc.parent_id].name if loc.parent_id and loc.parent_id in loc_map else ""
        doc_id = f"location_{loc.id}"
        batch.append((doc_id, _location_text(loc, parent_name), {"type": "location", "entity_id": loc.id, "name": loc.name, "importance": loc.importance}))
    counts["location"] = len(locations)

    factions = (await session.execute(
        select(Faction).where(Faction.novel_id == novel_id)
    )).scalars().all()
    for f in factions:
        doc_id = f"faction_{f.id}"
        batch.append((doc_id, _faction_text(f), {"type": "faction", "entity_id": f.id, "name": f.name, "importance": f.importance}))
    counts["faction"] = len(factions)

    techniques = (await session.execute(
        select(Technique).where(Technique.novel_id == novel_id)
    )).scalars().all()
    for t in techniques:
        doc_id = f"technique_{t.id}"
        batch.append((doc_id, _technique_text(t), {"type": "technique", "entity_id": t.id, "name": t.name, "importance": t.importance}))
    counts["technique"] = len(techniques)

    elements = (await session.execute(
        select(WorldRule).where(WorldRule.novel_id == novel_id, WorldRule.kind == "element")
    )).scalars().all()
    for r in elements:
        doc_id = f"world_element_{r.id}"
        batch.append((doc_id, _world_element_text(r), {"type": "world_element", "entity_id": r.id, "name": (r.title or "").strip(), "importance": r.importance}))
    counts["world_element"] = len(elements)

    if batch:
        await vector_store.astore_texts_batch(novel_id, batch)

    log.info("reindex_all_entities novel=%d counts=%s", novel_id, counts)
    return counts
