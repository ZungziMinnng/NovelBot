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
    lock_protagonist: bool = False
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
    image_model_ref: str = ""
    offscreen_brief: bool = False
    # 时段推进的两个阈值，0 = 关，形状见 models.RpgModule
    # slot_budget 默认 3：建模组这条路会把这份默认值原样传给 RpgModule(**dump)，
    # 所以列上的默认管不到新建的模组，真正生效的是这一行
    slot_budget: int = 3
    chat_nudge: int = 0
    free_costs_slot: bool = False
    # NPC 立绘出图设置，形状见 models.RpgModule.image_config
    image_config: dict = {}


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
    lock_protagonist: Optional[bool] = None
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
    image_model_ref: Optional[str] = None
    offscreen_brief: Optional[bool] = None
    slot_budget: Optional[int] = None
    chat_nudge: Optional[int] = None
    free_costs_slot: Optional[bool] = None
    image_config: Optional[dict] = None


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
    # 给默认值：老模组的行读出来没有这一项，理由同下面 slot_budget
    lock_protagonist: bool = False
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
    image_model_ref: str
    offscreen_brief: bool
    # 给默认值：老模组的行读出来没有这两项，不给就整份校验失败
    slot_budget: int = 0
    chat_nudge: int = 0
    free_costs_slot: bool = False
    image_config: dict = {}
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


# ── 常用 GM 指令 ──────────────────────────────────────────────────────────

class RpgInstructionPresetCreate(BaseModel):
    name: str
    content: str = ""


class RpgInstructionPresetUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None


class RpgInstructionPresetOut(BaseModel):
    id: int
    name: str
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 预设库 ────────────────────────────────────────────────────────────────

# JSON 列一律是裸 list，不做嵌套结构校验。写入方只有自家前端，多一层 pydantic
# 嵌套模型的唯一效果是「前端给数值定义加个字段，后端就开始 422」。

class RpgStatPresetCreate(BaseModel):
    name: str
    note: str = ""
    stat_defs: list = []
    relation_stat_defs: list = []
    sort_order: int = 0


class RpgStatPresetUpdate(BaseModel):
    name: Optional[str] = None
    note: Optional[str] = None
    stat_defs: Optional[list] = None
    relation_stat_defs: Optional[list] = None
    sort_order: Optional[int] = None


class RpgStatPresetOut(BaseModel):
    id: int
    name: str
    note: str
    stat_defs: list
    relation_stat_defs: list
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RpgActionPresetCreate(BaseModel):
    name: str
    note: str = ""
    actions: list = []
    sort_order: int = 0


class RpgActionPresetUpdate(BaseModel):
    name: Optional[str] = None
    note: Optional[str] = None
    actions: Optional[list] = None
    sort_order: Optional[int] = None


class RpgActionPresetOut(BaseModel):
    id: int
    name: str
    note: str
    actions: list
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
    # 世界规模：world = 完整世界，region = 单一区域故事
    world_scope: str = "region"


class RpgWizardExtractIn(BaseModel):
    """抽当前这一步聊定的结论。known 带前面已定的名字白名单。"""
    stage: str
    messages: list[WizardMessage] = []
    # {stat_names: [], relation_names: [], location_names: []}
    known: dict = {}
    model: str = ""
    # 抽取的**起始**温度。None = 按 call_json 的默认 0.3 走（老前端不传就是这条路）；
    # 0.1 那一档兜底始终保留，调这个只影响第一次尝试
    temperature: Optional[float] = None


class RpgWizardFullIn(BaseModel):
    """根据一句话想法生成整套模组草案，不直接落库。"""
    instruction: str = ""
    nsfw: bool = False
    model: str = ""
    world_scope: str = "region"
    temperature: Optional[float] = None  # 同 RpgWizardExtractIn


class RpgGenerateIn(BaseModel):
    """在某一摊（地点/角色/道具/动作）点「AI 生成」。白名单由后端查库，不用前端传。
    不落库——生成完前端预览、勾选后才建行。"""
    instruction: str = ""
    count: int = 3
    nsfw: bool = False
    model: str = ""
    temperature: Optional[float] = None  # 同 RpgWizardExtractIn


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
    time_slots: Optional[list] = None
    npcs: Optional[list] = None
    items: Optional[list] = None
    skills: Optional[list] = None
    tasks: Optional[list] = None
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
    # 只给这个人的出图设置。稀疏，形状同 RpgModule.image_config，
    # {} = 整份跟着模组走。见 services/rpg_image.py
    image_config: dict = {}
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
    relation_enabled: bool = False
    relation_stat_names: list[str] = []
    sort_order: int = 0


class RpgNpcUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    avatar_url: Optional[str] = None
    # 整份替换，不做深合并：「取消覆写某一项」在前端就是把那个 key 删掉再发
    # 整份上来，后端要是合并就永远删不掉了
    image_config: Optional[dict] = None
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
    relation_enabled: Optional[bool] = None
    relation_stat_names: Optional[list[str]] = None
    sort_order: Optional[int] = None


class RpgNpcAvatarGenerateIn(BaseModel):
    """立绘生成。prompt 由前端从外貌字段预填后交用户过目，这里只收最终文本。"""
    prompt: str
    width: int = 1024
    height: int = 1536
    # None = 后端摇一个随机种子；给了值就是复现上一张脸
    seed: Optional[int] = None


class RpgPromptAsTagsIn(BaseModel):
    """中文源文转 Danbooru tag。只给光辉这类 SDXL 工作流用。"""
    source: str
    # 成人内容照实转，但默认关：开不开是用户在出图弹窗里自己勾的，绝不自动开
    nsfw: bool = False
    # True = 把这个 NPC 的名字也转成 Danbooru 角色 tag（做同人游戏时用，如
    # 日向雏田→hyuuga_hinata）。默认关：原创角色带上名字反而会污染出图
    include_char_name: bool = False


class RpgPromptAsTagsOut(BaseModel):
    # 命中的规范 tag（保序），join 起来就是发给工作流的提示词
    tags: list[str]
    # 两趟都没在词表里查到的原样词，交前端显示——少画一样不告诉用户比明说糟
    dropped: list[str]


class RpgNpcOut(BaseModel):
    id: int
    module_id: int
    name: str
    role: str
    avatar_url: str
    # 这张立绘的随机种子，0 = 没记录。只读，写它的只有生成接口
    avatar_seed: int = 0
    # 只给这个人的出图设置，{} = 整份跟着模组走
    image_config: dict = {}
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
    relation_enabled: bool
    relation_stat_names: list[str]
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


# ── 技能 ──────────────────────────────────────────────────────────────────

class RpgSkillCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "主动"
    usable: bool = True
    effects: dict = {}
    requires: dict = {}
    cooldown: int = 0
    start_with: bool = False
    sort_order: int = 0


class RpgSkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    usable: Optional[bool] = None
    effects: Optional[dict] = None
    requires: Optional[dict] = None
    cooldown: Optional[int] = None
    start_with: Optional[bool] = None
    sort_order: Optional[int] = None


class RpgSkillOut(BaseModel):
    id: int
    module_id: int
    name: str
    description: str
    category: str
    usable: bool
    effects: dict
    requires: dict
    cooldown: int
    start_with: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 任务 ──────────────────────────────────────────────────────────────────

class RpgTaskCreate(BaseModel):
    name: str
    description: str = ""
    objective: str = ""
    category: str = "支线"
    effects: dict = {}
    auto_start: bool = False
    sort_order: int = 0


class RpgTaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    objective: Optional[str] = None
    category: Optional[str] = None
    effects: Optional[dict] = None
    auto_start: Optional[bool] = None
    sort_order: Optional[int] = None


class RpgTaskOut(BaseModel):
    id: int
    module_id: int
    name: str
    description: str
    objective: str
    category: str
    effects: dict
    auto_start: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RpgTaskResolveIn(BaseModel):
    """玩家在确认窗里逐条勾完之后提交。只传 id 不传内容——提议的正文依据
    存在 task_proposals 里，让前端把 action 改了再回传等于绕开校验。

    没勾的那几条一并传上来（accept=False），后端照样从待确认里移掉：
    「我看过了，这条不算完」和「还没看」是两回事，混在一起弹窗会反复跳。"""
    accepts: list[dict] = []  # [{"id": "...", "accept": true}]


class RpgItemClaimConfirmIn(BaseModel):
    """认下一件新道具。consumable 只在模组道具表里**还没有**同名定义时才用得上
    ——已经有定义的按那一行走，这个值会被忽略。"""
    consumable: bool = True


class RpgTaskStateIn(BaseModel):
    """玩家自己在任务格里改一条：手动标完成/失败/重新进行，或者划掉。"""
    name: str
    # open / done / failed；给 "" 表示删掉这一条
    status: str = ""


# ── 地点 ──────────────────────────────────────────────────────────────────

class RpgLocationCreate(BaseModel):
    name: str
    description: str = ""
    parent_id: Optional[int] = None
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
    parent_id: Optional[int] = None
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
    parent_id: Optional[int]
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
    group: str = ""
    cost_slot: bool = False
    at_location: str = ""
    sort_order: int = 0


class RpgActionUpdate(BaseModel):
    name: Optional[str] = None
    prompt_hint: Optional[str] = None
    effects: Optional[dict] = None
    relation_effects: Optional[dict] = None
    requires: Optional[dict] = None
    needs_target: Optional[bool] = None
    group: Optional[str] = None
    cost_slot: Optional[bool] = None
    at_location: Optional[str] = None
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
    group: str
    cost_slot: bool
    at_location: str
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


class RpgDiscoveryApplyIn(BaseModel):
    """把勾中的发现项建成模组资产。ids 是 RpgSession.discoveries 里那些条目的 id——
    只传 id 不传内容，免得前端把名字改了、后端却按改过的名字去正文里找不到依据。"""
    ids: list[str]
    model: str = ""
    temperature: Optional[float] = None  # 同 RpgWizardExtractIn


class RpgDiscoveryApplyOut(BaseModel):
    """建了哪些行 + 哪些被拦下了。前五项直接回前端用来刷新那几张表。"""
    npcs: list[RpgNpcOut] = []
    locations: list[RpgLocationOut] = []
    items: list[RpgItemOut] = []
    # 技能和任务除了建行，还会顺手写进这一局（学会 / 接下），所以前端拿到
    # 非空的这两项时，会话本身也要跟着刷
    skills: list[RpgSkillOut] = []
    tasks: list[RpgTaskOut] = []
    # 这一局真的学会 / 接下了哪几个名字。不等于上面的 skills / tasks：模组里
    # 早就有定义、这一次只补「这一局也拿到」的那些不会出现在上面两项里，
    # 但会话确实变了，前端得凭这个决定要不要重拉会话
    learned: list[str] = []
    opened: list[str] = []
    # 被白名单过滤或重名拦下的说明。必须显示出来——静默丢弃等于骗作者
    dropped: list[str] = []
    # 处理完之后剩下的待确认项，前端拿它直接覆盖角标
    remaining: list = []


class RpgSessionOut(BaseModel):
    id: int
    module_id: int
    title: str
    status: str
    char_name: str
    char_desc: str
    stats: dict
    inventory: list
    skills: list = []
    location: str
    time_slots: list
    slot: str
    day: int
    # 这一格用掉的行动数 / 对话数。给默认值：老局读出来没有这两项。
    # 按钮的提醒读它们，见 RpgSession.slot_actions
    slot_actions: int = 0
    slot_chats: int = 0
    flags: dict
    # 每个 flag 第一次立起来那天。前端按钮的置灰判断要它算「之后 N 天」，
    # 给默认值：老局读出来没有这一项。见 RpgSession.flag_days
    flag_days: dict = {}
    npc_states: dict
    npc_notes: dict
    npc_activities: dict
    npc_places: dict
    # {"地窖": "门被你踹坏了"}，键是地名。见 RpgSession.place_notes
    place_notes: dict = {}
    chronicle: list
    visited: list
    # 这一局的待办清单和「模型觉得办完了」的待确认提议。见 RpgSession.tasks
    tasks: list = []
    task_proposals: list = []
    # 结算认出来、还没登记进模组的人/地方/东西，等作者勾选。见 RpgSession.discoveries
    discoveries: list = []
    # 结算说「你拿到了」、还没认领的新道具。见 RpgSession.item_claims
    item_claims: list = []
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

class RpgSettlementOut(BaseModel):
    status: str
    revision: str = ""
    attempts: int = 0
    domains: dict = {}
    changes: list[str] = []
    warnings: list[str] = []
    facts: list[dict] = []
    applied: dict = {}
    proposed: dict = {}
    retryable: bool = False


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
    settlement: Optional[RpgSettlementOut] = None
    suggestions: Optional[list] = None
    input_tokens: int
    output_tokens: int
    aux_input_tokens: int
    aux_output_tokens: int
    created_at: datetime

    model_config = {"from_attributes": True}


class RpgMessageUpdate(BaseModel):
    """修改正文并将相关结算、摘要标记为过期。"""
    content: str


class RpgTurnRequest(BaseModel):
    content: str
    # 玩家自己指定用哪项数值判定。给了就跳过裁决那次调用，零延迟零成本
    attr: str = ""
    # 「点出来的」行动。全空就是自由打字，走 AI 结算；给了任意一个
    # 就走引擎，数字由模组定义算死，AI 只负责写成画面
    action_id: Optional[int] = None
    item_name: str = ""
    skill_name: str = ""
    move_to: str = ""
    target_npc: str = ""
    # 这一轮的对话模式，玩家在输入框上方明着选：
    #   group   群聊——在场的人都参与，这段话记进他们每个人的记忆
    #   private 私聊——只跟 private_with 那一个人说，只记进她的记忆
    #   solo    独自行动——这一轮不跟人说话，但在场的人看着（照样记给他们）
    # 它替掉了老的 focus_npc_id。那个字段名义上是「前端正在查看谁」，实际上
    # 偷偷决定了模型能记住多少——玩家看见的是个筛选器，代码拿它当记忆开关，
    # 于是一对一聊十轮之后她会突然说第一次见面的台词。模式必须是明牌的
    mode: str = "group"
    # 私聊对象，只在 mode=private 时有意义。她必须本来就在跟前
    private_with: Optional[int] = None
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
