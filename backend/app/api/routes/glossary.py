from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.glossary_entry import GlossaryEntry
from app.schemas.glossary_entry import GlossaryCreate, GlossaryUpdate, GlossaryOut, CATEGORY_OPTIONS

router = APIRouter()


@router.get("/categories")
async def list_categories():
    return CATEGORY_OPTIONS


@router.get("/novel/{novel_id}", response_model=list[GlossaryOut])
async def list_entries(novel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GlossaryEntry)
        .where(GlossaryEntry.novel_id == novel_id)
        .order_by(GlossaryEntry.importance.desc(), GlossaryEntry.created_at)
    )
    return result.scalars().all()


@router.post("/", response_model=GlossaryOut)
async def create_entry(data: GlossaryCreate, db: AsyncSession = Depends(get_db)):
    entry = GlossaryEntry(**data.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.patch("/{entry_id}", response_model=GlossaryOut)
async def update_entry(entry_id: int, data: GlossaryUpdate, db: AsyncSession = Depends(get_db)):
    entry = await db.get(GlossaryEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="词条不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(entry, k, v)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
async def delete_entry(entry_id: int, db: AsyncSession = Depends(get_db)):
    entry = await db.get(GlossaryEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="词条不存在")
    await db.delete(entry)
    await db.commit()
    return {"ok": True}
