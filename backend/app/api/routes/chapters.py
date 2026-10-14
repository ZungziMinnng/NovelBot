import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete, func, update as sql_update
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
from app.models.chapter_version import ChapterVersion
from app.services import summarizer, vector_store, entity_embeddings, prose_lint, state_snapshot
from app.services import chapter_versions, chapter_order, word_stats
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()


async def _owned_chapters_by_ids(db: AsyncSession, chapter_ids: list[int], user) -> list[Chapter]:
    """按 id 批量取章节并逐一校验归属（任一不属于当前用户即 404）。"""
    chapters = (await db.execute(
        select(Chapter).where(Chapter.id.in_(chapter_ids))
    )).scalars().all()
    for novel_id in {c.novel_id for c in chapters}:
        await get_owned_novel(db, novel_id, user)
    return chapters


class LintRequest(BaseModel):
    text: str


@router.post("/lint")
async def lint_text(body: LintRequest, user: CurrentUser):
    """对编辑器里的正文跑一遍机械体检，返回 findings。

    收正文而不是 chapter_id：编辑器里的草稿可能还没保存，作者要看的是眼前这一版。
    这里和 critic 的打回用同一个 prose_lint，口径不会分叉。纯函数、不碰库。
    """
    findings = prose_lint.lint(body.text or "")
    return {
        "findings": findings,
        "blocking_count": sum(1 for f in findings if f["severity"] == "blocking"),
    }


@router.get("/novel/{novel_id}", response_model=list[ChapterOut])
async def list_chapters(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    result = await db.execute(
        select(Chapter)
        .where(Chapter.novel_id == novel_id)
        # 章节号全书连续递增，按 number 排序；按 (volume, number) 会让未分卷章节插到已分卷之前
        .order_by(Chapter.number)
    )
    return result.scalars().all()


@router.get("/{chapter_id}", response_model=ChapterOut)
async def get_chapter(chapter_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await get_owned_child(db, Chapter, chapter_id, user, "章节")


@router.post("/", response_model=ChapterOut)
async def create_chapter(data: ChapterCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, data.novel_id, user)
    chapter = Chapter(**data.model_dump())
    chapter.word_count = len(chapter.content)
    db.add(chapter)
    await db.flush()
    await word_stats.record(db, chapter.novel_id, chapter.word_count)
    await db.commit()
    await db.refresh(chapter)
    return chapter


@router.patch("/{chapter_id}", response_model=ChapterOut)
async def update_chapter(chapter_id: int, data: ChapterUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    chapter = await get_owned_child(db, Chapter, chapter_id, user, "章节")
    old_words = chapter.word_count or 0
    if data.content is not None and data.content != chapter.content:
        # 手动编辑走自动保存，每停手 2 秒一次；snapshot 内部按时间间隔节流
        await chapter_versions.snapshot(db, chapter, "edit")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(chapter, k, v)
    if data.content is not None:
        chapter.word_count = len(data.content)
        await word_stats.record(db, chapter.novel_id, chapter.word_count - old_words)
    await db.commit()
    await db.refresh(chapter)
    return chapter


@router.post("/confirm")
async def confirm_chapter(req: ChapterConfirmRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """确认章节 → 触发摘要生成和记忆更新"""
    chapter = await get_owned_child(db, Chapter, req.chapter_id, user, "章节")

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

    # 状态更新是累积的（只有非空值才覆盖），重复确认同一章会把上次的结论一直留着——
    # 作者删掉的设定洗不掉。先回滚到本章生成前，再按当前正文重新累积。
    # 但回滚是全量恢复，后面几章累积的状态会一起被抹掉，所以只在本章是最新已确认章时才做。
    rollback_note = ""
    latest_confirmed = (await db.execute(
        select(func.max(Chapter.number)).where(
            Chapter.novel_id == novel_id,
            Chapter.status == "confirmed",
        )
    )).scalar()
    if latest_confirmed is not None and latest_confirmed > chapter.number:
        rollback_note = (
            f"第 {chapter.number} 章之后还有已确认章节（最新第 {latest_confirmed} 章），"
            "本次没有回滚状态：删掉的设定可能仍留在角色状态里，需要的话手动改。"
        )
    else:
        try:
            rolled_back = await state_snapshot.rollback_or_create(
                db, novel_id, chapter.number, chapter.volume or 1,
            )
            await db.commit()
            if not rolled_back:
                rollback_note = "本章没有状态快照，已按当前状态建立基线，这次不回滚。"
        except Exception as e:
            logging.getLogger(__name__).warning("确认章节时状态回滚失败: %s", e)
            rollback_note = f"状态回滚失败（{type(e).__name__}），本次在现有状态上累积。"
            await db.rollback()
            chapter = await db.get(Chapter, chapter_id)
            novel = await db.get(Novel, novel_id)

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

    warnings = [w for w in (char_warning, ent_warning, loc_warning, rollback_note) if w]
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
    user: CurrentUser,
    body: BackfillSummariesRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """批量生成章节摘要，逐章提交，失败跳过继续。mode=all 时重写已有摘要。"""
    novel = await get_owned_novel(db, novel_id, user)

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
async def discover_entities(chapter_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """对已有章节重新运行角色/实体/地点发现"""
    chapter = await get_owned_child(db, Chapter, chapter_id, user, "章节")
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
    for c in characters:
        c["source_chapter"] = chapter.number

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
async def batch_update_volume(body: BatchVolumeRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    chapters = await _owned_chapters_by_ids(db, body.chapter_ids, user)
    for ch in chapters:
        ch.volume = body.volume
    # 同步 Memory.volume，否则滚动摘要/快照按卷过滤会与章节漂移，静默丢上下文
    if chapters:
        await db.execute(
            sql_update(Memory)
            .where(
                Memory.novel_id == chapters[0].novel_id,
                Memory.chapter_number.in_([ch.number for ch in chapters]),
            )
            .values(volume=body.volume)
        )
    await db.commit()
    return {"ok": True, "updated": len(chapters)}


@router.delete("/{chapter_id}")
async def delete_chapter(chapter_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    chapter = await get_owned_child(db, Chapter, chapter_id, user, "章节")
    await _wait_memory(chapter.novel_id)
    # 删的是最新章就把状态卡恢复到它生成之前，否则重写时还带着被删内容的结论
    rolled_back = await state_snapshot.rewind_deleted(db, chapter.novel_id, [chapter])
    # 删除该章节的所有 Memory 行，防止污染后续章节的滚动摘要窗口
    await db.execute(
        sql_delete(Memory).where(
            Memory.chapter_id == chapter.id,
        )
    )
    # state_snapshot 按 (novel_id, chapter_number) 存且 chapter_id 为空，须单独删，
    # 否则重建同号章节时会用旧快照回滚人物状态
    await db.execute(
        sql_delete(Memory).where(
            Memory.novel_id == chapter.novel_id,
            Memory.memory_type == "state_snapshot",
            Memory.chapter_number == chapter.number,
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
    await _forget_chapters(db, [chapter.id])
    removed_words = chapter.word_count or 0
    novel_id = chapter.novel_id
    await db.delete(chapter)
    await word_stats.record(db, novel_id, -removed_words)
    await db.commit()
    return {"ok": True, "state_rolled_back": rolled_back}


async def _wait_memory(novel_id: int) -> None:
    """刚生成完记忆管线还在后台写状态，不等它跑完，回滚之后又会被写回去。"""
    from app.agents.orchestrator import _pending_memory
    pending = _pending_memory(novel_id)
    if pending:
        await asyncio.wait({pending})


async def _forget_chapters(db: AsyncSession, chapter_ids: list[int]) -> None:
    """删章时一并清掉它的历史版本。挂在章号上的便签不动：那一章重写时还要提醒。"""
    await chapter_versions.delete_for_chapters(db, chapter_ids)


class BatchDeleteRequest(BaseModel):
    chapter_ids: list[int]


@router.post("/batch-delete")
async def batch_delete_chapters(body: BatchDeleteRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """批量删除章节：连同各章的 Memory 行与摘要向量一并清理，最后按剩余章节回退小说进度。"""
    if not body.chapter_ids:
        return {"ok": True, "deleted": 0}
    chapters = await _owned_chapters_by_ids(db, body.chapter_ids, user)
    if not chapters:
        return {"ok": True, "deleted": 0}

    novel_id = chapters[0].novel_id
    ids = [c.id for c in chapters]

    await _wait_memory(novel_id)
    rolled_back = await state_snapshot.rewind_deleted(db, novel_id, chapters)

    # 删除这些章节的所有 Memory 行，防止污染后续章节的滚动摘要窗口
    await db.execute(sql_delete(Memory).where(Memory.chapter_id.in_(ids)))
    # state_snapshot 按 (novel_id, chapter_number) 存且 chapter_id 为空，须单独删
    await db.execute(
        sql_delete(Memory).where(
            Memory.novel_id == novel_id,
            Memory.memory_type == "state_snapshot",
            Memory.chapter_number.in_([c.number for c in chapters]),
        )
    )

    # 清理 ChromaDB 中的 summary 向量（兼容清理历史遗留的 content chunk）
    doc_ids: list[str] = []
    for cid in ids:
        doc_ids.append(f"chapter_{cid}_summary")
        doc_ids.extend(f"chapter_{cid}_chunk_{i}" for i in range(50))
    await vector_store.adelete_docs(novel_id, doc_ids)

    await _forget_chapters(db, ids)
    removed_words = sum(ch.word_count or 0 for ch in chapters)
    for ch in chapters:
        await db.delete(ch)
    await db.flush()
    await word_stats.record(db, novel_id, -removed_words)

    # 按剩余章节回退小说进度
    novel = await db.get(Novel, novel_id)
    if novel:
        max_remaining = (await db.execute(
            select(func.max(Chapter.number)).where(Chapter.novel_id == novel_id)
        )).scalar()
        novel.current_chapter = max_remaining or 0

    await db.commit()
    return {"ok": True, "deleted": len(chapters), "state_rolled_back": rolled_back}


# ── 调整顺序 / 插入新章 ─────────────────────────────────────────────────────

class ReorderRequest(BaseModel):
    novel_id: int
    chapter_ids: list[int]


@router.post("/reorder")
async def reorder_chapters(body: ReorderRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """调整最后一章已确认章节之后那一段未确认章节的顺序。规则见 services/chapter_order.py。"""
    await get_owned_novel(db, body.novel_id, user)
    try:
        moved = await chapter_order.reorder(db, body.novel_id, body.chapter_ids)
    except chapter_order.OrderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await db.commit()
    await chapter_order.sync_vectors(body.novel_id, moved)
    return {"ok": True, "moved": len(moved)}


class InsertChapterRequest(BaseModel):
    novel_id: int
    before_chapter_id: int
    title: str = ""


@router.post("/insert", response_model=ChapterOut)
async def insert_chapter(body: InsertChapterRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """在某个未确认章节前面插一个空章，后面的章节号依次 +1。"""
    await get_owned_novel(db, body.novel_id, user)
    try:
        chapter, moved = await chapter_order.insert_before(db, body.novel_id, body.before_chapter_id, body.title)
    except chapter_order.OrderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await db.commit()
    await db.refresh(chapter)
    await chapter_order.sync_vectors(body.novel_id, moved)
    return chapter


# ── 历史版本 ────────────────────────────────────────────────────────────────

@router.get("/{chapter_id}/versions")
async def list_versions(chapter_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """该章的历史版本，新的在前。不带正文，点开某一版再取。"""
    await get_owned_child(db, Chapter, chapter_id, user, "章节")
    rows = (await db.execute(
        select(ChapterVersion)
        .where(ChapterVersion.chapter_id == chapter_id)
        .order_by(ChapterVersion.created_at.desc(), ChapterVersion.id.desc())
    )).scalars().all()
    return [
        {"id": v.id, "reason": v.reason, "word_count": v.word_count, "created_at": v.created_at}
        for v in rows
    ]


async def _owned_version(db: AsyncSession, chapter_id: int, version_id: int, user) -> tuple[Chapter, ChapterVersion]:
    chapter = await get_owned_child(db, Chapter, chapter_id, user, "章节")
    version = await db.get(ChapterVersion, version_id)
    if version is None or version.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="版本不存在")
    return chapter, version


@router.get("/{chapter_id}/versions/{version_id}")
async def get_version(chapter_id: int, version_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    _, version = await _owned_version(db, chapter_id, version_id, user)
    return {
        "id": version.id, "reason": version.reason, "word_count": version.word_count,
        "created_at": version.created_at, "content": version.content,
    }


@router.post("/{chapter_id}/versions/{version_id}/restore", response_model=ChapterOut)
async def restore_version(chapter_id: int, version_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """把正文换回这一版。换之前当前正文也存一版，恢复错了还能再换回来。
    和手动编辑一样只换正文，不动确认状态和记忆。"""
    chapter, version = await _owned_version(db, chapter_id, version_id, user)
    await chapter_versions.snapshot(db, chapter, "restore")
    old_words = chapter.word_count or 0
    chapter.content = version.content
    chapter.word_count = len(version.content)
    await word_stats.record(db, chapter.novel_id, chapter.word_count - old_words)
    await db.commit()
    await db.refresh(chapter)
    return chapter


# ── 日更统计 ────────────────────────────────────────────────────────────────

@router.get("/novel/{novel_id}/word-stats")
async def get_word_stats(novel_id: int, user: CurrentUser, days: int = 30, db: AsyncSession = Depends(get_db)):
    """最近 days 天每天的全书净增字数。"""
    await get_owned_novel(db, novel_id, user)
    return await word_stats.recent(db, novel_id, days)
