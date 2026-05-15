from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.memory_item import MemoryItem
from app.schemas.memory_item import MemoryItemCreate, MemoryItemOut, MemoryItemUpdate

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[MemoryItemOut])
async def list_memory_items(
    novel_id: int,
    category: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    subject: Optional[str] = Query(default=None),
    chapter_number: Optional[int] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(MemoryItem).where(MemoryItem.novel_id == novel_id)
    if category:
        stmt = stmt.where(MemoryItem.category == category)
    if status:
        stmt = stmt.where(MemoryItem.status == status)
    if subject:
        stmt = stmt.where(MemoryItem.subject == subject)
    if chapter_number is not None:
        stmt = stmt.where(MemoryItem.chapter_number == chapter_number)
    stmt = stmt.order_by(MemoryItem.chapter_number.desc(), MemoryItem.updated_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{item_id}", response_model=MemoryItemOut)
async def get_memory_item(item_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(MemoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="记忆项不存在")
    return item


@router.post("/", response_model=MemoryItemOut)
async def create_memory_item(data: MemoryItemCreate, db: AsyncSession = Depends(get_db)):
    item = MemoryItem(**data.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=MemoryItemOut)
async def update_memory_item(
    item_id: int,
    data: MemoryItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(MemoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="记忆项不存在")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/{item_id}")
async def delete_memory_item(item_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(MemoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="记忆项不存在")
    await db.delete(item)
    await db.commit()
    return {"ok": True}
