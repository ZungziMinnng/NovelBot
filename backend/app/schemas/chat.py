from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str        # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    novel_id: int
    messages: list[ChatMessage]
    model: str = ""              # 留空使用全局 writer 模型
    system_prompt: str = ""      # 自定义 system prompt，空 = 使用默认
    temperature: float = 0.85
    max_tokens: int = 4096
    context_rounds: int = 0      # 对话轮次限制，0 = 使用小说默认设置
