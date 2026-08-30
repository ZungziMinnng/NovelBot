"""全书批量替换：纯文本查找替换，覆盖章节正文/摘要/大纲/记忆。

安全策略：预览确认 → 写库前把每个被改行的完整原文存进 TextReplaceBackup → 可一键撤销。
撤销靠存原文而非反向替换：若原文本来就含有 replace_text，反向替换会连带改坏原有的词。
"""
import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.chapter import Chapter
from app.models.memory import Memory, Outline
from app.models.text_replace_backup import TextReplaceBackup
from app.api.deps import CurrentUser, get_owned_novel
from app.api.routes.corrections import _sync_summary_vector

router = APIRouter()
logger = logging.getLogger(__name__)

ROW_LIMIT = 200        # 预览最多回多少行，防改名命中上万处时响应爆掉
SNIPPET_LIMIT = 3      # 每行最多几条抽样片段
SNIPPET_PAD = 20       # 片段上下文各留多少字
BACKUP_KEEP = 10       # 每本书保留最近几条备份

SCOPES = ("content", "summary", "outline", "memory")


def count_occurrences(text: str, find: str) -> int:
    """不重叠计数，与 str.replace 的替换次数口径一致。"""
    if not text or not find:
        return 0
    return text.count(find)


def extract_snippets(
    text: str,
    find: str,
    limit: int = SNIPPET_LIMIT,
    pad: int = SNIPPET_PAD,
) -> list[str]:
    """取命中处前后 pad 字的上下文片段，供预览抽样核对。"""
    if not text or not find:
        return []
    snippets: list[str] = []
    start = 0
    while len(snippets) < limit:
        idx = text.find(find, start)
        if idx == -1:
            break
        left = max(0, idx - pad)
        right = min(len(text), idx + len(find) + pad)
        snippets.append(text[left:right].replace("\n", " ").strip())
        start = idx + len(find)
    return snippets


class Target(BaseModel):
    """一个可替换的文本位置。obj 为 ORM 实例，写入时直接 setattr。"""

    table: str
    row_id: int
    field: str
    label: str
    text: str

    model_config = {"arbitrary_types_allowed": True}


async def _collect_targets(
    db: AsyncSession, novel_id: int, scope: list[str]
) -> list[tuple[Target, object]]:
    """按 scope 汇总全书所有待扫描文本位置，返回 (Target, ORM 实例)。

    摘要归 Chapter.summary 独占：Memory 的 chapter_summary 行被跳过，
    否则同一段摘要会被计两次；写入时由 _mirror_summary_to_memory 保持两处一致。
    """
    out: list[tuple[Target, object]] = []

    if "content" in scope or "summary" in scope:
        chapters = (await db.execute(
            select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.number)
        )).scalars().all()
        for c in chapters:
            if "content" in scope and c.content:
                out.append((Target(
                    table="chapters", row_id=c.id, field="content",
                    label=f"第{c.number}章正文", text=c.content,
                ), c))
            if "summary" in scope and c.summary:
                out.append((Target(
                    table="chapters", row_id=c.id, field="summary",
                    label=f"第{c.number}章摘要", text=c.summary,
                ), c))

    if "outline" in scope:
        outlines = (await db.execute(
            select(Outline).where(Outline.novel_id == novel_id).order_by(Outline.id)
        )).scalars().all()
        for o in outlines:
            if o.content:
                title = o.title or f"第{o.chapter_number}章"
                out.append((Target(
                    table="outlines", row_id=o.id, field="content",
                    label=f"大纲 · {title}", text=o.content,
                ), o))

    if "memory" in scope:
        memories = (await db.execute(
            select(Memory).where(
                Memory.novel_id == novel_id,
                Memory.memory_type != "chapter_summary",
            ).order_by(Memory.id)
        )).scalars().all()
        for m in memories:
            if m.content:
                out.append((Target(
                    table="memories", row_id=m.id, field="content",
                    label=f"记忆 · {m.memory_type} · 第{m.chapter_number}章", text=m.content,
                ), m))

    return out


def _normalize_scope(scope: list[str] | None) -> list[str]:
    picked = [s for s in (scope or list(SCOPES)) if s in SCOPES]
    if not picked:
        raise HTTPException(status_code=400, detail="替换范围不能为空")
    return picked


# ── 预览 ─────────────────────────────────────────────────────────────────

@router.get("/novel/{novel_id}/preview")
async def preview_replace(
    novel_id: int,
    user: CurrentUser,
    find: str = Query(..., min_length=1, max_length=200),
    scope: list[str] = Query(default=list(SCOPES)),
    db: AsyncSession = Depends(get_db),
):
    """扫描命中，不写库。行数与片段都有上限，避免改名类高频词把响应撑爆。"""
    await get_owned_novel(db, novel_id, user)
    picked = _normalize_scope(scope)

    total = 0
    affected = 0
    rows: list[dict] = []
    for target, _obj in await _collect_targets(db, novel_id, picked):
        n = count_occurrences(target.text, find)
        if not n:
            continue
        total += n
        affected += 1
        if len(rows) < ROW_LIMIT:
            rows.append({
                "table": target.table,
                "row_id": target.row_id,
                "field": target.field,
                "label": target.label,
                "count": n,
                "snippets": extract_snippets(target.text, find),
            })

    return {
        "find": find,
        "scope": picked,
        "total_occurrences": total,
        "affected_rows": affected,
        "rows": rows,
        "truncated": affected > len(rows),
    }


# ── 执行替换 ─────────────────────────────────────────────────────────────

class ApplyReplaceRequest(BaseModel):
    find: str = Field(..., min_length=1, max_length=200)
    replace: str = Field(default="", max_length=200)
    scope: list[str] = Field(default_factory=lambda: list(SCOPES))


async def _mirror_summary_to_memory(
    db: AsyncSession, chapter_id: int, value: str
) -> None:
    """摘要在 Chapter.summary 与 Memory 行两处各存一份，写一处必须同步另一处。"""
    mem = (await db.execute(
        select(Memory).where(
            Memory.chapter_id == chapter_id,
            Memory.memory_type == "chapter_summary",
        )
    )).scalars().first()
    if mem:
        mem.content = value


async def _retry_on_lock(fn, *args):
    """WAL 下写升级若遇他连接已提交会立即报 locked 而不等 busy_timeout，
    回滚拿新快照重试即可（与 corrections.apply_edit 一致）。"""
    db: AsyncSession = args[-1]
    for attempt in range(3):
        try:
            return await fn(*args)
        except OperationalError as e:
            await db.rollback()
            if "database is locked" not in str(e).lower() or attempt == 2:
                raise
            await asyncio.sleep(0.3 * (attempt + 1))


@router.post("/novel/{novel_id}/apply")
async def apply_replace(
    novel_id: int,
    req: ApplyReplaceRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await get_owned_novel(db, novel_id, user)
    if req.find == req.replace:
        raise HTTPException(status_code=400, detail="查找与替换内容相同")
    result = await _retry_on_lock(_apply_once, novel_id, req, db)
    # 向量重建放提交之后：嵌入是网络调用，不能抱着 SQLite 写锁做
    await _rebuild_summary_vectors(db, result.pop("_summary_chapter_ids", []))
    return result


async def _apply_once(novel_id: int, req: ApplyReplaceRequest, db: AsyncSession) -> dict:
    picked = _normalize_scope(req.scope)
    find, replace = req.find, req.replace

    payload: list[dict] = []
    total = 0
    summary_chapter_ids: list[int] = []

    for target, obj in await _collect_targets(db, novel_id, picked):
        n = count_occurrences(target.text, find)
        if not n:
            continue
        total += n
        payload.append({
            "table": target.table,
            "row_id": target.row_id,
            "field": target.field,
            "before": target.text,
        })
        new_text = target.text.replace(find, replace)
        setattr(obj, target.field, new_text)
        if target.table == "chapters" and target.field == "content":
            obj.word_count = len(new_text)
        if target.table == "chapters" and target.field == "summary":
            await _mirror_summary_to_memory(db, target.row_id, new_text)
            summary_chapter_ids.append(target.row_id)

    if not payload:
        raise HTTPException(status_code=404, detail=f"未找到「{find}」，未做任何修改")

    backup = TextReplaceBackup(
        novel_id=novel_id,
        find_text=find,
        replace_text=replace,
        scope=picked,
        payload=payload,
        affected_rows=len(payload),
        total_occurrences=total,
    )
    db.add(backup)
    await _prune_backups(db, novel_id)
    await db.commit()
    await db.refresh(backup)

    return {
        "ok": True,
        "backup_id": backup.id,
        "affected_rows": len(payload),
        "total_occurrences": total,
        "_summary_chapter_ids": summary_chapter_ids,
    }


async def _prune_backups(db: AsyncSession, novel_id: int) -> None:
    """只留最近 BACKUP_KEEP 条：payload 存全文，无上限会把库撑大。"""
    stale = (await db.execute(
        select(TextReplaceBackup)
        .where(TextReplaceBackup.novel_id == novel_id)
        .order_by(TextReplaceBackup.id.desc())
        .offset(BACKUP_KEEP - 1)
    )).scalars().all()
    for row in stale:
        await db.delete(row)


async def _rebuild_summary_vectors(db: AsyncSession, chapter_ids: list[int]) -> None:
    """并发重建受影响摘要的向量。失败只记日志——文本已落库，用户可用「重建向量库」兜底。"""
    if not chapter_ids:
        return
    chapters = (await db.execute(
        select(Chapter).where(Chapter.id.in_(chapter_ids))
    )).scalars().all()
    sem = asyncio.Semaphore(4)

    async def one(ch: Chapter):
        async with sem:
            await _sync_summary_vector(ch, ch.summary)

    results = await asyncio.gather(*(one(c) for c in chapters), return_exceptions=True)
    failed = sum(1 for r in results if isinstance(r, Exception))
    if failed:
        logger.warning("批量替换后 %s/%s 条摘要向量重建失败", failed, len(chapters))


# ── 撤销 ─────────────────────────────────────────────────────────────────

_UNDO_MODELS = {"chapters": Chapter, "outlines": Outline, "memories": Memory}


@router.post("/novel/{novel_id}/undo/{backup_id}")
async def undo_replace(
    novel_id: int,
    backup_id: int,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await get_owned_novel(db, novel_id, user)
    result = await _retry_on_lock(_undo_once, novel_id, backup_id, db)
    await _rebuild_summary_vectors(db, result.pop("_summary_chapter_ids", []))
    return result


async def _undo_once(novel_id: int, backup_id: int, db: AsyncSession) -> dict:
    backup = await db.get(TextReplaceBackup, backup_id)
    if not backup or backup.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="备份不存在")
    if backup.undone_at:
        raise HTTPException(status_code=400, detail="该次替换已撤销过")

    restored = 0
    missing = 0
    summary_chapter_ids: list[int] = []
    for item in backup.payload or []:
        model = _UNDO_MODELS.get(item.get("table"))
        if model is None:
            continue
        obj = await db.get(model, item["row_id"])
        # 行可能已被删除（如删章），跳过而不是整体失败
        if obj is None or getattr(obj, "novel_id", None) != novel_id:
            missing += 1
            continue
        before = item["before"]
        setattr(obj, item["field"], before)
        if item["table"] == "chapters" and item["field"] == "content":
            obj.word_count = len(before)
        if item["table"] == "chapters" and item["field"] == "summary":
            await _mirror_summary_to_memory(db, item["row_id"], before)
            summary_chapter_ids.append(item["row_id"])
        restored += 1

    backup.undone_at = datetime.utcnow()
    await db.commit()

    return {
        "ok": True,
        "restored_rows": restored,
        "missing_rows": missing,
        "_summary_chapter_ids": summary_chapter_ids,
    }


@router.get("/novel/{novel_id}/backups")
async def list_backups(
    novel_id: int,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """最近的替换操作。不回 payload（含全文，体量大）。"""
    await get_owned_novel(db, novel_id, user)
    rows = (await db.execute(
        select(TextReplaceBackup)
        .where(TextReplaceBackup.novel_id == novel_id)
        .order_by(TextReplaceBackup.id.desc())
    )).scalars().all()
    return [
        {
            "id": b.id,
            "find_text": b.find_text,
            "replace_text": b.replace_text,
            "scope": b.scope,
            "affected_rows": b.affected_rows,
            "total_occurrences": b.total_occurrences,
            "created_at": b.created_at,
            "undone_at": b.undone_at,
        }
        for b in rows
    ]
