from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.story_thread import StoryThread
from app.schemas.story_thread import StoryThreadCreate, StoryThreadOut, StoryThreadUpdate

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[StoryThreadOut])
async def list_threads(
    novel_id: int,
    kind: str | None = Query(default=None, pattern="^(foreshadowing|secret)$"),
    status: str | None = Query(default=None, pattern="^(active|resolved|abandoned)$"),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(StoryThread).where(StoryThread.novel_id == novel_id)
    if kind:
        stmt = stmt.where(StoryThread.kind == kind)
    if status:
        stmt = stmt.where(StoryThread.status == status)
    stmt = stmt.order_by(
        StoryThread.status != "active",
        StoryThread.importance.desc(),
        StoryThread.source_chapter,
        StoryThread.id,
    )
    return (await db.execute(stmt)).scalars().all()


@router.post("/", response_model=StoryThreadOut)
async def create_thread(data: StoryThreadCreate, db: AsyncSession = Depends(get_db)):
    thread = StoryThread(**data.model_dump())
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return thread


@router.patch("/{thread_id}", response_model=StoryThreadOut)
async def update_thread(
    thread_id: int,
    data: StoryThreadUpdate,
    db: AsyncSession = Depends(get_db),
):
    thread = await db.get(StoryThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="伏笔/秘密条目不存在")
    values = data.model_dump(exclude_none=True)
    kind = values.get("kind", thread.kind)
    if kind == "foreshadowing":
        values["known_by"] = []
    elif kind == "secret":
        values["due_chapter"] = 0
    for key, value in values.items():
        setattr(thread, key, value)
    await db.commit()
    await db.refresh(thread)
    return thread


@router.delete("/{thread_id}")
async def delete_thread(thread_id: int, db: AsyncSession = Depends(get_db)):
    thread = await db.get(StoryThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="伏笔/秘密条目不存在")
    await db.delete(thread)
    await db.commit()
    return {"ok": True}
