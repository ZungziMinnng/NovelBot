import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.novel import Novel
from app.schemas.chat import ChatRequest
from app.services import context_builder, llm_client

router = APIRouter()


def _sse(event: str, data) -> str:
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def _build_chat_system_prompt(ctx: dict) -> str:
    """将小说上下文组装成对话模式的 system prompt"""
    parts = [
        f"你是《{ctx.get('novel_title', '')}》的创作助手。"
        f"请基于以下小说设定回答用户的问题，提供专业的写作建议。"
    ]
    if ctx.get("core_setting"):
        parts.append(f"=== 世界观设定 ===\n{ctx['core_setting']}")
    if ctx.get("characters"):
        chars_text = ""
        for c in ctx["characters"]:
            state = c.get("state", {})
            chars_text += f"【{c['name']}·{c['role']}】{c['description']}\n"
            if state:
                chars_text += f"  当前状态：{json.dumps(state, ensure_ascii=False)}\n"
        parts.append(f"=== 角色状态 ===\n{chars_text.strip()}")
    if ctx.get("rolling_summary"):
        parts.append(f"=== 近期剧情摘要 ===\n{ctx['rolling_summary']}")
    return "\n\n".join(parts)


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    SSE 流式接口：编辑器对话模式。

    事件类型：
      token  → 逐 token 输出
      done   → 完成，data 为 {input_tokens, output_tokens}
      error  → 错误信息
    """
    novel = await db.get(Novel, req.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    await db.refresh(novel)

    # 构建小说上下文
    ctx = await context_builder.build_generation_context(
        session=db,
        novel=novel,
        chapter_number=novel.current_chapter or 1,
        volume=novel.current_volume or 1,
    )
    system_prompt = _build_chat_system_prompt(ctx)

    # 应用消息轮次限制（1轮 = user+assistant 各1条 = 2条消息）
    chat_rounds = novel.chat_context_rounds
    if chat_rounds and chat_rounds > 0:
        max_messages = chat_rounds * 2
        trimmed = req.messages[-max_messages:]
    else:
        trimmed = req.messages

    # 组装 messages（prepend system message）
    messages = [{"role": "system", "content": system_prompt}]
    for m in trimmed:
        messages.append({"role": m.role, "content": m.content})

    # 解析模型
    model, api_format = llm_client.get_agent_client("writer", req.model)

    async def event_stream():
        try:
            in_tok = 0
            out_tok = 0
            async for chunk in llm_client.dispatch_chat_stream_with_usage(
                messages=messages,
                model=model,
                api_format=api_format,
            ):
                if isinstance(chunk, tuple):
                    in_tok, out_tok = chunk
                else:
                    yield _sse("token", chunk)
            yield _sse("done", {"input_tokens": in_tok, "output_tokens": out_tok})
        except Exception as e:
            yield _sse("error", str(e))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
