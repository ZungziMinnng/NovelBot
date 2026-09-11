from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ── 角色卡 ────────────────────────────────────────────────────────────────

class ExampleTurn(BaseModel):
    user: str = ""
    assistant: str = ""


class TavernCardCreate(BaseModel):
    name: str
    linked_book_card_ids: list[int] = []
    creator_note: str = ""
    personality: str = ""
    opening_scene: str = ""
    system_instruction: str = ""
    description: str = ""
    profile_sections: dict = {}
    dialogue_examples: list[ExampleTurn] = []
    enabled_rule_ids: list[int] = []
    avatar_url: str = ""
    reply_length: int = 0
    scan_depth: int = 3
    context_turns: int = 20
    temperature: float = 0.9
    max_tokens: int = 2048
    model_ref: str = ""
    summary_model_ref: str = ""


class TavernCardUpdate(BaseModel):
    name: Optional[str] = None
    linked_book_card_ids: Optional[list[int]] = None
    creator_note: Optional[str] = None
    personality: Optional[str] = None
    opening_scene: Optional[str] = None
    system_instruction: Optional[str] = None
    description: Optional[str] = None
    profile_sections: Optional[dict] = None
    dialogue_examples: Optional[list[ExampleTurn]] = None
    enabled_rule_ids: Optional[list[int]] = None
    avatar_url: Optional[str] = None
    reply_length: Optional[int] = None
    scan_depth: Optional[int] = None
    context_turns: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    model_ref: Optional[str] = None
    summary_model_ref: Optional[str] = None


class TavernCardOut(BaseModel):
    id: int
    name: str
    linked_book_card_ids: list[int] = []
    creator_note: str
    personality: str
    opening_scene: str
    system_instruction: str
    description: str
    profile_sections: dict
    dialogue_examples: list[ExampleTurn]
    enabled_rule_ids: list[int]
    avatar_url: str
    reply_length: int
    scan_depth: int
    context_turns: int
    temperature: float
    max_tokens: int
    model_ref: str
    summary_model_ref: str
    session_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 世界书 ────────────────────────────────────────────────────────────────

class TavernWorldEntryCreate(BaseModel):
    keywords: str = ""
    content: str = ""
    enabled: bool = True
    sort_order: int = 0
    constant: bool = False
    depth: int = 0


class TavernWorldEntryUpdate(BaseModel):
    keywords: Optional[str] = None
    content: Optional[str] = None
    enabled: Optional[bool] = None
    sort_order: Optional[int] = None
    constant: Optional[bool] = None
    depth: Optional[int] = None


class TavernWorldEntryOut(BaseModel):
    id: int
    card_id: int
    keywords: str
    content: str
    enabled: bool
    sort_order: int
    constant: bool
    depth: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 会话 ──────────────────────────────────────────────────────────────────

class TavernSessionCreate(BaseModel):
    title: str = ""
    persona_name: str = ""
    persona_desc: str = ""


class TavernGroupSessionCreate(TavernSessionCreate):
    """建故事线。card_ids 首个为主卡：权限和会话级操作都认它。"""
    card_ids: list[int]


class TavernSessionUpdate(BaseModel):
    title: Optional[str] = None
    persona_name: Optional[str] = None
    persona_desc: Optional[str] = None


class TavernSessionCardOut(BaseModel):
    id: int
    name: str
    avatar_url: str


class TavernSessionOut(BaseModel):
    id: int
    card_id: int
    cards: list[TavernSessionCardOut] = []
    title: str
    persona_name: str
    persona_desc: str
    summary: str
    summarized_upto_id: int
    message_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 消息 ──────────────────────────────────────────────────────────────────

class TavernMessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    # 说话人。null = 玩家消息，或群聊之前的老数据（前端回落到主卡）
    card_id: Optional[int] = None
    content: str
    input_tokens: int
    output_tokens: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TavernMessageUpdate(BaseModel):
    content: str


# ── 常用系统指令 ──────────────────────────────────────────────────────────

class TavernInstructionPresetCreate(BaseModel):
    name: str
    content: str = ""


class TavernInstructionPresetUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None


class TavernInstructionPresetOut(BaseModel):
    id: int
    name: str
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 酒馆写作规则 ──────────────────────────────────────────────────────────

class TavernRuleCreate(BaseModel):
    name: str
    content: str = ""
    enabled: bool = True
    sort_order: int = 0


class TavernRuleUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    enabled: Optional[bool] = None
    sort_order: Optional[int] = None


class TavernRuleOut(BaseModel):
    id: int
    name: str
    content: str
    enabled: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TavernTurnRequest(BaseModel):
    content: str


class TavernSuggestOut(BaseModel):
    suggestions: list[str]


class TavernCardAssistRequest(BaseModel):
    """给角色卡某一栏做 AI 生成/优化。

    传的是前端表单里的当前文本而非 DB 里的值——新卡还没保存时也要能用，
    所以这个接口不带 card_id、不落库。
    """
    field: str
    name: str = ""
    personality: str = ""
    description: str = ""
    profile_sections: dict = {}
    opening_scene: str = ""
    model_ref: str = ""


class TavernCardAssistOut(BaseModel):
    text: str
