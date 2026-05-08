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

log = logging.getLogger(__name__)

# ── 嵌入文本构建 ──────────────────────────────────────────────────────────

def _char_text(c: Character) -> str:
    return f"{c.name} ({c.role})\n{c.description}"


def _entity_text(e: WorldEntity) -> str:
    type_label = "道具" if e.type == "item" else "系统"
    return f"{e.name} ({type_label})\n{e.description or ''}"


def _entity_type_key(e: WorldEntity) -> str:
    return f"entity_{e.type}"


def _location_text(loc: Location, parent_name: str = "") -> str:
    parts = [f"{loc.name} ({loc.type})"]
    if parent_name:
        parts[0] += f" [{parent_name}]"
    if loc.description:
        parts.append(loc.description)
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


# ── 单条嵌入 / 删除 ──────────────────────────────────────────────────────

async def embed_character(novel_id: int, char: Character) -> None:
    doc_id = f"character_{char.id}"
    text = _char_text(char)
    meta = {"type": "character", "entity_id": char.id, "name": char.name}
    await vector_store.astore_text(novel_id, doc_id, text, meta)


async def embed_world_entity(novel_id: int, entity: WorldEntity) -> None:
    type_key = _entity_type_key(entity)
    doc_id = f"{type_key}_{entity.id}"
    text = _entity_text(entity)
    meta = {"type": type_key, "entity_id": entity.id, "name": entity.name}
    await vector_store.astore_text(novel_id, doc_id, text, meta)


async def embed_location(novel_id: int, loc: Location, parent_name: str = "") -> None:
    doc_id = f"location_{loc.id}"
    text = _location_text(loc, parent_name)
    meta = {"type": "location", "entity_id": loc.id, "name": loc.name}
    await vector_store.astore_text(novel_id, doc_id, text, meta)


async def embed_faction(novel_id: int, fac: Faction) -> None:
    doc_id = f"faction_{fac.id}"
    text = _faction_text(fac)
    meta = {"type": "faction", "entity_id": fac.id, "name": fac.name}
    await vector_store.astore_text(novel_id, doc_id, text, meta)


async def embed_technique(novel_id: int, tech: Technique) -> None:
    doc_id = f"technique_{tech.id}"
    text = _technique_text(tech)
    meta = {"type": "technique", "entity_id": tech.id, "name": tech.name}
    await vector_store.astore_text(novel_id, doc_id, text, meta)


async def remove_entity_embedding(novel_id: int, type_key: str, db_id: int) -> None:
    doc_id = f"{type_key}_{db_id}"
    await vector_store.adelete_docs(novel_id, [doc_id])


# ── 批量重建 ─────────────────────────────────────────────────────────────

async def reindex_all_entities(session: AsyncSession, novel_id: int) -> dict:
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
        batch.append((doc_id, _entity_text(e), {"type": type_key, "entity_id": e.id, "name": e.name}))
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
        batch.append((doc_id, _location_text(loc, parent_name), {"type": "location", "entity_id": loc.id, "name": loc.name}))
    counts["location"] = len(locations)

    factions = (await session.execute(
        select(Faction).where(Faction.novel_id == novel_id)
    )).scalars().all()
    for f in factions:
        doc_id = f"faction_{f.id}"
        batch.append((doc_id, _faction_text(f), {"type": "faction", "entity_id": f.id, "name": f.name}))
    counts["faction"] = len(factions)

    techniques = (await session.execute(
        select(Technique).where(Technique.novel_id == novel_id)
    )).scalars().all()
    for t in techniques:
        doc_id = f"technique_{t.id}"
        batch.append((doc_id, _technique_text(t), {"type": "technique", "entity_id": t.id, "name": t.name}))
    counts["technique"] = len(techniques)

    if batch:
        await vector_store.astore_texts_batch(novel_id, batch)

    log.info("reindex_all_entities novel=%d counts=%s", novel_id, counts)
    return counts
