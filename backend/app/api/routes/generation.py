from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.novel import Novel
from app.schemas.generation import GenerateChapterRequest
from app.agents.orchestrator import run_chapter_generation

router = APIRouter()


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

    async def event_stream():
        async for chunk in run_chapter_generation(
            session=db,
            novel=novel,
            chapter_number=req.chapter_number,
            volume=req.volume,
            instruction=req.instruction,
            target_words=req.target_words,
        ):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
