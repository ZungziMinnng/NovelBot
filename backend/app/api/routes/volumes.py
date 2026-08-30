from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.volume import Volume
from app.schemas.volume import VolumeCreate, VolumeUpdate, VolumeOut
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[VolumeOut])
async def list_volumes(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    result = await db.execute(
        select(Volume)
        .where(Volume.novel_id == novel_id)
        .order_by(Volume.number)
    )
    return result.scalars().all()


@router.post("/", response_model=VolumeOut)
async def create_volume(data: VolumeCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, data.novel_id, user)
    vol = Volume(**data.model_dump())
    db.add(vol)
    await db.commit()
    await db.refresh(vol)
    return vol


@router.patch("/{volume_id}", response_model=VolumeOut)
async def update_volume(
    volume_id: int, data: VolumeUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    vol = await get_owned_child(db, Volume, volume_id, user, "分卷")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(vol, k, v)
    await db.commit()
    await db.refresh(vol)
    return vol


@router.delete("/{volume_id}")
async def delete_volume(volume_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    vol = await get_owned_child(db, Volume, volume_id, user, "分卷")
    await db.delete(vol)
    await db.commit()
    return {"ok": True}
