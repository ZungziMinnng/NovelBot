from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.api_provider import ApiProvider
from app.models.model_library import ModelEntry
from app.schemas.api_provider import ApiProviderCreate, ApiProviderUpdate, ApiProviderOut
from app.api.deps import CurrentUser

router = APIRouter()


async def _get_owned_provider(db: AsyncSession, provider_id: int, user) -> ApiProvider:
    provider = await db.get(ApiProvider, provider_id)
    if not provider or provider.user_id != user.id:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return provider


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


def _to_out(p: ApiProvider) -> ApiProviderOut:
    return ApiProviderOut(
        id=p.id,
        name=p.name,
        base_url=p.base_url,
        api_key_set=bool(p.api_key),
        api_key_masked=_mask_key(p.api_key),
        api_format=p.api_format,
        use_proxy=p.use_proxy,
        created_at=p.created_at,
    )


@router.get("/", response_model=list[ApiProviderOut])
async def list_providers(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ApiProvider).where(ApiProvider.user_id == user.id).order_by(ApiProvider.id)
    )
    return [_to_out(p) for p in result.scalars()]


@router.post("/", response_model=ApiProviderOut)
async def create_provider(data: ApiProviderCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    provider = ApiProvider(
        name=data.name,
        base_url=data.base_url,
        api_key=data.api_key,
        api_format=data.api_format,
        use_proxy=data.use_proxy,
        user_id=user.id,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    await _refresh_cache(db)
    return _to_out(provider)


@router.patch("/{provider_id}", response_model=ApiProviderOut)
async def update_provider(provider_id: int, data: ApiProviderUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    provider = await _get_owned_provider(db, provider_id, user)
    if data.name is not None:
        provider.name = data.name
    if data.base_url is not None:
        provider.base_url = data.base_url
    if data.api_key is not None and data.api_key != "":
        provider.api_key = data.api_key
    if data.api_format is not None:
        provider.api_format = data.api_format
    if data.use_proxy is not None:
        provider.use_proxy = data.use_proxy
    await db.commit()
    await db.refresh(provider)
    # 同步更新引用该供应商的模型的反规范化字段
    result = await db.execute(
        select(ModelEntry).where(ModelEntry.provider_id == provider.id)
    )
    for m in result.scalars():
        m.provider = provider.name
        m.api_format = provider.api_format
    await db.commit()
    await _refresh_cache(db)
    return _to_out(provider)


@router.delete("/{provider_id}")
async def delete_provider(provider_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    provider = await _get_owned_provider(db, provider_id, user)
    # 检查是否有模型引用
    result = await db.execute(
        select(ModelEntry).where(ModelEntry.provider_id == provider_id).limit(1)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该供应商下仍有模型，请先删除或迁移相关模型")
    await db.delete(provider)
    await db.commit()
    await _refresh_cache(db)
    return {"ok": True}


async def _refresh_cache(db: AsyncSession):
    from app.services import llm_client
    await llm_client.refresh_provider_cache(db)
    await llm_client.refresh_model_formats(db)
