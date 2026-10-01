from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.style_profile import StyleProfile
from app.schemas.style_profile import (
    StyleAdaptIn,
    StyleProfileCreate,
    StyleProfileOut,
    StyleProfilePreview,
    StyleProfileUpdate,
)
from app.api.deps import CurrentUser
from app.agents import style_agent
from app.services import llm_json
from app.services.style_extract import (
    all_chunks,
    compute_stats,
    decode_text,
    sample_chunks,
    split_chapters,
)

router = APIRouter()

_MAX_UPLOAD = 30 * 1024 * 1024


async def _get_owned(db: AsyncSession, profile_id: int, user) -> StyleProfile:
    profile = await db.get(StyleProfile, profile_id)
    if not profile or profile.user_id != user.id:
        raise HTTPException(status_code=404, detail="文风不存在")
    return profile


@router.post("/import", response_model=StyleProfilePreview)
async def import_profile(
    user: CurrentUser,
    file: UploadFile = File(...),
    categories: list[str] = Form([]),
    model: str = Form(""),
):
    """只出预览，不入库：用户看过、改过、点了确认才走 POST /。"""
    # 自定义类别是用户手填的：去空白、去重、截短、限个数（每类都要一次模型调用）
    cats = list(dict.fromkeys(c.strip()[:20] for c in categories if c.strip()))[:8]
    if not cats:
        raise HTTPException(status_code=400, detail="至少选一类要提取的内容")

    raw = await file.read()
    if len(raw) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="文件不能超过 30MB")

    chapters = split_chapters(decode_text(raw))
    chunks = sample_chunks(chapters)
    if not chunks:
        raise HTTPException(status_code=400, detail="没有抽到可用的段落，检查文件是不是小说正文")

    stats = compute_stats(chunks)
    try:
        result = await style_agent.analyze(chunks, all_chunks(chapters), cats, stats, model)
    except llm_json.JsonCallError as e:
        raise HTTPException(status_code=502, detail=f"文风分析失败：{e}")
    except ValueError as e:
        # 没配默认模型 / 模型不属于当前用户 / 书里没找到所选内容
        raise HTTPException(status_code=400, detail=str(e))

    name = (file.filename or "未命名").rsplit(".", 1)[0][:100]
    return StyleProfilePreview(name=name, stats=stats, **result)


@router.get("/", response_model=list[StyleProfileOut])
async def list_profiles(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StyleProfile)
        .where(StyleProfile.user_id == user.id)
        .order_by(StyleProfile.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=StyleProfileOut)
async def create_profile(data: StyleProfileCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    profile = StyleProfile(user_id=user.id, **data.model_dump())
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/{profile_id}", response_model=StyleProfileOut)
async def get_profile(profile_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await _get_owned(db, profile_id, user)


@router.patch("/{profile_id}", response_model=StyleProfileOut)
async def update_profile(
    profile_id: int, data: StyleProfileUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    profile = await _get_owned(db, profile_id, user)
    if data.name is not None:
        profile.name = data.name
    if data.style_desc is not None:
        profile.style_desc = data.style_desc
    if data.characters is not None:
        profile.characters = [c.model_dump() for c in data.characters]
    if data.scenes is not None:
        profile.scenes = [s.model_dump() for s in data.scenes]
    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete("/{profile_id}")
async def delete_profile(profile_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    profile = await _get_owned(db, profile_id, user)
    await db.delete(profile)
    await db.commit()
    return {"ok": True}


@router.post("/{profile_id}/adapt")
async def adapt_profile(
    profile_id: int, data: StyleAdaptIn, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """转换结果只回给前端填表单，不写任何目标——保存由用户在各自页面点。"""
    profile = await _get_owned(db, profile_id, user)
    try:
        return await style_agent.adapt(
            profile, data.mode, data.scene_indexes, data.character, data.name_map, data.model
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
