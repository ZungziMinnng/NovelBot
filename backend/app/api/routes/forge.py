from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import forge_agent
from app.api.deps import CurrentUser, get_owned_novel
from app.database import get_db
from app.models.character import Character
from app.models.forge import ForgeCharacter
from app.models.novel import Novel
from app.models.rpg import RpgModule, RpgNpc
from app.models.tavern import TavernCard
from app.schemas.forge import (
    ForgeCharacterCreate, ForgeCharacterOut, ForgeCharacterUpdate, ForgeDraft,
    ForgeExportIn, ForgeExportOut, ForgeFuseIn, ForgeSourceItem,
)
from app.services import forge_mapping

router = APIRouter()

_KIND_MODEL = {"tavern": TavernCard, "npc": RpgNpc, "novel": Character}


async def _get_owned(db: AsyncSession, char_id: int, user) -> ForgeCharacter:
    char = await db.get(ForgeCharacter, char_id)
    if not char or char.user_id != user.id:
        raise HTTPException(status_code=404, detail="熔炉角色不存在")
    return char


async def _get_owned_module(db: AsyncSession, module_id: int, user) -> RpgModule:
    module = await db.get(RpgModule, module_id)
    if not module or module.user_id != user.id:
        raise HTTPException(status_code=404, detail="模组不存在")
    return module


async def _load_source(db: AsyncSession, kind: str, obj_id: int, user):
    """载入来源并校验归属；不存在或非本人一律 404。"""
    obj = await db.get(_KIND_MODEL[kind], obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="来源角色不存在")
    if kind == "tavern":
        owned = obj.user_id == user.id
    elif kind == "npc":
        module = await db.get(RpgModule, obj.module_id)
        owned = module is not None and module.user_id == user.id
    else:
        novel = await db.get(Novel, obj.novel_id)
        owned = novel is not None and novel.user_id == user.id
    if not owned:
        raise HTTPException(status_code=404, detail="来源角色不存在")
    return obj


@router.get("/sources", response_model=list[ForgeSourceItem])
async def list_sources(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    items: list[ForgeSourceItem] = []

    cards = (await db.execute(
        select(TavernCard).where(TavernCard.user_id == user.id).order_by(TavernCard.updated_at.desc())
    )).scalars().all()
    for c in cards:
        items.append(ForgeSourceItem(
            kind="tavern", id=c.id, name=c.name, group="酒馆",
            avatar_url=c.avatar_url or "", brief=(c.description or c.personality or "")[:60],
        ))

    novel_rows = (await db.execute(
        select(Character, Novel.title)
        .join(Novel, Novel.id == Character.novel_id)
        .where(Novel.user_id == user.id)
        .order_by(Novel.id, Character.id)
    )).all()
    for c, title in novel_rows:
        items.append(ForgeSourceItem(
            kind="novel", id=c.id, name=c.name, group=f"小说：{title}",
            avatar_url=c.avatar_url or "", brief=(c.description or "")[:60],
        ))

    npc_rows = (await db.execute(
        select(RpgNpc, RpgModule.name)
        .join(RpgModule, RpgModule.id == RpgNpc.module_id)
        .where(RpgModule.user_id == user.id)
        .order_by(RpgModule.id, RpgNpc.sort_order, RpgNpc.id)
    )).all()
    for n, module_name in npc_rows:
        items.append(ForgeSourceItem(
            kind="npc", id=n.id, name=n.name, group=f"模组：{module_name}",
            avatar_url=n.avatar_url or "", brief=(n.description or "")[:60],
        ))
    return items


@router.post("/fuse", response_model=ForgeDraft)
async def fuse(data: ForgeFuseIn, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    sources = []
    for ref in data.sources:
        obj = await _load_source(db, ref.kind, ref.id, user)
        neutral = forge_mapping.to_neutral(ref.kind, obj)
        sources.append({**neutral, "weight": ref.weight, "instruction": ref.instruction.strip()})
    try:
        return await forge_agent.fuse(sources, data.goal, data.model_ref)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/characters", response_model=list[ForgeCharacterOut])
async def list_characters(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return (await db.execute(
        select(ForgeCharacter)
        .where(ForgeCharacter.user_id == user.id)
        .order_by(ForgeCharacter.updated_at.desc())
    )).scalars().all()


@router.post("/characters", response_model=ForgeCharacterOut)
async def create_character(
    data: ForgeCharacterCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    char = ForgeCharacter(user_id=user.id, **data.model_dump())
    db.add(char)
    await db.commit()
    await db.refresh(char)
    return char


@router.patch("/characters/{char_id}", response_model=ForgeCharacterOut)
async def update_character(
    char_id: int, data: ForgeCharacterUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    char = await _get_owned(db, char_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(char, field, value)
    await db.commit()
    await db.refresh(char)
    return char


@router.delete("/characters/{char_id}")
async def delete_character(char_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    char = await _get_owned(db, char_id, user)
    await db.delete(char)
    await db.commit()
    return {"ok": True}


@router.post("/characters/{char_id}/export", response_model=ForgeExportOut)
async def export_character(
    char_id: int, data: ForgeExportIn, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    char = await _get_owned(db, char_id, user)
    neutral = {
        "name": char.name, "dialogue_examples": char.dialogue_examples or [],
        **{k: getattr(char, k) or "" for k in forge_mapping.TEXT_FIELDS},
    }
    if data.target == "tavern":
        row = TavernCard(user_id=user.id, **forge_mapping.to_tavern(neutral))
    elif data.target == "npc":
        if data.module_id is None:
            raise HTTPException(status_code=400, detail="导出成 NPC 需要指定模组")
        await _get_owned_module(db, data.module_id, user)
        row = RpgNpc(module_id=data.module_id, **forge_mapping.to_npc(neutral))
    else:
        if data.novel_id is None:
            raise HTTPException(status_code=400, detail="导出成小说角色需要指定小说")
        await get_owned_novel(db, data.novel_id, user)
        row = Character(novel_id=data.novel_id, **forge_mapping.to_novel(neutral))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ForgeExportOut(target=data.target, id=row.id)
