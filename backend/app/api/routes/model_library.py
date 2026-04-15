from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.model_library import ModelEntry
from app.schemas.model_library import ModelEntryCreate, ModelEntryUpdate, ModelEntryOut

router = APIRouter()


@router.get("/", response_model=list[ModelEntryOut])
async def list_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelEntry).order_by(ModelEntry.id))
    return result.scalars().all()


@router.post("/", response_model=ModelEntryOut)
async def create_model(data: ModelEntryCreate, db: AsyncSession = Depends(get_db)):
    entry = ModelEntry(
        display_name=data.display_name,
        model_id=data.model_id,
        provider=data.provider,
        api_format=data.api_format,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    # Refresh in-memory format cache
    from app.services import llm_client
    await llm_client.refresh_model_formats(db)
    return entry


@router.patch("/{model_id}", response_model=ModelEntryOut)
async def update_model(model_id: int, data: ModelEntryUpdate, db: AsyncSession = Depends(get_db)):
    entry = await db.get(ModelEntry, model_id)
    if not entry:
        raise HTTPException(status_code=404, detail="模型不存在")
    if data.display_name is not None:
        entry.display_name = data.display_name
    if data.model_id is not None:
        entry.model_id = data.model_id
    if data.provider is not None:
        entry.provider = data.provider
    if data.api_format is not None:
        entry.api_format = data.api_format
    await db.commit()
    await db.refresh(entry)
    # Refresh in-memory format cache
    from app.services import llm_client
    await llm_client.refresh_model_formats(db)
    return entry


@router.delete("/{model_id}")
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db)):
    entry = await db.get(ModelEntry, model_id)
    if not entry:
        raise HTTPException(status_code=404, detail="模型不存在")
    await db.delete(entry)
    await db.commit()
    # Refresh in-memory format cache
    from app.services import llm_client
    await llm_client.refresh_model_formats(db)
    return {"ok": True}
