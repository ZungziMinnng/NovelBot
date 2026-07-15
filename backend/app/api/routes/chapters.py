import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete, func
from app.database import get_db
from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.character import Character
from app.models.world_entity import WorldEntity
from app.models.location import Location
from app.models.technique import Technique
from app.models.faction import Faction
from app.models.memory import Memory
from app.schemas.chapter import ChapterCreate, ChapterUpdate, ChapterOut, ChapterConfirmRequest
from app.agents import character_agent
from app.services import summarizer, vector_store, entity_embeddings

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

    # 捕获主键为普通 int：rollback 会让 ORM 对象过期，过期对象在异步会话下
    # 访问任意属性都会触发同步懒加载 → greenlet_spawn 错误。各 except 内据此重取活对象。
    chapter_id = chapter.id
    novel_id = chapter.novel_id

    summary = ""
    char_warning = ""
    ent_warning = ""
    loc_warning = ""
    projection_status = {
        "summary": "pending",
        "character_state": "pending",
        "entity_state": "pending",
        "location_state": "pending",
    }

    try:
        summary, _, _ = await summarizer.summarize_chapter(db, chapter, novel)
        projection_status["summary"] = "done" if summary else "skipped"
        await db.commit()
    except Exception as e:
        logging.getLogger(__name__).warning("确认章节时摘要生成失败: %s", e)
        projection_status["summary"] = f"failed:{type(e).__name__}: {e}"
        await db.rollback()
        chapter = await db.get(Chapter, chapter_id)
        novel = await db.get(Novel, novel_id)

    upd_char_ids: list[int] = []
    upd_entity_ids: list[int] = []
    upd_location_ids: list[int] = []
    try:
        char_ok, char_warning, _, _, _, upd_char_ids = await summarizer.update_character_states(
            db, chapter, novel, instruction=chapter.instruction or ""
        )
        projection_status["character_state"] = "done" if char_ok else f"failed:{char_warning or 'unknown'}"
        await db.commit()
    except Exception as e:
        logging.getLogger(__name__).warning("确认章节时角色状态更新失败: %s", e)
        char_warning = str(e)
        projection_status["character_state"] = f"failed:{type(e).__name__}: {e}"
        await db.rollback()
        chapter = await db.get(Chapter, chapter_id)
        novel = await db.get(Novel, novel_id)

    try:
        r = await summarizer.update_entity_location_states(
            db, chapter, novel, instruction=chapter.instruction or ""
        )
        ent_warning = r["entity"]["warning"]
        loc_warning = r["location"]["warning"]
        upd_entity_ids = r["entity"]["updated_ids"]
        upd_location_ids = r["location"]["updated_ids"]
        projection_status["entity_state"] = "done" if r["entity"]["ok"] else f"failed:{ent_warning or 'unknown'}"
        projection_status["location_state"] = "done" if r["location"]["ok"] else f"failed:{loc_warning or 'unknown'}"
        await db.commit()
    except Exception as e:
        logging.getLogger(__name__).warning("确认章节时实体/地点状态更新失败: %s", e)
        ent_warning = str(e)
        loc_warning = ""
        projection_status["entity_state"] = f"failed:{type(e).__name__}: {e}"
        projection_status["location_state"] = f"failed:{type(e).__name__}: {e}"
        await db.rollback()
        chapter = await db.get(Chapter, chapter_id)
        novel = await db.get(Novel, novel_id)

    await entity_embeddings.reembed_updated(
        db, novel_id,
        char_ids=upd_char_ids, entity_ids=upd_entity_ids, location_ids=upd_location_ids,
    )

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
        "book_summary_refreshed": book_summary_refreshed,
    }


class BackfillSummariesRequest(BaseModel):
    mode: str = "missing"  # missing=只补无摘要章节；all=重写全部章节摘要


@router.post("/novel/{novel_id}/backfill-summaries")
async def backfill_summaries(
    novel_id: int,
    body: BackfillSummariesRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """批量生成章节摘要，逐章提交，失败跳过继续。mode=all 时重写已有摘要。"""
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    mode = body.mode if body else "missing"
    conditions = [Chapter.novel_id == novel_id, Chapter.content != ""]
    if mode != "all":
        conditions.append((Chapter.summary.is_(None)) | (Chapter.summary == ""))

    result = await db.execute(
        select(Chapter.id)
        .where(*conditions)
        .order_by(Chapter.volume, Chapter.number)
    )
    chapter_ids = [r[0] for r in result]

    done: list[int] = []
    failed: list[dict] = []
    for cid in chapter_ids:
        # rollback 会让 ORM 对象过期，每轮按 id 重取活对象
        chapter = await db.get(Chapter, cid)
        novel = await db.get(Novel, novel_id)
        try:
            summary, _, _ = await summarizer.summarize_chapter(db, chapter, novel)
            await db.commit()
            if summary:
                done.append(chapter.number)
            else:
                failed.append({"number": chapter.number, "error": "生成结果为空"})
        except Exception as e:
            logging.getLogger(__name__).warning(
                "补全摘要失败: chapter_id=%s: %s", cid, e
            )
            await db.rollback()
            chapter = await db.get(Chapter, cid)
            failed.append({"number": chapter.number, "error": f"{type(e).__name__}: {e}"})

    return {"total": len(chapter_ids), "done": done, "failed": failed}


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

    faction_result = await db.execute(
        select(Faction.name).where(Faction.novel_id == novel.id)
    )
    existing_faction_names = [r[0] for r in faction_result]

    characters, entities, locations, techniques, factions = await character_agent.discover_all_new(
        novel, chapter.content,
        existing_char_names, existing_entity_names, existing_locations,
        existing_tech_names, existing_faction_names,
    )

    return {
        "characters": characters,
        "entities": entities,
        "locations": locations,
        "techniques": techniques,
        "factions": factions,
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


class BatchDeleteRequest(BaseModel):
    chapter_ids: list[int]


@router.post("/batch-delete")
async def batch_delete_chapters(body: BatchDeleteRequest, db: AsyncSession = Depends(get_db)):
    """批量删除章节：连同各章的 Memory 行与摘要向量一并清理，最后按剩余章节回退小说进度。"""
    if not body.chapter_ids:
        return {"ok": True, "deleted": 0}
    chapters = (await db.execute(
        select(Chapter).where(Chapter.id.in_(body.chapter_ids))
    )).scalars().all()
    if not chapters:
        return {"ok": True, "deleted": 0}

    novel_id = chapters[0].novel_id
    ids = [c.id for c in chapters]

    # 删除这些章节的所有 Memory 行，防止污染后续章节的滚动摘要窗口
    await db.execute(sql_delete(Memory).where(Memory.chapter_id.in_(ids)))

    # 清理 ChromaDB 中的 summary 向量（兼容清理历史遗留的 content chunk）
    doc_ids: list[str] = []
    for cid in ids:
        doc_ids.append(f"chapter_{cid}_summary")
        doc_ids.extend(f"chapter_{cid}_chunk_{i}" for i in range(50))
    await vector_store.adelete_docs(novel_id, doc_ids)

    for ch in chapters:
        await db.delete(ch)
    await db.flush()

    # 按剩余章节回退小说进度
    novel = await db.get(Novel, novel_id)
    if novel:
        max_remaining = (await db.execute(
            select(func.max(Chapter.number)).where(Chapter.novel_id == novel_id)
        )).scalar()
        novel.current_chapter = max_remaining or 0

    await db.commit()
    return {"ok": True, "deleted": len(chapters)}
