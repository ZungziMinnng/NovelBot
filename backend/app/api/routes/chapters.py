import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete
from app.database import get_db
from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.character import Character
from app.models.world_entity import WorldEntity
from app.models.location import Location
from app.models.technique import Technique
from app.models.memory import Memory
from app.schemas.chapter import ChapterCreate, ChapterUpdate, ChapterOut, ChapterConfirmRequest
from app.agents import character_agent
from app.services import memory_item_writer, summarizer, vector_store

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

    summary = ""
    char_warning = ""
    ent_warning = ""
    loc_warning = ""
    projection_status = {
        "summary": "pending",
        "character_state": "pending",
        "entity_state": "pending",
        "location_state": "pending",
        "memory_items": "pending",
    }
    memory_item_stats = {}
    before_character_states = await memory_item_writer.snapshot_character_states(db, novel.id)

    try:
        summary, _, _ = await summarizer.summarize_chapter(db, chapter, novel)
        projection_status["summary"] = "done" if summary else "skipped"
        await db.commit()
    except Exception as e:
        logging.getLogger(__name__).warning("确认章节时摘要生成失败: %s", e)
        projection_status["summary"] = f"failed:{type(e).__name__}: {e}"
        await db.rollback()

    try:
        char_ok, char_warning, _, _, _ = await summarizer.update_character_states(
            db, chapter, novel, instruction=chapter.instruction or ""
        )
        projection_status["character_state"] = "done" if char_ok else f"failed:{char_warning or 'unknown'}"
        await db.commit()
    except Exception as e:
        logging.getLogger(__name__).warning("确认章节时角色状态更新失败: %s", e)
        char_warning = str(e)
        projection_status["character_state"] = f"failed:{type(e).__name__}: {e}"
        await db.rollback()

    try:
        ent_ok, ent_warning, _, _, _ = await summarizer.update_entity_states(
            db, chapter, novel, instruction=chapter.instruction or ""
        )
        projection_status["entity_state"] = "done" if ent_ok else f"failed:{ent_warning or 'unknown'}"
        await db.commit()
    except Exception as e:
        logging.getLogger(__name__).warning("确认章节时实体状态更新失败: %s", e)
        ent_warning = str(e)
        projection_status["entity_state"] = f"failed:{type(e).__name__}: {e}"
        await db.rollback()

    try:
        loc_ok, loc_warning, _, _, _ = await summarizer.update_location_states(
            db, chapter, novel, instruction=chapter.instruction or ""
        )
        projection_status["location_state"] = "done" if loc_ok else f"failed:{loc_warning or 'unknown'}"
        await db.commit()
    except Exception as e:
        logging.getLogger(__name__).warning("确认章节时地点状态更新失败: %s", e)
        loc_warning = str(e)
        projection_status["location_state"] = f"failed:{type(e).__name__}: {e}"
        await db.rollback()

    try:
        memory_item_stats = await memory_item_writer.write_basic_memory_items(
            db,
            novel,
            chapter,
            before_character_states=before_character_states,
            summary=summary,
        )
        projection_status["memory_items"] = "done"
        await db.commit()
    except Exception as e:
        logging.getLogger(__name__).warning("确认章节时结构化记忆写入失败: %s", e)
        projection_status["memory_items"] = f"failed:{type(e).__name__}: {e}"
        await db.rollback()

    # 更新小说当前进度
    chapter.status = "confirmed"
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
                volume=chapter.volume,
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

    warnings = [w for w in (char_warning, ent_warning, loc_warning) if w]
    return {
        "summary": summary,
        "status": "confirmed",
        "char_warning": "; ".join(warnings) if warnings else None,
        "projection_status": projection_status,
        "memory_item_stats": memory_item_stats,
        "book_summary_refreshed": book_summary_refreshed,
    }


@router.post("/{chapter_id}/discover")
async def discover_entities(chapter_id: int, db: AsyncSession = Depends(get_db)):
    """对已有章节重新运行角色/实体/地点发现"""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if not chapter.content:
        raise HTTPException(status_code=400, detail="章节无内容")

    novel = await db.get(Novel, chapter.novel_id)

    char_result = await db.execute(
        select(Character.name).where(Character.novel_id == novel.id)
    )
    existing_char_names = [r[0] for r in char_result]

    entity_result = await db.execute(
        select(WorldEntity.name).where(WorldEntity.novel_id == novel.id)
    )
    existing_entity_names = [r[0] for r in entity_result]

    loc_result = await db.execute(
        select(Location.name, Location.type).where(Location.novel_id == novel.id)
    )
    existing_locations = [{"name": r[0], "type": r[1], "parent_name": ""} for r in loc_result]

    tech_result = await db.execute(
        select(Technique.name).where(Technique.novel_id == novel.id)
    )
    existing_tech_names = [r[0] for r in tech_result]

    characters, entities, locations, techniques = await asyncio.gather(
        character_agent.discover_new_characters(novel, chapter.content, existing_char_names),
        character_agent.discover_new_entities(novel, chapter.content, existing_entity_names),
        character_agent.discover_new_locations(novel, chapter.content, existing_locations),
        character_agent.discover_new_techniques(novel, chapter.content, existing_tech_names),
    )

    return {
        "characters": characters,
        "entities": entities,
        "locations": locations,
        "techniques": techniques,
    }


class BatchVolumeRequest(BaseModel):
    chapter_ids: list[int]
    volume: int


@router.post("/batch-volume")
async def batch_update_volume(body: BatchVolumeRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Chapter).where(Chapter.id.in_(body.chapter_ids))
    )
    chapters = result.scalars().all()
    for ch in chapters:
        ch.volume = body.volume
    await db.commit()
    return {"ok": True, "updated": len(chapters)}


@router.delete("/{chapter_id}")
async def delete_chapter(chapter_id: int, db: AsyncSession = Depends(get_db)):
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    # 删除该章节的所有 Memory 行，防止污染后续章节的滚动摘要窗口
    await db.execute(
        sql_delete(Memory).where(
            Memory.chapter_id == chapter.id,
        )
    )
    # 清理 ChromaDB 中的 summary 向量（兼容清理历史遗留的 content chunk）
    doc_ids = [f"chapter_{chapter_id}_summary"]
    doc_ids.extend(f"chapter_{chapter_id}_chunk_{i}" for i in range(50))
    await vector_store.adelete_docs(chapter.novel_id, doc_ids)
    # 若删除的是最新章节，回退小说进度
    novel = await db.get(Novel, chapter.novel_id)
    if novel and chapter.number == novel.current_chapter:
        novel.current_chapter = chapter.number - 1
    await db.delete(chapter)
    await db.commit()
    return {"ok": True}
