import asyncio
import json
import logging
import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db, AsyncSessionLocal
from app.models.chapter import Chapter
from app.models.novel import Novel
from app.schemas.generation import GenerateChapterRequest, ReviewRequest, RewriteChapterRequest
from app.agents.orchestrator import run_chapter_generation, run_chapter_rewrite
from app.services import context_builder, llm_client
from app.api.deps import CurrentUser, get_owned_novel

logger = logging.getLogger(__name__)

router = APIRouter()

# 非流式 Gemini 写作时，单次阻塞调用可静默数十秒不发任何字节，
# 中间代理（如 Vite dev proxy）会把空闲连接判定为结束并断流。
# 在静默期定期发送 SSE 注释行 `: ping`（前端 `data:` 解析与 EventSource 均忽略）保活。
_HEARTBEAT_INTERVAL = 15.0


_HEARTBEAT_DONE = object()


async def _with_heartbeat(agen):
    """包裹 SSE 异步生成器：静默超过 _HEARTBEAT_INTERVAL 秒时插入 keepalive 注释行。

    关键：用单个 producer 任务完整驱动 agen，chunk 经 Queue 传出。这样 agen 内部
    （含 AsyncSession 的全部 DB IO）始终在同一个 asyncio 任务里运行——绝不能像旧实现
    那样对每次 __anext__ 都 ensure_future 成新任务，否则 AsyncSession 会跨任务复用连接，
    触发 SQLAlchemy 的 `greenlet_spawn has not been called` 错误。"""
    queue: asyncio.Queue = asyncio.Queue()

    async def _producer():
        try:
            async for item in agen:
                await queue.put(("item", item))
        except Exception as e:  # 由 consumer 重抛，保留原始堆栈
            await queue.put(("error", e))
        finally:
            await queue.put(("done", _HEARTBEAT_DONE))

    task = asyncio.ensure_future(_producer())
    try:
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if kind == "item":
                yield payload
            elif kind == "error":
                raise payload
            else:
                break
    finally:
        if not task.done():
            task.cancel()
        try:
            await task  # 让 producer 的 finally（含 session 关闭）在其自身任务内跑完
        except (asyncio.CancelledError, Exception):
            pass


@router.post("/chapter")
async def generate_chapter(
    req: GenerateChapterRequest,
    user: CurrentUser,
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
    # 所有权校验用请求级 db（端点返回前完成）；SSE 流内另开独立会话，
    # 避免长流式期间客户端断开/协程取消导致请求级连接悬空（GC 警告 + 误 ROLLBACK）。
    await get_owned_novel(db, req.novel_id, user)

    async def _run():
        # session 的创建与全部 DB IO 都在 _with_heartbeat 的 producer 任务内，
        # 保证同一个 AsyncSession 不跨任务复用（否则触发 greenlet 错误）。
        async with AsyncSessionLocal() as gen_db:
            novel = await gen_db.get(Novel, req.novel_id)
            async for chunk in run_chapter_generation(
                session=gen_db,
                novel=novel,
                chapter_number=req.chapter_number,
                volume=req.volume,
                instruction=req.instruction,
                target_words=req.target_words,
                pov=req.pov or "",
            ):
                yield chunk

    return StreamingResponse(
        _with_heartbeat(_run()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/rewrite-chapter")
async def rewrite_chapter(
    req: RewriteChapterRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await get_owned_novel(db, req.novel_id, user)

    annotations = [a.model_dump() for a in req.annotations]

    async def _run():
        async with AsyncSessionLocal() as gen_db:
            novel = await gen_db.get(Novel, req.novel_id)
            async for chunk in run_chapter_rewrite(
                session=gen_db,
                novel=novel,
                chapter_number=req.chapter_number,
                annotations=annotations,
                target_words=req.target_words,
                rewrite_model=req.rewrite_model,
                pov=req.pov or "",
            ):
                yield chunk

    return StreamingResponse(
        _with_heartbeat(_run()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/review")
async def fulltext_review(
    req: ReviewRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    novel = await get_owned_novel(db, req.novel_id, user)

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


