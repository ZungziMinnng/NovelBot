from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.world_entity import WorldEntity
from app.schemas.world_entity import WorldEntityCreate, WorldEntityUpdate, WorldEntityOut

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[WorldEntityOut])
async def list_entities(
    novel_id: int,
    type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = select(WorldEntity).where(WorldEntity.novel_id == novel_id)
    if type:
        query = query.where(WorldEntity.type == type)
    query = query.order_by(WorldEntity.created_at)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{entity_id}", response_model=WorldEntityOut)
async def get_entity(entity_id: int, db: AsyncSession = Depends(get_db)):
    entity = await db.get(WorldEntity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    return entity


@router.post("/", response_model=WorldEntityOut)
async def create_entity(data: WorldEntityCreate, db: AsyncSession = Depends(get_db)):
    entity = WorldEntity(**data.model_dump())
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    return entity


@router.patch("/{entity_id}", response_model=WorldEntityOut)
async def update_entity(entity_id: int, data: WorldEntityUpdate, db: AsyncSession = Depends(get_db)):
    entity = await db.get(WorldEntity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(entity, k, v)
    await db.commit()
    await db.refresh(entity)
    return entity


@router.delete("/{entity_id}")
async def delete_entity(entity_id: int, db: AsyncSession = Depends(get_db)):
    entity = await db.get(WorldEntity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    await db.delete(entity)
    await db.commit()
    return {"ok": True}
