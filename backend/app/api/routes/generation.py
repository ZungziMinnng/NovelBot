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
from app.schemas.generation import GenerateChapterRequest, PlotSuggestionsRequest, ReviewRequest, RewriteChapterRequest
from app.agents.orchestrator import run_chapter_generation, run_chapter_rewrite
from app.services import context_builder, llm_client

logger = logging.getLogger(__name__)

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
        async for chunk in run_chapter_rewrite(
            session=db,
            novel=novel,
            chapter_number=req.chapter_number,
            annotations=annotations,
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

    writer_system_prompt = getattr(novel, "writer_system_prompt", "") or ""
    suggestions = await generate_plot_suggestions(
        novel, chapter_content, ctx, req.chapter_number,
        writer_system_prompt=writer_system_prompt,
    )
    return {"suggestions": suggestions}


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


async def generate_plot_suggestions(
    novel: Novel, chapter_content: str, ctx: dict, chapter_number: int,
    writer_system_prompt: str = "",
) -> list[str]:
    """根据章节内容和上下文生成 4 条下一章剧情发展建议。

    被 orchestrator 并行调用（SSE 流内）和 REST 端点（手动获取）共用。
    """
    # 使用 fast 模型（轻量任务），而非 writer 模型
    model, api_format = llm_client.get_fast_client(getattr(novel, "fast_model", "") or "")

    # 组装小说元信息
    genre = ctx.get("genre") or getattr(novel, "genre", "") or ""
    writing_style = ctx.get("writing_style") or getattr(novel, "writing_style", "") or ""
    core_setting = ctx.get("core_setting") or getattr(novel, "core_setting", "") or ""

    # 组装近期剧情上下文
    context_parts = []
    if core_setting:
        context_parts.append(f"世界观设定：\n{core_setting[:600]}")
    if ctx.get("rolling_summary"):
        context_parts.append(f"近期剧情摘要：\n{ctx['rolling_summary']}")
    chars_with_state = []
    for c in ctx.get("characters", [])[:6]:
        state = c.get("state") or {}
        location = state.get("location", "")
        goal = state.get("current_goal", "")
        brief = f"{c['name']}（{c.get('role', '')}）"
        if location or goal:
            brief += f"：位于{location}" if location else ""
            brief += f"，目标：{goal}" if goal else ""
        chars_with_state.append(brief)
    if chars_with_state:
        context_parts.append("主要角色当前状态：\n" + "\n".join(chars_with_state))
    if ctx.get("chapter_outline"):
        context_parts.append(f"本章大纲：{ctx['chapter_outline']}")
    context_block = "\n\n".join(context_parts)

    # 组装小说风格标签
    style_line = ""
    if genre or writing_style:
        parts = [p for p in [genre, writing_style] if p]
        style_line = f"本作类型与风格：{'，'.join(parts)}。\n"

    chapter_tail = chapter_content[-2000:] if chapter_content else "（暂无内容）"

    task_prompt = (
        f"你是《{novel.title}》的创作者。刚写完第{chapter_number}章，现在需要构思下一章的走向。\n"
        f"{style_line}\n"
        f"{context_block}\n\n"
        f"请根据本章结尾的剧情张力和角色处境，给出4个具体的后续发展方向。\n"
        f"要求：\n"
        f"- 紧接本章结尾，不要凭空引入新人物或事件\n"
        f"- 每条是一个具体的剧情场景或事件描述，不是抽象的写作方向\n"
        f"- 4条之间风格各异：可以是激化矛盾、揭示秘密、转换场景、深入人物关系等\n"
        f"- 每条30-80字，用叙事语气描述将要发生什么\n"
        f"- 只返回JSON数组：[\"发展1\", \"发展2\", \"发展3\", \"发展4\"]\n"
        f"- 不要输出JSON以外的任何内容"
    )

    # 按 api_format 分支消息结构
    messages: list[dict] = []
    if writer_system_prompt:
        messages.append({"role": "system", "content": writer_system_prompt})

    # ⚠ 重要：Gemini 安全过滤规避措施，请勿修改此处逻辑，除非用户明确要求。
    if api_format == "gemini":
        # Gemini: 章节原文放 assistant(model) 角色，绕过 PROHIBITED_CONTENT 过滤
        messages.extend([
            {"role": "user", "content": task_prompt},
            {"role": "assistant", "content": f"好的，以下是我刚完成的第{chapter_number}章内容：\n\n{chapter_tail}"},
            {"role": "user", "content": "基于你刚写完的这章内容，构思4个不同方向的后续发展，只输出JSON数组："},
        ])
    else:
        # OpenAI / DeepSeek: 章节原文 + 任务一起放 user 消息，确保模型重视
        messages.append({
            "role": "user",
            "content": (
                f"以下是我刚完成的第{chapter_number}章内容（末尾部分）：\n\n"
                f"{chapter_tail}\n\n"
                f"---\n\n"
                f"{task_prompt}"
            ),
        })

    # 最多尝试 2 次（首次 + 1 次重试）
    for attempt in range(2):
        try:
            response = await llm_client.dispatch_chat_complete(
                messages=messages,
                model=model,
                api_format=api_format,
                temperature=0.9,
                max_tokens=800,
            )
        except Exception as e:
            logger.warning("plot_suggestions: LLM 调用失败 (attempt %d): %s", attempt + 1, e)
            continue

        if not response or not response.strip():
            logger.warning("plot_suggestions: LLM 返回空内容 (attempt %d)", attempt + 1)
            continue

        result = _parse_suggestions_json(response)
        if result:
            return result
        logger.warning("plot_suggestions: JSON 解析失败 (attempt %d)，原文: %s", attempt + 1, response.strip()[:200])

    return []


def _parse_suggestions_json(response: str) -> list[str]:
    """从 LLM 响应中提取 JSON 数组形式的剧情建议。"""
    text = response.strip()
    # 去除 markdown 代码块包裹
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text.strip())
    try:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            items = json.loads(match.group())
            result = [str(s).strip() for s in items[:4] if str(s).strip()]
            if result:
                return result
    except (json.JSONDecodeError, ValueError):
        pass
    return []
