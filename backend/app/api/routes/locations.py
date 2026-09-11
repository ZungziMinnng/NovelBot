from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update as sql_update
from app.database import get_db
from app.models.location import Location
from app.models.faction import Faction
from app.schemas.location import LocationCreate, LocationUpdate, LocationOut
from app.services.entity_embeddings import embed_location, remove_entity_embedding
from app.services import state_snapshot
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[LocationOut])
async def list_locations(
    novel_id: int,
    user: CurrentUser,
    type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_novel(db, novel_id, user)
    query = select(Location).where(Location.novel_id == novel_id)
    if type:
        query = query.where(Location.type == type)
    query = query.order_by(Location.name)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{location_id}", response_model=LocationOut)
async def get_location(location_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await get_owned_child(db, Location, location_id, user, "地点")


@router.post("/", response_model=LocationOut)
async def create_location(data: LocationCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, data.novel_id, user)
    loc = Location(**data.model_dump())
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    await embed_location(loc.novel_id, loc)
    return loc


@router.patch("/{location_id}", response_model=LocationOut)
async def update_location(location_id: int, data: LocationUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    loc = await get_owned_child(db, Location, location_id, user, "地点")
    fields = data.model_dump(exclude_unset=True)
    for k, v in fields.items():
        setattr(loc, k, v)
    # 手改的状态同步进最新快照，否则重新确认时的回滚会把它一起冲掉
    if "current_state" in fields:
        await state_snapshot.patch_latest(
            db, loc.novel_id, "locations", loc.id, loc.current_state,
        )
    await db.commit()
    await db.refresh(loc)
    await embed_location(loc.novel_id, loc)
    return loc


@router.delete("/{location_id}")
async def delete_location(location_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    loc = await get_owned_child(db, Location, location_id, user, "地点")
    novel_id = loc.novel_id
    loc_id = loc.id
    # 清掉指向本地点的引用：子地点 parent_id（外键硬约束）与势力驻地（软引用）
    await db.execute(
        sql_update(Location).where(Location.parent_id == loc_id).values(parent_id=None)
    )
    await db.execute(
        sql_update(Faction).where(Faction.location_id == loc_id).values(location_id=None)
    )
    await db.delete(loc)
    await db.commit()
    await remove_entity_embedding(novel_id, "location", loc_id)
    return {"ok": True}
