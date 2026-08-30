"""跨数据源统一搜索 + 修正：记忆 / 摘要 / 角色 / 地点。

搜索同时走「关键词(SQL ilike + JSON 扫描)」与「语义(向量库)」，返回扁平的可编辑命中。
保存时集中处理跨表与向量库的一致性同步（章节摘要三处一致、角色/地点 re-embed）。
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.location import Location
from app.models.memory import Memory, Outline
from app.services import vector_store
from app.services.entity_embeddings import embed_character, embed_location
from app.api.deps import CurrentUser, get_owned_novel

router = APIRouter()


def _hit(source, id, field, title, context, value, match, score=None):
    return {
        "source": source,
        "id": id,
        "field": field,
        "title": title,
        "context": context,
        "value": value or "",
        "match": match,
        "score": score,
    }


def _contains(text, q_lower) -> bool:
    return bool(text) and q_lower in str(text).lower()


# ── 搜索 ─────────────────────────────────────────────────────────────────

@router.get("/novel/{novel_id}/search")
async def unified_search(
    novel_id: int,
    user: CurrentUser,
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_novel(db, novel_id, user)

    q_lower = q.lower()
    pattern = f"%{q}%"
    hits: list[dict] = []
    seen: set[tuple] = set()

    def add(hit: dict) -> bool:
        key = (hit["source"], hit["id"], hit["field"])
        if key in seen:
            return False
        seen.add(key)
        hits.append(hit)
        return True

    # 章节号 → Chapter（语义命中 chapter_summary 时反查用）
    chapters = (await db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id)
    )).scalars().all()
    chapter_by_number = {c.number: c for c in chapters}

    # ── 关键词：Character（含 JSON 子字段扫描）──
    characters = (await db.execute(
        select(Character).where(Character.novel_id == novel_id)
    )).scalars().all()
    char_by_id = {c.id: c for c in characters}
    for c in characters:
        if _contains(c.name, q_lower) or _contains(c.description, q_lower):
            add(_hit("character", c.id, "description", c.name, "角色描述", c.description, "keyword"))
        for attr, label in (("current_state", "角色状态"), ("full_sheet", "角色卡")):
            data = getattr(c, attr) or {}
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, str) and _contains(v, q_lower):
                        add(_hit("character", c.id, f"{attr}.{k}", c.name, f"{label} · {k}", v, "keyword"))

    # ── 关键词：Location（含 JSON 子字段扫描）──
    locations = (await db.execute(
        select(Location).where(Location.novel_id == novel_id)
    )).scalars().all()
    loc_by_id = {l.id: l for l in locations}
    for l in locations:
        if _contains(l.name, q_lower) or _contains(l.description, q_lower):
            add(_hit("location", l.id, "description", l.name, f"地点 · {l.type}", l.description, "keyword"))
        for attr, label in (("current_state", "地点态势"), ("properties", "地点属性")):
            data = getattr(l, attr) or {}
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, str) and _contains(v, q_lower):
                        add(_hit("location", l.id, f"{attr}.{k}", l.name, f"{label} · {k}", v, "keyword"))

    # ── 关键词：Memory（章节摘要归为 chapter 编辑目标，其余为 memory）──
    memories = (await db.execute(
        select(Memory).where(
            Memory.novel_id == novel_id,
            Memory.memory_type != "state_snapshot",
            Memory.content.ilike(pattern),
        )
    )).scalars().all()
    for m in memories:
        if m.memory_type == "chapter_summary" and m.chapter_id:
            add(_hit("chapter", m.chapter_id, "summary",
                     f"第{m.chapter_number}章摘要", "章节摘要", m.content, "keyword"))
        else:
            add(_hit("memory", m.id, "content",
                     f"第{m.chapter_number}章", f"记忆 · {m.memory_type}", m.content, "keyword"))

    # ── 关键词：Outline ──
    outlines = (await db.execute(
        select(Outline).where(
            Outline.novel_id == novel_id,
            or_(Outline.title.ilike(pattern), Outline.content.ilike(pattern)),
        )
    )).scalars().all()
    for o in outlines:
        add(_hit("outline", o.id, "content",
                 o.title or f"第{o.chapter_number}章大纲", f"大纲 · {o.level}", o.content, "keyword"))

    # ── 语义：向量库 ──
    vec_results = await vector_store.asearch_similar_with_meta(novel_id, q, top_k=10)
    for h in vec_results:
        meta = h.get("metadata") or {}
        doc_type = meta.get("type", "")
        score = round(1 - h.get("distance", 1), 3)
        if doc_type == "chapter_summary":
            ch = chapter_by_number.get(meta.get("chapter_number"))
            if ch:
                add(_hit("chapter", ch.id, "summary",
                         f"第{ch.number}章摘要", "章节摘要", ch.summary, "semantic", score))
        elif doc_type == "character":
            c = char_by_id.get(meta.get("entity_id"))
            if c:
                add(_hit("character", c.id, "description", c.name, "角色描述", c.description, "semantic", score))
        elif doc_type == "location":
            l = loc_by_id.get(meta.get("entity_id"))
            if l:
                add(_hit("location", l.id, "description", l.name, f"地点 · {l.type}", l.description, "semantic", score))

    return hits


# ── 应用修改 ─────────────────────────────────────────────────────────────

class ApplyEditRequest(BaseModel):
    source: str
    id: int
    field: str
    value: str


def _set_subfield(obj, attr: str, key: str, value: str) -> None:
    """JSON 字段需整体重新赋值，SQLAlchemy 才能检测到变更。"""
    data = dict(getattr(obj, attr) or {})
    data[key] = value
    setattr(obj, attr, data)


async def _sync_chapter_summary_db(db: AsyncSession, chapter: Chapter, value: str) -> None:
    """章节摘要数据库两处同步：Chapter.summary + Memory 行。
    向量同步放事务提交之后（_sync_summary_vector），避免嵌入网络调用期间抱着 SQLite 写锁。"""
    chapter.summary = value
    mem = (await db.execute(
        select(Memory).where(
            Memory.chapter_id == chapter.id,
            Memory.memory_type == "chapter_summary",
        )
    )).scalars().first()
    if mem:
        mem.content = value


async def _sync_summary_vector(chapter: Chapter, value: str) -> None:
    # 向量写入失败不应让摘要修正落库失败（与摘要/实体同步策略一致）。
    # 典型失败：集合维度与当前嵌入模型不一致（需用「重建向量库」修复）。
    try:
        await vector_store.astore_text(
            novel_id=chapter.novel_id,
            doc_id=f"chapter_{chapter.id}_summary",
            text=value,
            metadata={
                "type": "chapter_summary",
                "volume": chapter.volume,
                "chapter_number": chapter.number,
            },
        )
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "摘要修正向量同步失败（文本已保存，可重建向量库修复）: novel=%s chapter=%s",
            chapter.novel_id, chapter.id, exc_info=True,
        )


@router.post("/novel/{novel_id}/apply")
async def apply_edit(novel_id: int, req: ApplyEditRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    # WAL 模式下若本事务的读快照期间有其他连接提交（如后台生成），写升级会立即
    # 报 database is locked 且不等待 busy_timeout；回滚拿新快照重试即可。
    for attempt in range(3):
        try:
            return await _apply_edit_once(novel_id, req, db)
        except OperationalError as e:
            await db.rollback()
            if "database is locked" not in str(e).lower() or attempt == 2:
                raise
            await asyncio.sleep(0.3 * (attempt + 1))


async def _apply_edit_once(novel_id: int, req: ApplyEditRequest, db: AsyncSession):
    source, field, value = req.source, req.field, req.value

    if source == "character":
        char = await db.get(Character, req.id)
        if not char or char.novel_id != novel_id:
            raise HTTPException(status_code=404, detail="角色不存在")
        if field == "description":
            char.description = value
        elif "." in field:
            attr, key = field.split(".", 1)
            if attr not in ("current_state", "full_sheet"):
                raise HTTPException(status_code=400, detail=f"不支持的字段: {field}")
            _set_subfield(char, attr, key, value)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的字段: {field}")
        await db.commit()
        await db.refresh(char)
        await embed_character(novel_id, char)

    elif source == "location":
        loc = await db.get(Location, req.id)
        if not loc or loc.novel_id != novel_id:
            raise HTTPException(status_code=404, detail="地点不存在")
        if field == "description":
            loc.description = value
        elif "." in field:
            attr, key = field.split(".", 1)
            if attr not in ("current_state", "properties"):
                raise HTTPException(status_code=400, detail=f"不支持的字段: {field}")
            _set_subfield(loc, attr, key, value)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的字段: {field}")
        await db.commit()
        await db.refresh(loc)
        await embed_location(novel_id, loc)

    elif source == "chapter":
        chapter = await db.get(Chapter, req.id)
        if not chapter or chapter.novel_id != novel_id:
            raise HTTPException(status_code=404, detail="章节不存在")
        await _sync_chapter_summary_db(db, chapter, value)
        await db.commit()
        await _sync_summary_vector(chapter, value)

    elif source == "memory":
        mem = await db.get(Memory, req.id)
        if not mem or mem.novel_id != novel_id:
            raise HTTPException(status_code=404, detail="记忆条目不存在")
        mem.content = value
        synced_chapter = None
        if mem.memory_type == "chapter_summary" and mem.chapter_id:
            synced_chapter = await db.get(Chapter, mem.chapter_id)
            if synced_chapter:
                await _sync_chapter_summary_db(db, synced_chapter, value)
        await db.commit()
        if synced_chapter:
            await _sync_summary_vector(synced_chapter, value)

    elif source == "outline":
        outline = await db.get(Outline, req.id)
        if not outline or outline.novel_id != novel_id:
            raise HTTPException(status_code=404, detail="大纲条目不存在")
        outline.content = value
        await db.commit()

    else:
        raise HTTPException(status_code=400, detail=f"不支持的数据源: {source}")

    return {"source": source, "id": req.id, "field": field, "value": value, "ok": True}
