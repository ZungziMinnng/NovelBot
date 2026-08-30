"""投稿相关接口：稿件导出、敏感词预检。

单独成模块而不是塞进 novels.py（已 1090 行）。
"""
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, get_owned_novel
from app.database import get_db
from app.models.chapter import Chapter
from app.models.sensitive_word import SensitiveWord
from app.services import exporter, sensitive_check

logger = logging.getLogger(__name__)
router = APIRouter()


async def _load_chapters(db: AsyncSession, novel_id: int, scope: str) -> list[Chapter]:
    stmt = select(Chapter).where(Chapter.novel_id == novel_id)
    if scope == "confirmed":
        stmt = stmt.where(Chapter.status == "confirmed")
    result = await db.execute(stmt.order_by(Chapter.number))
    return [c for c in result.scalars().all() if (c.content or "").strip()]


def _attachment_headers(filename: str) -> dict[str, str]:
    """中文文件名必须走 RFC 5987 的 filename*，否则浏览器存下来是乱码。"""
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}


@router.get("/novel/{novel_id}/export")
async def export_novel(
    novel_id: int,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    scope: str = Query("confirmed", pattern="^(confirmed|all)$"),
    split: str = Query("single", pattern="^(single|per_chapter)$"),
):
    """导出稿件。scope=confirmed 只导已确认章节，all 含草稿；split=per_chapter 出 zip。"""
    novel = await get_owned_novel(db, novel_id, user)
    chapters = await _load_chapters(db, novel_id, scope)
    base = exporter.safe_filename(novel.title)
    logger.info("导出小说 %s（%s 章，scope=%s, split=%s）", novel_id, len(chapters), scope, split)

    if split == "per_chapter":
        payload = exporter.build_chapter_zip(novel, chapters)
        return Response(payload, media_type="application/zip",
                        headers=_attachment_headers(f"{base}.zip"))

    text = exporter.build_single_txt(novel, chapters)
    # 带 BOM：Windows 记事本打开 UTF-8 无 BOM 的中文 txt 仍可能乱码
    return Response(text.encode("utf-8-sig"), media_type="text/plain; charset=utf-8",
                    headers=_attachment_headers(f"{base}.txt"))


# ── 敏感词预检 ──────────────────────────────────────────────────────────────
# 全程手动触发、类别默认全不勾。写 NSFW 内容时不勾"色情露骨"即可，
# 这套检查不参与生成、不改正文、不进提示词。


class _ScanBody(BaseModel):
    categories: list[str] = Field(default_factory=list)
    scope: str = "all"
    include_custom: bool = True


@router.get("/sensitive-words")
async def list_sensitive_words(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """返回基线类别（含各类词数）和用户自定义词。"""
    result = await db.execute(
        select(SensitiveWord).where(SensitiveWord.user_id == user.id).order_by(SensitiveWord.id.desc())
    )
    custom = [{"id": w.id, "word": w.word, "note": w.note} for w in result.scalars().all()]
    return {"categories": sensitive_check.category_meta(), "custom": custom}


class _WordsBody(BaseModel):
    # 支持整段粘贴：平台清单通常是一大段，逐条加太费手
    text: str = ""
    note: str = ""


@router.post("/sensitive-words")
async def add_sensitive_words(body: _WordsBody, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """批量添加自定义词，按换行/逗号/空格切分，已存在的跳过。"""
    import re
    incoming = {w.strip() for w in re.split(r"[,，、;；\s\n]+", body.text) if w.strip()}
    if not incoming:
        return {"added": 0}
    existing = await db.execute(select(SensitiveWord.word).where(SensitiveWord.user_id == user.id))
    known = set(existing.scalars().all())
    fresh = [w for w in incoming if w not in known]
    for word in fresh:
        db.add(SensitiveWord(user_id=user.id, word=word[:100], note=body.note[:200]))
    await db.commit()
    return {"added": len(fresh)}


@router.delete("/sensitive-words/{word_id}")
async def delete_sensitive_word(word_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    word = await db.get(SensitiveWord, word_id)
    if word is None or word.user_id != user.id:
        raise HTTPException(status_code=404, detail="词条不存在")
    await db.delete(word)
    await db.commit()
    return {"ok": True}


@router.post("/novel/{novel_id}/sensitive-scan")
async def scan_novel(
    novel_id: int,
    body: _ScanBody,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """按勾选类别扫描全书。不勾任何类别且没有自定义词时直接返回空结果。"""
    await get_owned_novel(db, novel_id, user)

    custom_words: list[str] = []
    if body.include_custom:
        result = await db.execute(select(SensitiveWord.word).where(SensitiveWord.user_id == user.id))
        custom_words = list(result.scalars().all())

    wordlist = sensitive_check.build_wordlist(body.categories, custom_words)
    if not wordlist:
        return {"scanned_chapters": 0, "total_hits": 0, "word_count": 0, "chapters": []}

    chapters = await _load_chapters(db, novel_id, body.scope)
    report = []
    total = 0
    for ch in chapters:
        hits = sensitive_check.scan_text(exporter.clean_body(ch), wordlist)
        if hits:
            total += len(hits)
            report.append({
                "chapter_id": ch.id,
                "number": ch.number,
                "title": ch.title,
                "hits": hits,
            })
    logger.info("敏感词预检 novel=%s 章节=%s 命中=%s", novel_id, len(chapters), total)
    return {
        "scanned_chapters": len(chapters),
        "total_hits": total,
        "word_count": len(wordlist),
        "chapters": report,
    }
