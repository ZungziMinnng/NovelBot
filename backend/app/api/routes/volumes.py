from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.volume import Volume
from app.schemas.volume import VolumeCreate, VolumeUpdate, VolumeOut

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[VolumeOut])
async def list_volumes(novel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Volume)
        .where(Volume.novel_id == novel_id)
        .order_by(Volume.number)
    )
    return result.scalars().all()


@router.post("/", response_model=VolumeOut)
async def create_volume(data: VolumeCreate, db: AsyncSession = Depends(get_db)):
    vol = Volume(**data.model_dump())
    db.add(vol)
    await db.commit()
    await db.refresh(vol)
    return vol


@router.patch("/{volume_id}", response_model=VolumeOut)
async def update_volume(
    volume_id: int, data: VolumeUpdate, db: AsyncSession = Depends(get_db)
):
    vol = await db.get(Volume, volume_id)
    if not vol:
        raise HTTPException(status_code=404, detail="分卷不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(vol, k, v)
    await db.commit()
    await db.refresh(vol)
    return vol


@router.delete("/{volume_id}")
async def delete_volume(volume_id: int, db: AsyncSession = Depends(get_db)):
    vol = await db.get(Volume, volume_id)
    if not vol:
        raise HTTPException(status_code=404, detail="分卷不存在")
    await db.delete(vol)
    await db.commit()
    return {"ok": True}
