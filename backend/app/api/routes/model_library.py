from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.model_library import ModelEntry
from app.models.api_provider import ApiProvider
from app.schemas.model_library import ModelEntryCreate, ModelEntryUpdate, ModelEntryOut

router = APIRouter()


async def _fill_from_provider(entry: ModelEntry, provider_id: int | None, db: AsyncSession):
    """如果提供了 provider_id，从供应商记录填充 provider 和 api_format 反规范化字段。"""
    if provider_id is None:
        return
    provider = await db.get(ApiProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=400, detail=f"供应商 ID {provider_id} 不存在")
    entry.provider_id = provider_id
    entry.provider = provider.name
    entry.api_format = provider.api_format


async def _refresh_cache(db: AsyncSession):
    from app.services import llm_client
    llm_client.clear_llm_client_cache()
    await llm_client.refresh_model_formats(db)


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
        model_type=data.model_type,
    )
    await _fill_from_provider(entry, data.provider_id, db)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    await _refresh_cache(db)
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
    if data.model_type is not None:
        entry.model_type = data.model_type
    if data.provider_id is not None:
        await _fill_from_provider(entry, data.provider_id, db)
    else:
        if data.provider is not None:
            entry.provider = data.provider
        if data.api_format is not None:
            entry.api_format = data.api_format
    await db.commit()
    await db.refresh(entry)
    await _refresh_cache(db)
    return entry


@router.delete("/{model_id}")
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db)):
    entry = await db.get(ModelEntry, model_id)
    if not entry:
        raise HTTPException(status_code=404, detail="模型不存在")
    await db.delete(entry)
    await db.commit()
    await _refresh_cache(db)
    return {"ok": True}
