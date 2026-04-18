from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.writer_preset import WriterPreset
from app.schemas.writer_preset import WriterPresetCreate, WriterPresetUpdate, WriterPresetOut

router = APIRouter()


@router.get("/", response_model=list[WriterPresetOut])
async def list_presets(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WriterPreset).order_by(WriterPreset.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=WriterPresetOut)
async def create_preset(data: WriterPresetCreate, db: AsyncSession = Depends(get_db)):
    preset = WriterPreset(name=data.name, prompt=data.prompt)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.get("/{preset_id}", response_model=WriterPresetOut)
async def get_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    preset = await db.get(WriterPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")
    return preset


@router.patch("/{preset_id}", response_model=WriterPresetOut)
async def update_preset(
    preset_id: int, data: WriterPresetUpdate, db: AsyncSession = Depends(get_db)
):
    preset = await db.get(WriterPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")
    if data.name is not None:
        preset.name = data.name
    if data.prompt is not None:
        preset.prompt = data.prompt
    await db.commit()
    await db.refresh(preset)
    return preset


@router.delete("/{preset_id}")
async def delete_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    preset = await db.get(WriterPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")
    await db.delete(preset)
    await db.commit()
    return {"ok": True}
