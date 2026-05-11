from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.location import Location
from app.schemas.location import LocationCreate, LocationUpdate, LocationOut
from app.services.entity_embeddings import embed_location, remove_entity_embedding

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[LocationOut])
async def list_locations(
    novel_id: int,
    type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = select(Location).where(Location.novel_id == novel_id)
    if type:
        query = query.where(Location.type == type)
    query = query.order_by(Location.name)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{location_id}", response_model=LocationOut)
async def get_location(location_id: int, db: AsyncSession = Depends(get_db)):
    loc = await db.get(Location, location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="地点不存在")
    return loc


@router.post("/", response_model=LocationOut)
async def create_location(data: LocationCreate, db: AsyncSession = Depends(get_db)):
    loc = Location(**data.model_dump())
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    await embed_location(loc.novel_id, loc)
    return loc


@router.patch("/{location_id}", response_model=LocationOut)
async def update_location(location_id: int, data: LocationUpdate, db: AsyncSession = Depends(get_db)):
    loc = await db.get(Location, location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="地点不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(loc, k, v)
    await db.commit()
    await db.refresh(loc)
    await embed_location(loc.novel_id, loc)
    return loc


@router.delete("/{location_id}")
async def delete_location(location_id: int, db: AsyncSession = Depends(get_db)):
    loc = await db.get(Location, location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="地点不存在")
    novel_id = loc.novel_id
    loc_id = loc.id
    await db.delete(loc)
    await db.commit()
    await remove_entity_embedding(novel_id, "location", loc_id)
    return {"ok": True}
