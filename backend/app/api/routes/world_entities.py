from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.world_entity import WorldEntity
from app.models.technique import Technique
from app.schemas.world_entity import WorldEntityCreate, WorldEntityUpdate, WorldEntityOut
from app.schemas.technique import TechniqueOut
from app.services.entity_embeddings import embed_world_entity, embed_technique, remove_entity_embedding

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
    await embed_world_entity(entity.novel_id, entity)
    return entity


@router.patch("/{entity_id}", response_model=WorldEntityOut)
async def update_entity(entity_id: int, data: WorldEntityUpdate, db: AsyncSession = Depends(get_db)):
    entity = await db.get(WorldEntity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    old_type_key = f"entity_{entity.type}"
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(entity, k, v)
    await db.commit()
    await db.refresh(entity)
    new_type_key = f"entity_{entity.type}"
    if old_type_key != new_type_key:
        await remove_entity_embedding(entity.novel_id, old_type_key, entity.id)
    await embed_world_entity(entity.novel_id, entity)
    return entity


@router.delete("/{entity_id}")
async def delete_entity(entity_id: int, db: AsyncSession = Depends(get_db)):
    entity = await db.get(WorldEntity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    novel_id = entity.novel_id
    type_key = f"entity_{entity.type}"
    entity_id_val = entity.id
    await db.delete(entity)
    await db.commit()
    await remove_entity_embedding(novel_id, type_key, entity_id_val)
    return {"ok": True}


@router.post("/{entity_id}/convert-to-technique", response_model=TechniqueOut)
async def convert_to_technique(entity_id: int, db: AsyncSession = Depends(get_db)):
    entity = await db.get(WorldEntity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    novel_id = entity.novel_id
    old_type_key = f"entity_{entity.type}"
    old_id = entity.id
    technique = Technique(
        novel_id=novel_id,
        name=entity.name,
        description=entity.description or "",
    )
    db.add(technique)
    await db.delete(entity)
    await db.commit()
    await db.refresh(technique)
    await remove_entity_embedding(novel_id, old_type_key, old_id)
    await embed_technique(novel_id, technique)
    return technique
