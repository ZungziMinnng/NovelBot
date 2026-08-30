from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.faction import Faction
from app.schemas.faction import FactionCreate, FactionUpdate, FactionOut
from app.services.entity_embeddings import embed_faction, remove_entity_embedding
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[FactionOut])
async def list_factions(
    novel_id: int,
    user: CurrentUser,
    alignment: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_novel(db, novel_id, user)
    query = select(Faction).where(Faction.novel_id == novel_id)
    if alignment:
        query = query.where(Faction.alignment == alignment)
    query = query.order_by(Faction.created_at)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", response_model=FactionOut)
async def create_faction(data: FactionCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, data.novel_id, user)
    faction = Faction(**data.model_dump())
    db.add(faction)
    await db.commit()
    await db.refresh(faction)
    await embed_faction(faction.novel_id, faction)
    return faction


@router.patch("/{faction_id}", response_model=FactionOut)
async def update_faction(
    faction_id: int, data: FactionUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    faction = await get_owned_child(db, Faction, faction_id, user, "势力")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(faction, k, v)
    await db.commit()
    await db.refresh(faction)
    await embed_faction(faction.novel_id, faction)
    return faction


@router.delete("/{faction_id}")
async def delete_faction(faction_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    faction = await get_owned_child(db, Faction, faction_id, user, "势力")
    novel_id = faction.novel_id
    fac_id = faction.id
    await db.delete(faction)
    await db.commit()
    await remove_entity_embedding(novel_id, "faction", fac_id)
    return {"ok": True}
