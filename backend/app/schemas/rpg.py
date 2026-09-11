from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ── 模组 ──────────────────────────────────────────────────────────────────

class RpgModuleCreate(BaseModel):
    name: str
    creator_note: str = ""
    genre: str = ""
    worldview: str = ""
    opening_scene: str = ""
    system_instruction: str = ""
    narration_sample: str = ""
    cover_url: str = ""
    stat_defs: list = []
    relation_stat_defs: list = []
    default_inventory: list = []
    default_location: str = ""
    rate_table: dict = {"trivial": 90, "easy": 75, "medium": 55, "hard": 35, "extreme": 15}
    difficulty_bias: int = 0
    check_mode: str = "never"
    random_check: bool = True
    scan_depth: int = 3
    context_turns: int = 20
    temperature: float = 0.9
    max_tokens: int = 2048
    reply_length: int = 300
    model_ref: str = ""
    fast_model_ref: str = ""


class RpgModuleUpdate(BaseModel):
    name: Optional[str] = None
    creator_note: Optional[str] = None
    genre: Optional[str] = None
    worldview: Optional[str] = None
    opening_scene: Optional[str] = None
    system_instruction: Optional[str] = None
    narration_sample: Optional[str] = None
    cover_url: Optional[str] = None
    stat_defs: Optional[list] = None
    relation_stat_defs: Optional[list] = None
    default_inventory: Optional[list] = None
    default_location: Optional[str] = None
    rate_table: Optional[dict] = None
    difficulty_bias: Optional[int] = None
    check_mode: Optional[str] = None
    random_check: Optional[bool] = None
    scan_depth: Optional[int] = None
    context_turns: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    reply_length: Optional[int] = None
    model_ref: Optional[str] = None
    fast_model_ref: Optional[str] = None


class RpgModuleOut(BaseModel):
    id: int
    name: str
    creator_note: str
    genre: str
    worldview: str
    opening_scene: str
    system_instruction: str
    narration_sample: str
    cover_url: str
    stat_defs: list
    relation_stat_defs: list
    default_inventory: list
    default_location: str
    rate_table: dict
    difficulty_bias: int
    check_mode: str
    random_check: bool
    scan_depth: int
    context_turns: int
    temperature: float
    max_tokens: int
    reply_length: int
    model_ref: str
    fast_model_ref: str
    session_count: int = 0
    npc_count: int = 0
    entry_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 世界书 ────────────────────────────────────────────────────────────────

class RpgWorldEntryCreate(BaseModel):
    keywords: str = ""
    content: str = ""
    enabled: bool = True
    sort_order: int = 0
    constant: bool = False
    depth: int = 0
    trigger_condition: dict = {}


class RpgWorldEntryUpdate(BaseModel):
    keywords: Optional[str] = None
    content: Optional[str] = None
    enabled: Optional[bool] = None
    sort_order: Optional[int] = None
    constant: Optional[bool] = None
    depth: Optional[int] = None
    trigger_condition: Optional[dict] = None


class RpgWorldEntryOut(BaseModel):
    id: int
    module_id: int
    keywords: str
    content: str
    enabled: bool
    sort_order: int
    constant: bool
    depth: int
    trigger_condition: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 角色卡 ────────────────────────────────────────────────────────────────

class RpgNpcCreate(BaseModel):
    name: str
    role: str = "npc"
    avatar_url: str = ""
    description: str = ""
    persona: str = ""
    appearance: str = ""
    location: str = ""
    keywords: str = ""
    profile_sections: dict = {}
    dialogue_examples: list = []
    initial_state: dict = {}
    sort_order: int = 0


class RpgNpcUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    avatar_url: Optional[str] = None
    description: Optional[str] = None
    persona: Optional[str] = None
    appearance: Optional[str] = None
    location: Optional[str] = None
    keywords: Optional[str] = None
    profile_sections: Optional[dict] = None
    dialogue_examples: Optional[list] = None
    initial_state: Optional[dict] = None
    sort_order: Optional[int] = None


class RpgNpcOut(BaseModel):
    id: int
    module_id: int
    name: str
    role: str
    avatar_url: str
    description: str
    persona: str
    appearance: str
    location: str
    keywords: str
    profile_sections: dict
    dialogue_examples: list
    initial_state: dict
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 道具 ──────────────────────────────────────────────────────────────────

class RpgItemCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "消耗品"
    usable: bool = True
    consumable: bool = True
    effects: dict = {}
    sort_order: int = 0


class RpgItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    usable: Optional[bool] = None
    consumable: Optional[bool] = None
    effects: Optional[dict] = None
    sort_order: Optional[int] = None


class RpgItemOut(BaseModel):
    id: int
    module_id: int
    name: str
    description: str
    category: str
    usable: bool
    consumable: bool
    effects: dict
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 地点 ──────────────────────────────────────────────────────────────────

class RpgLocationCreate(BaseModel):
    name: str
    description: str = ""
    connections: list = []
    enter_requires: dict = {}
    sort_order: int = 0


class RpgLocationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    connections: Optional[list] = None
    enter_requires: Optional[dict] = None
    sort_order: Optional[int] = None


class RpgLocationOut(BaseModel):
    id: int
    module_id: int
    name: str
    description: str
    connections: list
    enter_requires: dict
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 动作按钮 ──────────────────────────────────────────────────────────────

class RpgActionCreate(BaseModel):
    name: str
    prompt_hint: str = ""
    effects: dict = {}
    relation_effects: dict = {}
    requires: dict = {}
    needs_target: bool = False
    sort_order: int = 0


class RpgActionUpdate(BaseModel):
    name: Optional[str] = None
    prompt_hint: Optional[str] = None
    effects: Optional[dict] = None
    relation_effects: Optional[dict] = None
    requires: Optional[dict] = None
    needs_target: Optional[bool] = None
    sort_order: Optional[int] = None


class RpgActionOut(BaseModel):
    id: int
    module_id: int
    name: str
    prompt_hint: str
    effects: dict
    relation_effects: dict
    requires: dict
    needs_target: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 存档局 ────────────────────────────────────────────────────────────────

class RpgSessionCreate(BaseModel):
    """建局。不给的字段按模组的数值定义初始化。"""
    char_name: str
    char_desc: str = ""
    title: str = ""
    stats: Optional[dict] = None
    location: Optional[str] = None


class RpgSessionUpdate(BaseModel):
    title: Optional[str] = None


class RpgSessionOut(BaseModel):
    id: int
    module_id: int
    title: str
    status: str
    char_name: str
    char_desc: str
    stats: dict
    inventory: list
    location: str
    flags: dict
    npc_states: dict
    summary: str
    summarized_upto_id: int
    turn_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 消息与回合 ────────────────────────────────────────────────────────────

class RpgMessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    roll: Optional[dict] = None
    state_delta: Optional[dict] = None
    suggestions: Optional[list] = None
    input_tokens: int
    output_tokens: int
    aux_input_tokens: int
    aux_output_tokens: int
    created_at: datetime

    model_config = {"from_attributes": True}


class RpgTurnRequest(BaseModel):
    content: str
    # 玩家自己指定用哪项数值判定。给了就跳过裁决那次调用，零延迟零成本
    attr: str = ""
    # 「点出来的」行动。三个都空就是自由打字，走 AI 结算；给了任意一个
    # 就走引擎，数字由模组定义算死，AI 只负责写成画面
    action_id: Optional[int] = None
    item_name: str = ""
    move_to: str = ""
    target_npc: str = ""


# ── 存档 ──────────────────────────────────────────────────────────────────

class RpgSaveCreate(BaseModel):
    label: str = ""


class RpgSaveOut(BaseModel):
    id: int
    session_id: int
    kind: str
    label: str
    turn_index: int
    before_message_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
