"""调整章节顺序 / 在中间插入新章。

只动「最后一章已确认章节之后」的未确认章：已确认的章节摘要、角色状态、伏笔都按章号累积过，
挪动它们等于改写历史。未确认章挪动时，下面这些按章号存的东西跟着换号：
- 章节自己（chapters.number 有唯一索引，先挪到负数临时号再落到目标号）
- 指向该章的 Memory（按 chapter_id 跟着走）；状态快照 chapter_id 为空，按章号映射
- 章级大纲（大纲是「第 N 章写什么」，作者挪章就是挪剧情，计划跟着那一章走）
- 伏笔的起/收章、世界观变更的生效章、作者便签挂的章
- 摘要向量 metadata 里的 chapter_number
LLM 用量账本按当时的章号记，是历史流水，不改。
"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.author_note import AuthorNote
from app.models.chapter import Chapter
from app.models.memory import Memory, Outline
from app.models.story_thread import StoryThread
from app.models.worldview_change import WorldviewChange
from app.services import vector_store


class OrderError(ValueError):
    pass


async def last_confirmed_number(db: AsyncSession, novel_id: int) -> int:
    return int((await db.execute(
        select(func.max(Chapter.number)).where(
            Chapter.novel_id == novel_id, Chapter.status == "confirmed",
        )
    )).scalar() or 0)


async def movable_chapters(db: AsyncSession, novel_id: int) -> list[Chapter]:
    floor = await last_confirmed_number(db, novel_id)
    return list((await db.execute(
        select(Chapter)
        .where(Chapter.novel_id == novel_id, Chapter.number > floor)
        .order_by(Chapter.number)
    )).scalars().all())


async def _apply_mapping(db: AsyncSession, novel_id: int, chapters: list[Chapter], by_number: dict[int, int]) -> None:
    """by_number: 旧章号 → 新章号（只含真的变了的）。chapters 是要换号的章节对象。"""
    if not by_number:
        return
    by_id = {c.id: by_number[c.number] for c in chapters if c.number in by_number}
    by_number_old = {c.id: c.number for c in chapters if c.id in by_id}

    # 唯一索引 (novel_id, number)：直接互换会撞，先全部挪到负数临时号
    for c in chapters:
        if c.id in by_id:
            c.number = -c.id
    await db.flush()
    for c in chapters:
        if c.id in by_id:
            # 默认标题「第N章」是按章号起的，跟着换；作者自己起的标题不动
            if c.title == f"第{by_number_old[c.id]}章":
                c.title = f"第{by_id[c.id]}章"
            c.number = by_id[c.id]
    await db.flush()

    old_numbers = list(by_number)
    memories = (await db.execute(
        select(Memory).where(
            Memory.novel_id == novel_id,
            (Memory.chapter_id.in_(list(by_id))) | (
                Memory.chapter_id.is_(None)
                & (Memory.memory_type == "state_snapshot")
                & Memory.chapter_number.in_(old_numbers)
            ),
        )
    )).scalars().all()
    for m in memories:
        if m.chapter_id is not None:
            m.chapter_number = by_id[m.chapter_id]
        else:
            m.chapter_number = by_number[m.chapter_number]

    outlines = (await db.execute(
        select(Outline).where(
            Outline.novel_id == novel_id,
            Outline.level == "chapter",
            Outline.chapter_number.in_(old_numbers),
        )
    )).scalars().all()
    for o in outlines:
        o.chapter_number = by_number[o.chapter_number]

    threads = (await db.execute(
        select(StoryThread).where(
            StoryThread.novel_id == novel_id,
            StoryThread.source_chapter.in_(old_numbers) | StoryThread.resolved_chapter.in_(old_numbers),
        )
    )).scalars().all()
    for t in threads:
        t.source_chapter = by_number.get(t.source_chapter, t.source_chapter)
        t.resolved_chapter = by_number.get(t.resolved_chapter, t.resolved_chapter)

    changes = (await db.execute(
        select(WorldviewChange).where(
            WorldviewChange.novel_id == novel_id,
            WorldviewChange.effective_chapter.in_(old_numbers),
        )
    )).scalars().all()
    for w in changes:
        w.effective_chapter = by_number[w.effective_chapter]

    notes = (await db.execute(
        select(AuthorNote).where(
            AuthorNote.novel_id == novel_id,
            AuthorNote.chapter_number.in_(old_numbers),
        )
    )).scalars().all()
    for n in notes:
        n.chapter_number = by_number[n.chapter_number]


async def sync_vectors(novel_id: int, moved: dict[int, int]) -> None:
    """提交之后再改向量 metadata（网络/磁盘 IO 不抱着写锁做）。moved: chapter_id → 新章号。"""
    for chapter_id, number in moved.items():
        await vector_store.aupdate_metadata(
            novel_id, f"chapter_{chapter_id}_summary", {"chapter_number": number},
        )


async def reorder(db: AsyncSession, novel_id: int, chapter_ids: list[int]) -> dict[int, int]:
    """chapter_ids 是可移动那一段的新顺序，必须恰好是那一段的全部章节。
    沿用原来那组章号（中间有删章留下的空号也保留），按新顺序依次分配。返回 chapter_id → 新章号。"""
    chapters = await movable_chapters(db, novel_id)
    if sorted(chapter_ids) != sorted(c.id for c in chapters) or len(set(chapter_ids)) != len(chapter_ids):
        raise OrderError("只能调整最后一章已确认章节之后的未确认章节，章节列表已变化，请刷新后重试")
    numbers = [c.number for c in chapters]
    target = dict(zip(chapter_ids, numbers))
    moved = {c.id: target[c.id] for c in chapters if target[c.id] != c.number}
    by_number = {c.number: target[c.id] for c in chapters if c.id in moved}
    await _apply_mapping(db, novel_id, chapters, by_number)
    return moved


async def insert_before(db: AsyncSession, novel_id: int, before_chapter_id: int, title: str = "") -> tuple[Chapter, dict[int, int]]:
    """在 before_chapter_id 那一章前面插一个空章，它和后面的章节号各 +1。
    后面还没写的章级大纲也一起往后推，计划才对得上。返回 (新章节, 被挪动的 chapter_id → 新章号)。"""
    chapters = await movable_chapters(db, novel_id)
    anchor = next((c for c in chapters if c.id == before_chapter_id), None)
    if anchor is None:
        raise OrderError("只能插在最后一章已确认章节之后")
    at = anchor.number
    tail = [c for c in chapters if c.number >= at]
    by_number = {c.number: c.number + 1 for c in tail}
    # 没写出来的章也可能已经有大纲，同样要往后推，否则会被插进来的空章「认领」
    planned = (await db.execute(
        select(Outline.chapter_number).where(
            Outline.novel_id == novel_id,
            Outline.level == "chapter",
            Outline.chapter_number >= at,
        )
    )).scalars().all()
    noted = (await db.execute(
        select(AuthorNote.chapter_number).where(
            AuthorNote.novel_id == novel_id,
            AuthorNote.chapter_number >= at,
        )
    )).scalars().all()
    for n in [*planned, *noted]:
        by_number.setdefault(n, n + 1)
    await _apply_mapping(db, novel_id, tail, by_number)

    chapter = Chapter(
        novel_id=novel_id,
        volume=anchor.volume,
        number=at,
        title=title or f"第{at}章",
        content="",
        word_count=0,
    )
    db.add(chapter)
    await db.flush()
    return chapter, {c.id: c.number for c in tail}
