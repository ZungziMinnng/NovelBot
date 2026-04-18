from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.chapter import Chapter
from app.models.novel import Novel
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

    summary, _, _ = await summarizer.summarize_chapter(db, chapter, novel)
    char_ok, char_warning, _, _ = await summarizer.update_character_states(
        db, chapter, novel, instruction=chapter.instruction or ""
    )

    # 更新小说当前进度
    novel.current_chapter = max(novel.current_chapter, chapter.number)
    novel.current_volume = chapter.volume

    await db.commit()
    return {"summary": summary, "status": "confirmed", "char_warning": char_warning or None}


@router.delete("/{chapter_id}")
async def delete_chapter(chapter_id: int, db: AsyncSession = Depends(get_db)):
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    # 清理 ChromaDB 中的 summary + content chunk 向量
    doc_ids = [f"chapter_{chapter_id}_summary"]
    doc_ids.extend(f"chapter_{chapter_id}_chunk_{i}" for i in range(50))
    await vector_store.adelete_docs(chapter.novel_id, doc_ids)
    await db.delete(chapter)
    await db.commit()
    return {"ok": True}
