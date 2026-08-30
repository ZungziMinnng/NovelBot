from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.glossary_entry import GlossaryEntry
from app.schemas.glossary_entry import GlossaryCreate, GlossaryUpdate, GlossaryOut, CATEGORY_OPTIONS
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()


@router.get("/categories")
async def list_categories(user: CurrentUser):
    return CATEGORY_OPTIONS


@router.get("/novel/{novel_id}", response_model=list[GlossaryOut])
async def list_entries(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    result = await db.execute(
        select(GlossaryEntry)
        .where(GlossaryEntry.novel_id == novel_id)
        .order_by(GlossaryEntry.importance.desc(), GlossaryEntry.created_at)
    )
    return result.scalars().all()


@router.post("/", response_model=GlossaryOut)
async def create_entry(data: GlossaryCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, data.novel_id, user)
    entry = GlossaryEntry(**data.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.patch("/{entry_id}", response_model=GlossaryOut)
async def update_entry(entry_id: int, data: GlossaryUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    entry = await get_owned_child(db, GlossaryEntry, entry_id, user, "词条")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(entry, k, v)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
async def delete_entry(entry_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    entry = await get_owned_child(db, GlossaryEntry, entry_id, user, "词条")
    await db.delete(entry)
    await db.commit()
    return {"ok": True}
