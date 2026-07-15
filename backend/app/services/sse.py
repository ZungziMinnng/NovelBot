import json


def sse_event(event: str, data) -> str:
    """统一的 SSE 事件编码：data 可为 str 或 dict。"""
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"
