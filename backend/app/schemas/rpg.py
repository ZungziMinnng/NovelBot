from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel


# 玩法类别。写进来的必须是这三个之一（拼错直接 422，不要等到玩的时候才发现
# 玩法规则没注入）；但**读出去的是裸 str**——老库里可能留着空串，
# 用 Literal 校验响应会让一个正常的模组直接打不开
PlayStyle = Literal["sim", "rpg", "slg"]


# ── 模组 ──────────────────────────────────────────────────────────────────

class RpgModuleCreate(BaseModel):
    name: str
    creator_note: str = ""
    genre: str = ""
    play_style: PlayStyle = "rpg"
    worldview: str = ""
    opening_scene: str = ""
    system_instruction: str = ""
    enabled_rule_ids: list[int] = []
    narration_sample: str = ""
    cover_url: str = ""
    stat_defs: list = []
    relation_stat_defs: list = []
    default_inventory: list = []
    default_location: str = ""
    time_slots: list = []
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
    summary_model_ref: str = ""
    offscreen_brief: bool = False


class RpgModuleUpdate(BaseModel):
    name: Optional[str] = None
    creator_note: Optional[str] = None
    genre: Optional[str] = None
    play_style: Optional[PlayStyle] = None
    worldview: Optional[str] = None
    opening_scene: Optional[str] = None
    system_instruction: Optional[str] = None
    enabled_rule_ids: Optional[list[int]] = None
    narration_sample: Optional[str] = None
    cover_url: Optional[str] = None
    stat_defs: Optional[list] = None
    relation_stat_defs: Optional[list] = None
    default_inventory: Optional[list] = None
    default_location: Optional[str] = None
    time_slots: Optional[list] = None
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
    summary_model_ref: Optional[str] = None
    offscreen_brief: Optional[bool] = None


class RpgModuleOut(BaseModel):
    id: int
    name: str
    creator_note: str
    genre: str
    # 裸 str 不是 PlayStyle：老库里的空串要能读出来，见上面的注释
    play_style: str
    worldview: str
    opening_scene: str
    system_instruction: str
    enabled_rule_ids: list[int] = []
    narration_sample: str
    cover_url: str
    stat_defs: list
    relation_stat_defs: list
    default_inventory: list
    default_location: str
    time_slots: list
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
    summary_model_ref: str
    offscreen_brief: bool
    session_count: int = 0
    npc_count: int = 0
    entry_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RpgAssistIn(BaseModel):
    """编辑模组时按一下「帮我写」。不落库，返回的东西由作者决定要不要用。"""
    # 栏位名，白名单在 agents/rpg_assist.py 的 FIELD_SPECS
    field: str
    # 这一栏当前的内容。空 = 从零生成，非空 = 在原文上优化
    content: str = ""
    # {展示名: 文本}，作为参考喂给模型。传前端表单里的实时值而不是让后端
    # 回查——作者刚敲进去还没保存的内容，库里查不到
    context: dict[str, str] = {}


class RpgAssistOut(BaseModel):
    text: str


# ── 写作规则 ──────────────────────────────────────────────────────────────

class RpgRuleCreate(BaseModel):
    name: str
    content: str = ""
    enabled: bool = True
    sort_order: int = 0


class RpgRuleUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    enabled: Optional[bool] = None
    sort_order: Optional[int] = None


class RpgRuleOut(BaseModel):
    id: int
    name: str
    content: str
    enabled: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 构思向导 ──────────────────────────────────────────────────────────────

class WizardMessage(BaseModel):
    role: str
    content: str


class RpgWizardChatIn(BaseModel):
    """构思对话一轮。不落库，SSE 流式返回。"""
    messages: list[WizardMessage] = []
    model: str = ""
    nsfw: bool = False
    # 当前哪一步（world/stats/places/cast/things），空 = 还没进向导
    stage: str = ""
    # 前面几步已经定下来的内容，纯文本，喂给模型避免自相矛盾
    confirmed: str = ""
    play_style: str = "rpg"


class RpgWizardExtractIn(BaseModel):
    """抽当前这一步聊定的结论。known 带前面已定的名字白名单。"""
    stage: str
    messages: list[WizardMessage] = []
    # {stat_names: [], relation_names: [], location_names: []}
    known: dict = {}
    model: str = ""


class RpgGenerateIn(BaseModel):
    """在某一摊（地点/角色/道具/动作）点「AI 生成」。白名单由后端查库，不用前端传。
    不落库——生成完前端预览、勾选后才建行。"""
    instruction: str = ""
    count: int = 3
    nsfw: bool = False
    model: str = ""


class RpgWizardExtractOut(BaseModel):
    """各步字段全 Optional：一次只返回当前这一步那一摊。dropped 是被白名单
    过滤掉的东西的说明，前端要显示出来——静默丢弃等于骗作者。"""
    genre: Optional[str] = None
    worldview: Optional[str] = None
    opening_scene: Optional[str] = None
    system_instruction: Optional[str] = None
    narration_sample: Optional[str] = None
    stat_defs: Optional[list] = None
    relation_stat_defs: Optional[list] = None
    locations: Optional[list] = None
    default_location: Optional[str] = None
    npcs: Optional[list] = None
    items: Optional[list] = None
    actions: Optional[list] = None
    dropped: list[str] = []


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
    slot_locations: dict = {}
    keywords: str = ""
    ai_scheduled: bool = False
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
    slot_locations: Optional[dict] = None
    keywords: Optional[str] = None
    ai_scheduled: Optional[bool] = None
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
    slot_locations: dict
    keywords: str
    ai_scheduled: bool
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
    start_with: bool = False
    effects: dict = {}
    sort_order: int = 0


class RpgItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    usable: Optional[bool] = None
    consumable: Optional[bool] = None
    start_with: Optional[bool] = None
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
    start_with: bool
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
    # 地图坐标，百分比。默认 0 是必须的：前端新建地点时把整个表单铺开传过来，
    # 里面没有 x/y（坐标只由拖拽写）
    x: int = 0
    y: int = 0


class RpgLocationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    connections: Optional[list] = None
    enter_requires: Optional[dict] = None
    sort_order: Optional[int] = None
    x: Optional[int] = None
    y: Optional[int] = None


class RpgLocationOut(BaseModel):
    id: int
    module_id: int
    name: str
    description: str
    connections: list
    enter_requires: dict
    sort_order: int
    x: int
    y: int
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
    # 时段表。不给或给空列表都是「跟模组走」（而且是活的，模组后来改了会跟着变）。
    # 「这一局不要时钟」没法在这里表达，只有模组本身不设时段才是那个意思
    time_slots: Optional[list] = None


class RpgSessionUpdate(BaseModel):
    title: Optional[str] = None


class RpgNoteDeleteIn(BaseModel):
    """要删掉的那条近况的键名。GM 记错了，玩家自己划掉。"""
    key: str


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
    time_slots: list
    slot: str
    day: int
    flags: dict
    npc_states: dict
    npc_notes: dict
    npc_activities: dict
    npc_places: dict
    chronicle: list
    visited: list
    summary: str
    summarized_upto_id: int
    turn_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RpgAdvanceOut(BaseModel):
    """结束一个时段之后的新状态，外加给玩家看的那几句话。"""
    session: RpgSessionOut
    facts: list[str] = []


# ── 消息与回合 ────────────────────────────────────────────────────────────

class RpgMessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    # 已废弃：后端不再读写，保留只为老前端不至于拿到 null 就崩。
    # 新的筛选键是下面的 present
    thread_id: Optional[int] = None
    # 这条消息发生在哪个地点，以及当时在场的 NPC id 列表（写入时快照）
    location: str = ""
    # None = 不知道（迁移过来的老消息）→ 当所有人可见；[] = 确定只有玩家一个人
    present: Optional[list[int]] = None
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
    # 当前前端正在查看的 NPC。只决定上下文取哪条记忆，不影响动作目标。
    focus_npc_id: Optional[int] = None
    # 这一轮归哪条对话线，值是 NPC 的 id；不给 = 场面线。
    # 和 target_npc 是两件事：它管「这段叙事归哪条历史」，target_npc 管
    # 「这个动作用在谁身上」。在老兵线里对老板娘用动作是合法的
    thread_id: Optional[int] = None


class RpgMoveIn(BaseModel):
    """瞬移的目标地点名。存名字不存 id，同 sessions.location 那一套。"""
    target: str


class RpgMoveOut(BaseModel):
    """瞬移之后的新状态，外加给玩家看的那句话（被拦时是拒绝的理由）。"""
    session: RpgSessionOut
    message: str = ""


class RpgSuggestOut(BaseModel):
    suggestions: list[str]


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
