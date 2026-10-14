"""章节历史版本：正文被覆盖之前存一份旧稿，作者可以对比、恢复。"""
from datetime import datetime, timedelta

from sqlalchemy import select, delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_version import ChapterVersion

# 每章最多留几版，超出删最旧的
MAX_VERSIONS = 30
# 手动编辑（含自动保存，每停手 2 秒存一次）只在距上一版超过这么久时才存，免得刷满历史
EDIT_INTERVAL = timedelta(minutes=10)


async def snapshot(db: AsyncSession, chapter: Chapter, reason: str) -> None:
    """把 chapter 当前正文存成一版。空正文、与上一版相同时跳过。"""
    content = chapter.content or ""
    if not content.strip():
        return
    latest = (await db.execute(
        select(ChapterVersion)
        .where(ChapterVersion.chapter_id == chapter.id)
        .order_by(ChapterVersion.created_at.desc(), ChapterVersion.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if latest is not None:
        if latest.content == content:
            return
        if reason == "edit" and datetime.utcnow() - latest.created_at < EDIT_INTERVAL:
            return
    db.add(ChapterVersion(
        novel_id=chapter.novel_id,
        chapter_id=chapter.id,
        content=content,
        word_count=len(content),
        reason=reason,
    ))
    await db.flush()
    keep = (await db.execute(
        select(ChapterVersion.id)
        .where(ChapterVersion.chapter_id == chapter.id)
        .order_by(ChapterVersion.created_at.desc(), ChapterVersion.id.desc())
        .limit(MAX_VERSIONS)
    )).scalars().all()
    await db.execute(
        sql_delete(ChapterVersion).where(
            ChapterVersion.chapter_id == chapter.id,
            ChapterVersion.id.not_in(keep),
        )
    )


async def delete_for_chapters(db: AsyncSession, chapter_ids: list[int]) -> None:
    if chapter_ids:
        await db.execute(sql_delete(ChapterVersion).where(ChapterVersion.chapter_id.in_(chapter_ids)))
