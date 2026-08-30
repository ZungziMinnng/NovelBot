from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.chapter import Chapter
from app.models.story_thread import StoryThread
from app.schemas.story_thread import StoryThreadCreate, StoryThreadOut, StoryThreadUpdate
from app.services.thread_selector import (
    ACTIVE_PER_VOLUME,
    STALE_AFTER_CHAPTERS,
    find_stale_threads,
)
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[StoryThreadOut])
async def list_threads(
    novel_id: int,
    user: CurrentUser,
    kind: str | None = Query(default=None, pattern="^(foreshadowing|secret)$"),
    status: str | None = Query(default=None, pattern="^(active|resolved|abandoned|expired)$"),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_novel(db, novel_id, user)
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


@router.get("/novel/{novel_id}/stale")
async def stale_threads(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """埋太久没回收的伏笔/秘密。只报告，标不标记为已过期由作者定。

    路由声明必须在 /{thread_id} 之前。
    """
    await get_owned_novel(db, novel_id, user)
    current_chapter = int((await db.execute(
        select(func.max(Chapter.number)).where(Chapter.novel_id == novel_id)
    )).scalar() or 0)

    threads = (await db.execute(
        select(StoryThread).where(StoryThread.novel_id == novel_id)
    )).scalars().all()

    active = [t for t in threads if t.status == "active"]
    stale = find_stale_threads(
        [
            {
                "id": t.id, "kind": t.kind, "title": t.title, "content": t.content,
                "status": t.status, "source_chapter": t.source_chapter,
                "due_chapter": t.due_chapter, "importance": t.importance,
            }
            for t in active
        ],
        current_chapter,
    )
    lo, hi = ACTIVE_PER_VOLUME
    density = ""
    if len(active) > hi:
        density = f"当前在场 {len(active)} 条，超过建议上限 {hi} 条，读者记不住这么多线"
    elif active and len(active) < lo:
        density = f"当前在场 {len(active)} 条，低于建议下限 {lo} 条，悬念可能不够"

    return {
        "current_chapter": current_chapter,
        "active_count": len(active),
        "expired_count": sum(1 for t in threads if t.status == "expired"),
        "stale_after": STALE_AFTER_CHAPTERS,
        "density_hint": density,
        "stale": stale,
    }


@router.post("/", response_model=StoryThreadOut)
async def create_thread(data: StoryThreadCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, data.novel_id, user)
    thread = StoryThread(**data.model_dump())
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return thread


@router.patch("/{thread_id}", response_model=StoryThreadOut)
async def update_thread(
    thread_id: int,
    data: StoryThreadUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    thread = await get_owned_child(db, StoryThread, thread_id, user, "伏笔/秘密条目")
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
async def delete_thread(thread_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    thread = await get_owned_child(db, StoryThread, thread_id, user, "伏笔/秘密条目")
    await db.delete(thread)
    await db.commit()
    return {"ok": True}
