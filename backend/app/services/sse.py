import json

from fastapi.responses import StreamingResponse

from app.services import llm_client


def sse_event(event: str, data) -> str:
    """统一的 SSE 事件编码：data 可为 str 或 dict。"""
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def stream_chat(
    messages: list[dict],
    model: str,
    api_format: str,
    temperature: float,
    max_tokens: int,
    pre_warning: str = "",
) -> StreamingResponse:
    """把一次流式补全包成 SSE 响应。事件：warning / token / done / error。

    只依赖 llm_client，不认识任何业务对象——小说侧的聊天和构思、RPG 的构思向导
    共用这一份，事件名对不上前端就得为每个入口写一套解析。
    """
    async def event_stream():
        if pre_warning:
            yield sse_event("warning", pre_warning)
        try:
            in_tok = 0
            out_tok = 0
            async for chunk in llm_client.dispatch_chat_stream_with_usage(
                messages=messages,
                model=model,
                api_format=api_format,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if isinstance(chunk, tuple):
                    _, in_tok, out_tok = chunk
                elif isinstance(chunk, dict):
                    if "warning" in chunk:
                        yield sse_event("warning", chunk["warning"])
                else:
                    yield sse_event("token", chunk)
            yield sse_event("done", {"input_tokens": in_tok, "output_tokens": out_tok})
        except Exception as e:
            yield sse_event("error", str(e))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
