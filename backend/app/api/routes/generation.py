import json
import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.schemas.generation import GenerateChapterRequest, PlotSuggestionsRequest
from app.agents.orchestrator import run_chapter_generation
from app.services import context_builder, llm_client

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
    await db.refresh(novel)

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


@router.post("/plot-suggestions")
async def get_plot_suggestions(
    req: PlotSuggestionsRequest,
    db: AsyncSession = Depends(get_db),
):
    """根据已生成章节内容，返回4个下一章剧情发展建议"""
    novel = await db.get(Novel, req.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    await db.refresh(novel)

    result = await db.execute(
        select(Chapter).where(
            Chapter.novel_id == req.novel_id,
            Chapter.number == req.chapter_number,
            Chapter.volume == req.volume,
        )
    )
    chapter = result.scalar_one_or_none()
    chapter_content = chapter.content if chapter else ""

    ctx = await context_builder.build_generation_context(
        session=db,
        novel=novel,
        chapter_number=req.chapter_number,
        volume=req.volume,
    )

    suggestions = await _generate_plot_suggestions(novel, chapter_content, ctx, req.chapter_number)
    return {"suggestions": suggestions}


async def _generate_plot_suggestions(
    novel: Novel, chapter_content: str, ctx: dict, chapter_number: int
) -> list[str]:
    model, api_format = llm_client.get_agent_client("writer", getattr(novel, "fast_model", "") or "")
    chars_summary = "、".join([c["name"] for c in ctx.get("characters", [])[:6]])
    setting_snippet = (ctx.get("core_setting") or "")[:300]

    prompt = (
        f"你是资深小说编辑。请为《{novel.title}》第{chapter_number}章之后提供4个不同方向的下一章写作指令建议。\n\n"
        f"世界观：{setting_snippet}\n"
        f"主要角色：{chars_summary}\n\n"
        f"本章末尾（参考）：\n{chapter_content[-600:] if chapter_content else '（暂无内容）'}\n\n"
        f"要求：\n"
        f"- 4个建议方向各不相同（如：冲突升级、人物转折、悬念铺设、情感深化等）\n"
        f"- 每条20-50字，语气直接，作为写作指令使用\n"
        f"- 只返回JSON数组格式：[\"建议1\", \"建议2\", \"建议3\", \"建议4\"]\n"
        f"- 不要输出JSON以外的任何内容"
    )

    response = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.9,
        max_tokens=500,
    )

    try:
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            items = json.loads(match.group())
            return [str(s).strip() for s in items[:4] if str(s).strip()]
    except Exception:
        pass
    return []
