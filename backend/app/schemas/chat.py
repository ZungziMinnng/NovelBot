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
    chapter_number: int = 0      # 编辑器当前打开的章节，0 = 回退到小说进度
    web_search: bool = False     # 开启后先联网搜一次，结果作为参考资料拼进 system prompt


class BrainstormRequest(BaseModel):
    """新建小说页的构思对话。不带表单草稿：对话单向影响表单，反过来会让 AI
    绕着已填内容说话，作者想推翻自己填的东西反而更费劲"""
    messages: list[ChatMessage]
    model: str = ""
    temperature: float = 0.9
    max_tokens: int = 4096
    context_rounds: int = 20
    nsfw: bool = False
    web_search: bool = False     # 开启后先联网搜一次，结果作为参考资料拼进 system prompt
    stage: str = ""              # 向导阶段 id，空 = 自由聊天模式
    # 向导前几步抽出来的结论，不是作者手填的表单——上面"不带表单草稿"的原则仍然成立。
    # 必须回灌是因为 context_rounds 截断后早期结论会掉出窗口，AI 会重复问已经定过的事
    confirmed: str = ""


class BrainstormExtractRequest(BaseModel):
    """把构思对话里聊定的结论抽成表单字段。model 留空用快速模型"""
    messages: list[ChatMessage]
    model: str = ""


class ExtractedCard(BaseModel):
    volume: int = 3
    text: str = ""


class ExtractedCharacter(BaseModel):
    name: str = ""
    role: str = ""
    age: str = ""
    description: str = ""


class BrainstormExtractResponse(BaseModel):
    """空串/空数组 = 对话里没聊到，前端不覆盖对应栏位"""
    title: str = ""
    genre: str = ""
    writing_style: str = ""
    premise: str = ""
    plot_design: str = ""
    core_setting: str = ""
    world_rules_seed: str = ""
    ending: str = ""
    protagonist_arc: str = ""
    endgame_cards: list[ExtractedCard] = []
    characters: list[ExtractedCharacter] = []
