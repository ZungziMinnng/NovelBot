from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import lore_agent
from app.api.deps import CurrentUser, get_owned_novel
from app.database import get_db
from app.models.lore import LoreEntry
from app.models.novel import Novel
from app.models.rpg import RpgItem, RpgModule, RpgRule, RpgSkill
from app.models.tavern import TavernCard, TavernRule, TavernWorldEntry
from app.models.technique import Technique
from app.models.world_entity import WorldEntity
from app.models.world_rule import WorldRule
from app.schemas.lore import (
    LoreDraft, LoreEntryCreate, LoreEntryOut, LoreEntryUpdate,
    LoreExportIn, LoreExportOut, LoreFuseIn, LoreSourceItem,
)
from app.services import lore_mapping

router = APIRouter()

# (origin, kind) -> 模型；tavern 只有 rule
_ORIGIN_MODEL = {
    ("lore", "item"): LoreEntry,
    ("lore", "skill"): LoreEntry,
    ("lore", "rule"): LoreEntry,
    ("novel", "item"): WorldEntity,
    ("novel", "skill"): Technique,
    ("novel", "rule"): WorldRule,
    ("rpg", "item"): RpgItem,
    ("rpg", "skill"): RpgSkill,
    ("rpg", "rule"): RpgRule,
    ("tavern", "rule"): TavernRule,
}
_NOVEL_MODEL = {"item": WorldEntity, "skill": Technique, "rule": WorldRule}
_RPG_MODEL = {"item": RpgItem, "skill": RpgSkill}


async def _get_owned(db: AsyncSession, entry_id: int, user) -> LoreEntry:
    entry = await db.get(LoreEntry, entry_id)
    if not entry or entry.user_id != user.id:
        raise HTTPException(status_code=404, detail="设定不存在")
    return entry


async def _get_owned_module(db: AsyncSession, module_id: int, user) -> RpgModule:
    module = await db.get(RpgModule, module_id)
    if not module or module.user_id != user.id:
        raise HTTPException(status_code=404, detail="模组不存在")
    return module


async def _get_owned_card(db: AsyncSession, card_id: int, user) -> TavernCard:
    card = await db.get(TavernCard, card_id)
    if not card or card.user_id != user.id:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    return card


async def _load_source(db: AsyncSession, origin: str, kind: str, obj_id: int, user):
    """载入来源并校验归属；不存在、归属不符、种类不符一律 404。"""
    model = _ORIGIN_MODEL.get((origin, kind))
    if model is None:
        raise HTTPException(status_code=404, detail="来源设定不存在")
    obj = await db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="来源设定不存在")
    if origin == "lore":
        owned = obj.user_id == user.id and obj.kind == kind
    elif origin == "novel":
        novel = await db.get(Novel, obj.novel_id)
        owned = novel is not None and novel.user_id == user.id
        if kind == "item":
            owned = owned and obj.type == "item"
        elif kind == "rule":
            owned = owned and obj.kind == "rule"
    elif origin == "rpg":
        if kind == "rule":
            owned = obj.user_id == user.id
        else:
            module = await db.get(RpgModule, obj.module_id)
            owned = module is not None and module.user_id == user.id
    else:
        owned = obj.user_id == user.id
    if not owned:
        raise HTTPException(status_code=404, detail="来源设定不存在")
    return obj


@router.get("/sources", response_model=list[LoreSourceItem])
async def list_sources(kind: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if kind not in _NOVEL_MODEL:
        raise HTTPException(status_code=400, detail="未知设定类型")
    items: list[LoreSourceItem] = []

    entries = (await db.execute(
        select(LoreEntry)
        .where(LoreEntry.user_id == user.id, LoreEntry.kind == kind)
        .order_by(LoreEntry.updated_at.desc())
    )).scalars().all()
    for e in entries:
        items.append(LoreSourceItem(
            origin="lore", kind=e.kind, id=e.id, name=e.name, group="设定库",
            brief=(e.description or "")[:60],
        ))

    if kind == "item":
        rows = (await db.execute(
            select(WorldEntity, Novel.title)
            .join(Novel, Novel.id == WorldEntity.novel_id)
            .where(Novel.user_id == user.id, WorldEntity.type == "item")
            .order_by(Novel.id, WorldEntity.id)
        )).all()
        for obj, title in rows:
            items.append(LoreSourceItem(
                origin="novel", kind="item", id=obj.id, name=obj.name,
                group=f"小说：{title}", brief=(obj.description or "")[:60],
            ))
    elif kind == "skill":
        rows = (await db.execute(
            select(Technique, Novel.title)
            .join(Novel, Novel.id == Technique.novel_id)
            .where(Novel.user_id == user.id)
            .order_by(Novel.id, Technique.id)
        )).all()
        for obj, title in rows:
            items.append(LoreSourceItem(
                origin="novel", kind="skill", id=obj.id, name=obj.name,
                group=f"小说：{title}", brief=(obj.description or "")[:60],
            ))
    else:
        rows = (await db.execute(
            select(WorldRule, Novel.title)
            .join(Novel, Novel.id == WorldRule.novel_id)
            .where(Novel.user_id == user.id, WorldRule.kind == "rule")
            .order_by(Novel.id, WorldRule.id)
        )).all()
        for obj, title in rows:
            items.append(LoreSourceItem(
                origin="novel", kind="rule", id=obj.id, name=obj.title or "",
                group=f"小说：{title}", brief=(obj.content or "")[:60],
            ))

    if kind in ("item", "skill"):
        model = _RPG_MODEL[kind]
        rows = (await db.execute(
            select(model, RpgModule.name)
            .join(RpgModule, RpgModule.id == model.module_id)
            .where(RpgModule.user_id == user.id)
            .order_by(RpgModule.id, model.sort_order, model.id)
        )).all()
        for obj, module_name in rows:
            items.append(LoreSourceItem(
                origin="rpg", kind=kind, id=obj.id, name=obj.name,
                group=f"模组：{module_name}", brief=(obj.description or "")[:60],
            ))
    else:
        rules = (await db.execute(
            select(RpgRule).where(RpgRule.user_id == user.id)
            .order_by(RpgRule.sort_order, RpgRule.id)
        )).scalars().all()
        for obj in rules:
            items.append(LoreSourceItem(
                origin="rpg", kind="rule", id=obj.id, name=obj.name,
                group="RPG 规则", brief=(obj.content or "")[:60],
            ))

        rules = (await db.execute(
            select(TavernRule).where(TavernRule.user_id == user.id)
            .order_by(TavernRule.sort_order, TavernRule.id)
        )).scalars().all()
        for obj in rules:
            items.append(LoreSourceItem(
                origin="tavern", kind="rule", id=obj.id, name=obj.name,
                group="酒馆规则", brief=(obj.content or "")[:60],
            ))
    return items


@router.post("/fuse", response_model=LoreDraft)
async def fuse(data: LoreFuseIn, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    kinds = {ref.kind for ref in data.sources}
    if len(kinds) > 1:
        raise HTTPException(status_code=400, detail="只能融合同一类设定")
    kind = kinds.pop()

    sources = []
    for ref in data.sources:
        obj = await _load_source(db, ref.origin, ref.kind, ref.id, user)
        neutral = lore_mapping.to_neutral(ref.origin, ref.kind, obj)
        sources.append({**neutral, "weight": ref.weight, "instruction": ref.instruction.strip()})
    try:
        return await lore_agent.fuse(kind, sources, data.goal, data.model_ref)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/entries", response_model=list[LoreEntryOut])
async def list_entries(
    user: CurrentUser, kind: str | None = None, db: AsyncSession = Depends(get_db)
):
    stmt = select(LoreEntry).where(LoreEntry.user_id == user.id)
    if kind:
        stmt = stmt.where(LoreEntry.kind == kind)
    return (await db.execute(stmt.order_by(LoreEntry.updated_at.desc()))).scalars().all()


@router.post("/entries", response_model=LoreEntryOut)
async def create_entry(
    data: LoreEntryCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    entry = LoreEntry(user_id=user.id, **data.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.patch("/entries/{entry_id}", response_model=LoreEntryOut)
async def update_entry(
    entry_id: int, data: LoreEntryUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    entry = await _get_owned(db, entry_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(entry, field, value)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    entry = await _get_owned(db, entry_id, user)
    await db.delete(entry)
    await db.commit()
    return {"ok": True}


@router.post("/entries/{entry_id}/export", response_model=LoreExportOut)
async def export_entry(
    entry_id: int, data: LoreExportIn, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    entry = await _get_owned(db, entry_id, user)
    neutral = lore_mapping.to_neutral("lore", entry.kind, entry)
    fields = lore_mapping.export_fields(data.target, entry.kind, neutral)

    if data.target == "novel":
        if data.novel_id is None:
            raise HTTPException(status_code=400, detail="导出到小说需要指定小说")
        await get_owned_novel(db, data.novel_id, user)
        row = _NOVEL_MODEL[entry.kind](novel_id=data.novel_id, **fields)
    elif data.target == "rpg":
        if data.module_id is None:
            raise HTTPException(status_code=400, detail="导出到 RPG 需要指定模组")
        await _get_owned_module(db, data.module_id, user)
        if entry.kind == "rule":
            row = RpgRule(user_id=user.id, **fields)
        else:
            row = _RPG_MODEL[entry.kind](module_id=data.module_id, **fields)
    else:
        if entry.kind == "rule":
            row = TavernRule(user_id=user.id, **fields)
        else:
            if data.card_id is None:
                raise HTTPException(status_code=400, detail="导出到酒馆需要指定角色卡")
            await _get_owned_card(db, data.card_id, user)
            row = TavernWorldEntry(card_id=data.card_id, **fields)

    db.add(row)
    await db.commit()
    await db.refresh(row)
    return LoreExportOut(target=data.target, id=row.id)
