import asyncio
import json
import logging
import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.schemas.generation import GenerateChapterRequest, ReviewRequest, RewriteChapterRequest
from app.agents.orchestrator import run_chapter_generation, run_chapter_rewrite
from app.services import context_builder, llm_client

logger = logging.getLogger(__name__)

router = APIRouter()

# 非流式 Gemini 写作时，单次阻塞调用可静默数十秒不发任何字节，
# 中间代理（如 Vite dev proxy）会把空闲连接判定为结束并断流。
# 在静默期定期发送 SSE 注释行 `: ping`（前端 `data:` 解析与 EventSource 均忽略）保活。
_HEARTBEAT_INTERVAL = 15.0


async def _with_heartbeat(agen):
    """包裹 SSE 异步生成器：静默超过 _HEARTBEAT_INTERVAL 秒时插入 keepalive 注释行。
    注意：超时只是再次等待同一个 __anext__ 任务，绝不取消它，避免把 CancelledError
    抛进 orchestrator 导致误 ROLLBACK。"""
    nxt = asyncio.ensure_future(agen.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({nxt}, timeout=_HEARTBEAT_INTERVAL)
            if not done:
                yield ": ping\n\n"
                continue
            try:
                chunk = nxt.result()
            except StopAsyncIteration:
                break
            yield chunk
            nxt = asyncio.ensure_future(agen.__anext__())
    finally:
        if not nxt.done():
            nxt.cancel()


@router.post("/chapter")
async def generate_chapter(
    req: GenerateChapterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    SSE 流式接口：生成章节内容。

    前端使用 EventSource 或 fetch + ReadableStream 消费。
    事件格式：data: {"event": "...", "data": "..."}

    事件类型：
      stage   → 当前阶段描述
      token   → Writer 输出的单个 token
      done    → 完成，data 为章节 ID
      error   → 错误信息
    """
    novel = await db.get(Novel, req.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    await db.refresh(novel)

    async def event_stream():
        async for chunk in _with_heartbeat(run_chapter_generation(
            session=db,
            novel=novel,
            chapter_number=req.chapter_number,
            volume=req.volume,
            instruction=req.instruction,
            target_words=req.target_words,
            pov=req.pov or "",
        )):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/rewrite-chapter")
async def rewrite_chapter(
    req: RewriteChapterRequest,
    db: AsyncSession = Depends(get_db),
):
    novel = await db.get(Novel, req.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    await db.refresh(novel)

    annotations = [a.model_dump() for a in req.annotations]

    async def event_stream():
        async for chunk in _with_heartbeat(run_chapter_rewrite(
            session=db,
            novel=novel,
            chapter_number=req.chapter_number,
            annotations=annotations,
            target_words=req.target_words,
            rewrite_model=req.rewrite_model,
            pov=req.pov or "",
        )):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/review")
async def fulltext_review(
    req: ReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    novel = await db.get(Novel, req.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    from app.agents import review_agent
    confirmed = await db.execute(
        select(Chapter).where(
            Chapter.novel_id == req.novel_id,
            Chapter.content != "",
        )
    )
    chapters = confirmed.scalars().all()
    if not chapters:
        raise HTTPException(status_code=400, detail="没有有内容的章节可供审查")

    issues, in_tok, out_tok, model = await review_agent.run_fulltext_review(db, novel)
    total_words = sum(ch.word_count or 0 for ch in chapters)
    return {
        "issues": issues,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "model": model,
        "chapter_count": len(chapters),
        "word_count": total_words,
    }


