import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.memory import Memory
from app.schemas.chapter import ChapterCreate, ChapterUpdate, ChapterOut, ChapterConfirmRequest
from app.services import summarizer, vector_store

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[ChapterOut])
async def list_chapters(novel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Chapter)
        .where(Chapter.novel_id == novel_id)
        .order_by(Chapter.volume, Chapter.number)
    )
    return result.scalars().all()


@router.get("/{chapter_id}", response_model=ChapterOut)
async def get_chapter(chapter_id: int, db: AsyncSession = Depends(get_db)):
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return chapter


@router.post("/", response_model=ChapterOut)
async def create_chapter(data: ChapterCreate, db: AsyncSession = Depends(get_db)):
    chapter = Chapter(**data.model_dump())
    chapter.word_count = len(chapter.content)
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return chapter


@router.patch("/{chapter_id}", response_model=ChapterOut)
async def update_chapter(chapter_id: int, data: ChapterUpdate, db: AsyncSession = Depends(get_db)):
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(chapter, k, v)
    if data.content is not None:
        chapter.word_count = len(data.content)
    await db.commit()
    await db.refresh(chapter)
    return chapter


@router.post("/confirm")
async def confirm_chapter(req: ChapterConfirmRequest, db: AsyncSession = Depends(get_db)):
    """确认章节 → 触发摘要生成和记忆更新"""
    chapter = await db.get(Chapter, req.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    novel = await db.get(Novel, chapter.novel_id)
    chapter.status = "confirmed"

    try:
        (summary, _, _), (char_ok, char_warning, _, _), (ent_ok, ent_warning, _, _) = await asyncio.gather(
            summarizer.summarize_chapter(db, chapter, novel),
            summarizer.update_character_states(db, chapter, novel, instruction=chapter.instruction or ""),
            summarizer.update_entity_states(db, chapter, novel, instruction=chapter.instruction or ""),
        )
    except Exception as e:
        # LLM 调用失败不应阻塞确认
        import logging
        logging.getLogger(__name__).warning("确认章节时记忆更新部分失败: %s", e)
        summary = ""
        char_warning = str(e)
        ent_warning = ""

    # 更新小说当前进度
    novel.current_chapter = max(novel.current_chapter, chapter.number)
    novel.current_volume = chapter.volume

    await db.commit()

    # 自动刷新故事弧概要（每 15 章）
    if chapter.number >= 15 and chapter.number % 15 == 0:
        try:
            await summarizer.generate_arc_summary(
                db, novel,
                start_chapter=chapter.number - 14,
                end_chapter=chapter.number,
            )
            await db.commit()
        except Exception:
            logging.getLogger(__name__).warning("确认章节时弧概要生成失败", exc_info=True)

    # 自动刷新全书概要（每 5 章刷新一次，避免长程记忆过时）
    book_summary_refreshed = False
    if chapter.number >= 5 and chapter.number % 5 == 0:
        try:
            await summarizer.generate_book_summary(db, novel)
            await db.commit()
            book_summary_refreshed = True
        except Exception:
            import logging
            logging.getLogger(__name__).warning("自动刷新全书概要失败", exc_info=True)

    warnings = [w for w in (char_warning, ent_warning) if w]
    return {
        "summary": summary,
        "status": "confirmed",
        "char_warning": "; ".join(warnings) if warnings else None,
        "book_summary_refreshed": book_summary_refreshed,
    }


@router.delete("/{chapter_id}")
async def delete_chapter(chapter_id: int, db: AsyncSession = Depends(get_db)):
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    # 解除 memories 表的外键引用，避免删除时外键约束失败
    result = await db.execute(select(Memory).where(Memory.chapter_id == chapter_id))
    for mem in result.scalars():
        mem.chapter_id = None
    # 清理 ChromaDB 中的 summary 向量（兼容清理历史遗留的 content chunk）
    doc_ids = [f"chapter_{chapter_id}_summary"]
    doc_ids.extend(f"chapter_{chapter_id}_chunk_{i}" for i in range(50))
    await vector_store.adelete_docs(chapter.novel_id, doc_ids)
    await db.delete(chapter)
    await db.commit()
    return {"ok": True}
