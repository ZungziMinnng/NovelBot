from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.novel import Novel
from app.models.worldview_change import WorldviewChange
from app.schemas.worldview_change import (
    WorldviewChangeCreate, WorldviewChangeUpdate, WorldviewChangeOut,
)
from app.services import summarizer

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[WorldviewChangeOut])
async def list_changes(novel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WorldviewChange)
        .where(WorldviewChange.novel_id == novel_id)
        .order_by(WorldviewChange.effective_chapter, WorldviewChange.created_at)
    )
    return result.scalars().all()


@router.post("/", response_model=WorldviewChangeOut)
async def create_change(data: WorldviewChangeCreate, db: AsyncSession = Depends(get_db)):
    change = WorldviewChange(**data.model_dump())
    db.add(change)
    await db.commit()
    await db.refresh(change)
    return change


@router.patch("/{change_id}", response_model=WorldviewChangeOut)
async def update_change(change_id: int, data: WorldviewChangeUpdate, db: AsyncSession = Depends(get_db)):
    change = await db.get(WorldviewChange, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="变更条目不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(change, k, v)
    await db.commit()
    await db.refresh(change)
    return change


@router.delete("/{change_id}")
async def delete_change(change_id: int, db: AsyncSession = Depends(get_db)):
    change = await db.get(WorldviewChange, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="变更条目不存在")
    await db.delete(change)
    await db.commit()
    return {"ok": True}


@router.post("/novel/{novel_id}/scan")
async def scan_changes(novel_id: int, db: AsyncSession = Depends(get_db)):
    """手动触发 AI 检测：找出被剧情推翻的世界观设定，写成 pending 供用户确认。"""
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    drifts = await summarizer.detect_worldview_drift(db, novel, recent=10)
    new_rows = await summarizer.persist_pending_drifts(db, novel_id, drifts)
    await db.commit()
    return {"detected": len(drifts), "added": len(new_rows)}
