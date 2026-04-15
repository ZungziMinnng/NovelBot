from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str        # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    novel_id: int
    messages: list[ChatMessage]
    model: str = ""  # 留空使用全局 writer 模型
