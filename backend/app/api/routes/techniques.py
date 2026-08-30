from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.technique import Technique
from app.models.world_entity import WorldEntity
from app.schemas.technique import TechniqueCreate, TechniqueUpdate, TechniqueOut
from app.schemas.world_entity import WorldEntityOut
from app.services.entity_embeddings import embed_technique, embed_world_entity, remove_entity_embedding
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[TechniqueOut])
async def list_techniques(
    novel_id: int,
    user: CurrentUser,
    type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_novel(db, novel_id, user)
    query = select(Technique).where(Technique.novel_id == novel_id)
    if type:
        query = query.where(Technique.type == type)
    query = query.order_by(Technique.created_at)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", response_model=TechniqueOut)
async def create_technique(data: TechniqueCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, data.novel_id, user)
    technique = Technique(**data.model_dump())
    db.add(technique)
    await db.commit()
    await db.refresh(technique)
    await embed_technique(technique.novel_id, technique)
    return technique


@router.patch("/{technique_id}", response_model=TechniqueOut)
async def update_technique(
    technique_id: int, data: TechniqueUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    technique = await get_owned_child(db, Technique, technique_id, user, "功法")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(technique, k, v)
    await db.commit()
    await db.refresh(technique)
    await embed_technique(technique.novel_id, technique)
    return technique


@router.delete("/{technique_id}")
async def delete_technique(technique_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    technique = await get_owned_child(db, Technique, technique_id, user, "功法")
    novel_id = technique.novel_id
    tech_id = technique.id
    await db.delete(technique)
    await db.commit()
    await remove_entity_embedding(novel_id, "technique", tech_id)
    return {"ok": True}


class ConvertToEntityBody(BaseModel):
    type: str  # "item" | "system"


@router.post("/{technique_id}/convert-to-entity", response_model=WorldEntityOut)
async def convert_technique_to_entity(
    technique_id: int, body: ConvertToEntityBody, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    if body.type not in ("item", "system"):
        raise HTTPException(status_code=400, detail="type 必须是 item 或 system")
    technique = await get_owned_child(db, Technique, technique_id, user, "功法")
    novel_id = technique.novel_id
    old_tech_id = technique.id
    entity = WorldEntity(
        novel_id=novel_id,
        name=technique.name,
        type=body.type,
        description=technique.description,
    )
    db.add(entity)
    await db.delete(technique)
    await db.commit()
    await db.refresh(entity)
    await remove_entity_embedding(novel_id, "technique", old_tech_id)
    await embed_world_entity(novel_id, entity)
    return entity
