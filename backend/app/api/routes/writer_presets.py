from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.writer_preset import WriterPreset
from app.schemas.writer_preset import WriterPresetCreate, WriterPresetUpdate, WriterPresetOut
from app.api.deps import CurrentUser

router = APIRouter()


async def _get_owned_preset(db: AsyncSession, preset_id: int, user) -> WriterPreset:
    preset = await db.get(WriterPreset, preset_id)
    if not preset or preset.user_id != user.id:
        raise HTTPException(status_code=404, detail="预设不存在")
    return preset


@router.get("/", response_model=list[WriterPresetOut])
async def list_presets(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WriterPreset)
        .where(WriterPreset.user_id == user.id)
        .order_by(WriterPreset.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=WriterPresetOut)
async def create_preset(data: WriterPresetCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    preset = WriterPreset(name=data.name, prompt=data.prompt, examples=data.examples, user_id=user.id)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.get("/{preset_id}", response_model=WriterPresetOut)
async def get_preset(preset_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await _get_owned_preset(db, preset_id, user)


@router.patch("/{preset_id}", response_model=WriterPresetOut)
async def update_preset(
    preset_id: int, data: WriterPresetUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    preset = await _get_owned_preset(db, preset_id, user)
    if data.name is not None:
        preset.name = data.name
    if data.prompt is not None:
        preset.prompt = data.prompt
    if data.examples is not None:
        preset.examples = data.examples
    await db.commit()
    await db.refresh(preset)
    return preset


@router.delete("/{preset_id}")
async def delete_preset(preset_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    preset = await _get_owned_preset(db, preset_id, user)
    await db.delete(preset)
    await db.commit()
    return {"ok": True}
