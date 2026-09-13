"""RPG 模式的数据模型：模组 / 世界书 / NPC / 道具 / 地点 / 动作 / 存档局 / 消息 / 快照。

与酒馆、小说侧都完全独立。理由同当初酒馆不复用小说侧：共用一张表会让两边
改一个字段都要顾虑对面。

与酒馆最本质的差别是这里有「世界的权威状态」——数值、背包、地点存在库里，
模型只能提议改动（state_delta），后端校验后才生效。

驱动这个模式的不是骰子而是数值：玩家做一件事 → 数值变了 → 跨过某条线 →
解锁新内容。所以数值由模组作者自己定义（stat_defs），判定只是可选调味。
"""
from datetime import datetime
from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class RpgModule(Base):
    """模组（剧本），对应酒馆的角色卡：一份可反复开局的世界设定。"""
    __tablename__ = "rpg_modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 唯一归属根，其余表靠外键链回来，_get_owned_* 逐级校验到这里
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # 只给作者看，永远不进 prompt。照抄酒馆的安全底线，有哨兵测试守着
    creator_note: Mapped[str] = mapped_column(Text, default="")

    worldview: Mapped[str] = mapped_column(Text, default="")
    # 开局旁白，建局时落成首条 assistant 消息
    opening_scene: Mapped[str] = mapped_column(Text, default="")
    # GM 风格覆盖，拼在底层 GM 指令之后
    system_instruction: Mapped[str] = mapped_column(Text, default="")

    # 勾选的 rpg_rules.id（RPG 自己的写作规则库，不是酒馆的也不是小说侧的）。
    # 默认 [] = 不注入。理由同酒馆：RPG 是全新功能，没有「老数据护栏不能丢」的
    # 包袱，所以不要小说侧那套 NULL 三态语义
    enabled_rule_ids: Mapped[list] = mapped_column(JSON, default=list)
    # 叙事腔调样例。只作为文字引用进 system，不做真实 few-shot 轮——
    # 那会让模型学着连玩家那一侧一起写
    narration_sample: Mapped[str] = mapped_column(Text, default="")

    cover_url: Mapped[str] = mapped_column(String(300), default="")

    # 「都市」「魔法学院」「互动养成」这种。只是一句话进 GM 提示词，
    # 但它决定了模型的整体基调，比任何参数都管用
    genre: Mapped[str] = mapped_column(String(100), default="")

    # 玩法类别：sim（模拟）/ rpg（探索冒险，默认）/ slg（经营策略）。
    # 和 genre 是两根正交的轴：genre 说「世界长什么样」，它说「这局怎么玩」。
    # 同一个魔法学院，可以是模拟养成也可以是探索冒险，两者说的不是一回事。
    # 取值见 services/rpg_play_style.py
    play_style: Mapped[str] = mapped_column(String(20), default="rpg")

    # ── 数值定义 ──
    # 玩家那一套。[{name, initial, min, max, for_check, on_zero, display}]
    # max=None 表示无上限（钱、声望这种）；display=隐藏 的项玩家看不见，
    # 用来放幕后计数器（怀疑度），但一样能触发世界书条件
    stat_defs: Mapped[list] = mapped_column(JSON, default=list)
    # 关系数值。定义一次，每个角色各持一份，存在 session.npc_states 里
    relation_stat_defs: Mapped[list] = mapped_column(JSON, default=list)

    # ── 开局默认值：建局时整份拷进 session ──
    default_inventory: Mapped[list] = mapped_column(JSON, default=list)
    default_location: Mapped[str] = mapped_column(String(100), default="")

    # 时段表，如 ["早", "中", "晚"]。空 = 这个模组不用时段，一切照旧。
    # 这里是默认值，建局时可以改，改完存进 session 自己那一份
    time_slots: Mapped[list] = mapped_column(JSON, default=list)

    # 作废：数值系统换成 stat_defs 之后这两列没人读了。项目没有 Alembic，
    # create_all 不删列，而它们建成了 NOT NULL，从模型里拿掉会让老库插入直接
    # 失败，所以只能留着
    default_attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    default_hp_max: Mapped[int] = mapped_column(Integer, default=20)

    # ── 判定（可选，默认关）──
    # 档位→成功率的映射由模组作者定死，模型只能选档位不能给数字。
    # 这是治「同一个撬锁这轮困难下轮普通」最有效的一招：模型判断
    # 「这算困难吗」比判断「这是 55% 还是 40%」稳定一个数量级。
    # 列名沿用 dc_table，形状一样都是「档位→数字」，改列名要建新表不值得
    rate_table: Mapped[dict] = mapped_column(
        "dc_table", JSON,
        default=lambda: {"trivial": 90, "easy": 75, "medium": 55, "hard": 35, "extreme": 15},
    )
    # 整体难度旋钮，加到成功率上。+10 轻松 / -10 硬核
    difficulty_bias: Mapped[int] = mapped_column(Integer, default=0)
    # never = 纯数值不判定（默认）/ smart = 让 AI 判断要不要判 / always = 每轮都判。
    # 默认 never：这个模式的地基是数值，判定只是冒险题材的调味
    check_mode: Mapped[str] = mapped_column(String(10), default="never")
    # 开了判定之后还掷不掷随机数。关掉则纯看成功率，同一存档重玩结果一样
    random_check: Mapped[bool] = mapped_column(Boolean, default=True)

    # ── 上下文与模型参数 ──
    # 世界书关键词往回扫几条消息，含义同酒馆
    scan_depth: Mapped[int] = mapped_column(Integer, default=3)
    context_turns: Mapped[int] = mapped_column(Integer, default=20)
    temperature: Mapped[float] = mapped_column(Float, default=0.9)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    # 期望叙事字数（软约束）。RPG 单轮该比酒馆长，所以给默认值而不是 0
    reply_length: Mapped[int] = mapped_column(Integer, default=300)

    model_ref: Mapped[str] = mapped_column(String(100), default="")
    # 裁决 / 结算 / 建议共用的便宜模型。酒馆只有摘要一个，
    # RPG 一轮里有三处结构化调用，合用一个字段省得配四遍
    fast_model_ref: Mapped[str] = mapped_column(String(100), default="")
    # 压缩旧剧情用。空 = 跟着 fast_model_ref 走，所以老库行为不变。
    # 单独拎出来是因为摘要和裁决的要求不一样：裁决要快要便宜，摘要错一次
    # 会把错的东西一路带到局终（它的输出会喂给下一次摘要）
    summary_model_ref: Mapped[str] = mapped_column(String(100), default="")

    # 推时段时写一句「别处的传闻」进大事记。**默认关**：开了之后「结束这个
    # 时段」就不再是零模型调用了，这个承诺写在文档、按钮提示和测试里
    offscreen_brief: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgRule(Base):
    """RPG 写作规则。与酒馆 tavern_rules、小说侧 prompt_rules 各自分表。

    小说侧那批规则是按写长篇正文调的，套到逐轮对话上会打架；酒馆那批又是按
    酒馆玩法调的，共用一张表会让几个模式的列表互相污染。这里没有内置规则，
    所以不需要 is_builtin / builtin_key——RPG 默认不注入任何规则。
    """
    __tablename__ = "rpg_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgWorldEntry(Base):
    """世界书词条。结构与 TavernWorldEntry 一致，挂在模组上。

    没有酒馆的 linked_book_card_ids：RPG 没有「多张卡同场」的概念，
    一个模组一本世界书。
    """
    __tablename__ = "rpg_world_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rpg_modules.id"), nullable=False, index=True
    )

    # 触发关键词，逗号分隔
    keywords: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # 常驻词条：不看关键词，每轮都注入
    constant: Mapped[bool] = mapped_column(Boolean, default=False)
    # 插入深度：0 = 拼进 system；n>0 = 插到倒数第 n 条消息开头
    depth: Mapped[int] = mapped_column(Integer, default=0)

    # 数值门槛。空 = 无条件（和以前一样）。格式见 services/rpg_state.py。
    # 语义唯一：条件是「附加约束」，全部满足才算生效——
    # 常驻+条件 = 满足就每轮注入（好感过 50 她的说话方式变了）
    # 关键词+条件 = 提到关键词「且」满足条件才注入。
    # 世界书本来就有 depth 能插到任意位置，加上条件它就是事件系统，
    # 不必另开一张事件表和一套注入管线。列名避开 condition：
    # 那是部分 SQL 方言的保留字
    trigger_condition: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgNpc(Base):
    """角色卡。字段结构照抄酒馆卡，但放在 RPG 自己的表里，两边互不牵连。"""
    __tablename__ = "rpg_npcs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rpg_modules.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(300), default="")

    # npc = 世界里的人 / protagonist = 主角模板，开局时预填玩家角色。
    # 两者共用同一个卡片编辑器，不写两套
    role: Mapped[str] = mapped_column(String(20), default="npc")

    # 一句话简介，给作者在列表里认人用，也进提示词
    description: Mapped[str] = mapped_column(Text, default="")
    # 分栏档案，键同酒馆：外貌身材 / 背景故事 / 能力特长 / 关系网络
    profile_sections: Mapped[dict] = mapped_column(JSON, default=dict)
    # [{"user": ..., "assistant": ...}]，只作为文字引用进提示词
    dialogue_examples: Mapped[list] = mapped_column(JSON, default=list)

    persona: Mapped[str] = mapped_column(Text, default="")
    # 只在首次见面时注入（npc_states 里该 npc 的 met 为假），之后省掉这段 token
    appearance: Mapped[str] = mapped_column(Text, default="")

    # 常驻地点。等于 session.location 即视为在场
    location: Mapped[str] = mapped_column(String(100), default="")
    # 作息表：{"早": "大礼堂", "晚": "寝室"}。当前时段在这张表里有值就用它，
    # 没有（或整个表是空的）就落回 location。**不是第二个在场判据**——
    # 它只是给 location 换了个按时段取值的算法，谁在场仍然只有一种问法
    slot_locations: Mapped[dict] = mapped_column(JSON, default=dict)
    # 额外触发词：人不在场但被提到也注入，匹配方式同世界书
    keywords: Mapped[str] = mapped_column(String(500), default="")

    # 勾上之后，这一轮没被提到的人会自己过日子：模型给她写一句「最近在做什么」，
    # 记在 session.npc_activities 里，下回见面时注入。**默认关**——它意味着
    # 每轮多一次模型调用，而这个模式此前只有玩家说话时才花钱
    ai_scheduled: Mapped[bool] = mapped_column(Boolean, default=False)

    # 这个人的关系数值起点。空 = 按模组的 relation_stat_defs 取 initial；
    # 填了就覆盖对应项（「她一开始就恨你」）
    initial_state: Mapped[dict] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgItem(Base):
    """道具。用掉它数值精确增减，AI 碰不到这个数。"""
    __tablename__ = "rpg_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rpg_modules.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # 消耗品 / 装备 / 关键道具。只用来分组显示，不影响结算
    category: Mapped[str] = mapped_column(String(20), default="消耗品")

    usable: Mapped[bool] = mapped_column(Boolean, default=True)
    # 用完就少一个。关键道具（钥匙）设 false
    consumable: Mapped[bool] = mapped_column(Boolean, default=True)
    # 开局就带在身上。和 rpg_modules.default_inventory 是两件事：那是「这一局
    # 开场凭空多出来的一件东西」，这是「这件道具本身就该在玩家身上」。
    # 建局时两边合并（rpg_state.starting_inventory）
    start_with: Mapped[bool] = mapped_column(Boolean, default=False)
    # {"精力": 20, "资金": -50}，键必须是 stat_defs 里有的名字
    effects: Mapped[dict] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgLocation(Base):
    """地点。连接关系构成真地图，移动是明确动作而不是随口一说。"""
    __tablename__ = "rpg_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rpg_modules.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    # 可选父地点：空表示大地图地点；有值表示父地点内部的小地图节点。
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("rpg_locations.id"), nullable=True, index=True,
    )

    # 从这里能直接去哪儿，存名字不存 id：RpgNpc.location 本来就是字符串、
    # onstage_npcs() 本来就按名字比对，用 id 会凭空多一套映射
    connections: Mapped[list] = mapped_column(JSON, default=list)
    # 进入条件，格式同世界书的 trigger_condition。空 = 随便进
    enter_requires: Mapped[dict] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # 地图上的位置，百分比 0..100 而不是像素：换个屏幕宽度不用重算，
    # 前端直接 left: x%。两个都是 0 = 作者还没摆过，前端落到兜底网格
    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgAction(Base):
    """模组自定义的动作按钮。点一下数值由引擎直接算，AI 只拿到已发生的事实。"""
    __tablename__ = "rpg_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rpg_modules.id"), nullable=False, index=True
    )

    # 按钮上的字，如「夸她」
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 点了等于玩家说了这句话
    prompt_hint: Mapped[str] = mapped_column(Text, default="")

    # 玩家数值增减
    effects: Mapped[dict] = mapped_column(JSON, default=dict)
    # 对目标角色的关系数值增减
    relation_effects: Mapped[dict] = mapped_column(JSON, default=dict)
    # 可用条件，格式同世界书。不满足时前端置灰并显示原因
    requires: Mapped[dict] = mapped_column(JSON, default=dict)
    # 要不要先选一个在场角色。relation_effects 非空时基本都要
    needs_target: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgSession(Base):
    """一局游戏。世界的权威状态就存在这行上。"""
    __tablename__ = "rpg_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rpg_modules.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(200), default="")
    # alive / dead / ended。血量归零后端置 dead，前端据此拦输入并弹读档
    status: Mapped[str] = mapped_column(String(20), default="alive")

    # ── 玩家角色：属于这一局而不是模组，同一个模组可以开多局、每局角色不同 ──
    char_name: Mapped[str] = mapped_column(String(100), default="")
    char_desc: Mapped[str] = mapped_column(Text, default="")

    # 这一局的玩家数值，「名字→数字」。键由模组的 stat_defs 定义，
    # 建局时按它初始化。min/max/on_zero 都要回查 stat_defs，所以这里
    # 只存值不存定义。列名沿用 attributes（含义变了但形状没变，
    # 改列名要建新表搬数据，不值得）
    stats: Mapped[dict] = mapped_column(
        "attributes", JSON, default=dict
    )

    # 作废：体力现在就是 stat_defs 里一项普通数值（想要的模组自己定义）。
    # 理由同 default_attributes——NOT NULL 列不能从模型里拿掉
    hp: Mapped[int] = mapped_column(Integer, default=20)
    hp_max: Mapped[int] = mapped_column(Integer, default=20)

    # [{"name": "生锈的铁钥匙", "qty": 1, "note": "从守卫身上摸到"}]
    # note 强烈建议有：模型看到它会自然复用这个细节
    inventory: Mapped[list] = mapped_column(JSON, default=list)
    location: Mapped[str] = mapped_column(String(100), default="")

    # ── 时间。玩家自己拨的时钟，只有「结束这个时段」能推动它 ──
    # **只在玩家建局时改过才非空**。空 = 跟模组走，这样模组后来把时段改细，
    # 还没定制的局会跟着变（见 rpg_state.slot_table）。存过的就冻住不再追溯，
    # 理由同 default_location
    time_slots: Mapped[list] = mapped_column(JSON, default=list)
    # 当前时段，存的是「名字」不是下标。存下标就得把 module 传进
    # check_condition 才能换算，那会打破「一处写完、三处共用」；
    # 先例是 RpgLocation.connections 存名字不存 id
    slot: Mapped[str] = mapped_column(String(20), default="")
    day: Mapped[int] = mapped_column(Integer, default=1)

    # 剧情开关，扁平不嵌套。模型对嵌套结构做增量改动极不可靠；扁平键值的
    # 合并语义唯一：同键覆盖、新键追加、值为 null 表示删除
    flags: Mapped[dict] = mapped_column(JSON, default=dict)
    # {"3": {"好感": 2, "信任": 40, "met": true}}，键是 npc_id 的字符串——
    # 名字会改，id 不会。数值项按模组的 relation_stat_defs 初始化，
    # met 是内部标记（控制首次见面才注入外貌），渲染面板时跳过
    npc_states: Mapped[dict] = mapped_column(JSON, default=dict)

    # 这一局里 GM 边玩边记下的 NPC 近况。{"3": {"伤势": "左肩中刀", "身上带着": "猎枪"}}，
    # 外层键同 npc_states（npc_id 的字符串），内层是自由键值，值一律是字符串。
    #
    # 刻意不并进 npc_states：那张表里所有非 met 的键都被当成关系数字用
    # （rpg_context._npc_block 拿去排版、apply_relations 拿去 clamp、
    # check_condition 拿去比大小、前端两处拿去 Number()）。合表之后模型
    # 只要写出一次 {"好感": "很喜欢你"}，62 就被一个字符串盖掉，于是关系数
    # 悄悄归零、所有「好感≥50」的门一起失效，而且全程没有任何报错。
    npc_notes: Mapped[dict] = mapped_column(JSON, default=dict)

    # AI 调度的产物：{"3": "在图书馆翻了一下午旧报纸"}。键同 npc_states
    # （npc_id 的字符串），值是**一句**话，每个角色只有一个。
    #
    # 存在这一局而不是角色卡上：同一个模组可以开好几局，写进卡里等于把 A 局的
    # 玩法带到 B 局——玩家在 B 局第一次见到赫敏，她已经在复述 A 局的事了。
    # 和 npc_notes 分开同理，那张表是 GM 从叙事里读出来的近况，这张是调度替
    # 不在场的人编的行动，两个写手共用一个键空间迟早互相盖
    npc_activities: Mapped[dict] = mapped_column(JSON, default=dict)

    # 剧情把谁挪到哪儿了：{"3": "校长办公室"}，键同 npc_states。
    #
    # 作息表和常驻地点回答的是「没事的时候她在哪儿」，这一列回答「这一格剧情
    # 把她挪到哪了」——玩家在对话框里说「你过来」，结算从刚写出的正文里读出
    # 她的新位置写在这里，下一轮她真的站在跟前（侧栏这么说、能拉进私聊、
    # 调度也不再替一个站在你面前的人写「在宿舍干什么」）。
    #
    # 存这一局而不是写进角色卡：同一个模组开两局，A 局把她叫到办公室，
    # B 局第一次见面不该从办公室开始。理由同 npc_activities。
    #
    # **推时段清空**（rpg_state.advance_slot）：时段一变就回到「作息表说了算」，
    # 否则模型随手写的一笔会永久盖掉作者排的作息表，而那是他唯一的排期手段。
    npc_places: Mapped[dict] = mapped_column(JSON, default=dict)

    # 大事记：这一局里「已经传开」的事，跨对话线共享。存在的理由是分线之后
    # 「你在铁匠铺听说老兵他哥失踪了，回去找老兵，老兵没听过」——这不是摘要器
    # 能修的，摘要只管一条线。
    #
    # 口吻必须是「已经传开的事」而不是「发生过的事」：它注入每一条线，等于
    # 所有 NPC 全知。所以只写值得让所有人知道、且真的传开了的事，
    # 密室里干的事不进来（字段说明见 rpg_settle.jinja2）
    chronicle: Mapped[list] = mapped_column(JSON, default=list)

    # 去过的地点名。地图的迷雾读它：没去过也不挨着去过的地方，画成一个灰点。
    # 存名字不存 id，理由同 connections
    visited: Mapped[list] = mapped_column(JSON, default=list)

    # 滚动摘要，含义同酒馆。历史统一成一条之后只剩这一份
    summary: Mapped[str] = mapped_column(Text, default="")
    summarized_upto_id: Mapped[int] = mapped_column(Integer, default=0)

    # NPC 独立摘要与各自已压缩到的消息指针，按 NPC id 存储。
    # 保留为 JSON 映射，兼容已有数据库与没有独立线的旧会话。
    thread_summaries: Mapped[dict] = mapped_column(JSON, default=dict)
    thread_upto: Mapped[dict] = mapped_column(JSON, default=dict)

    # 难度台账：[{"key": "撬锁", "attr": "敏捷", "band": "hard"}]，留最近 20 条。
    # 裁决时注入当一致性锚，挡住「同一个动作难度来回跳」
    dc_ledger: Mapped[list] = mapped_column(JSON, default=list)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgMessage(Base):
    __tablename__ = "rpg_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rpg_sessions.id"), nullable=False, index=True
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")

    # **已废弃：后端不再读这一列。** 保留只为不动老库的表结构（SQLite 删列要
    # 重建表）。原先它同时是三件事——历史分区键、隐私边界、界面视图，三件事
    # 绑在一个值上，于是每次让一件对了另两件就错。现在由 location + present
    # 两列接管，见下
    #
    # **不要给它加外键，也不要写进 _repair_data 的悬空外键清理**——角色被删
    # 之后那会把一条角色线静默变成场面线，两条历史当场合并，且不会报错
    thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # 这条消息发生在哪个地点。**写入时快照**，不是读时回查 sess.location——
    # 玩家会走，事后推不出来。统一时间线里混着好几个地点的消息，靠它在
    # 历史上打分隔，否则模型会把三天前在铁匠铺说的话读成眼前这场对话
    location: Mapped[str] = mapped_column(String(100), default="")

    # 这条消息发生时**在场**的 NPC id 列表。同样是写入时快照：npc_places
    # 每回合都在变（作息表推时段会清空、剧情会把谁挪走），事后推不出来
    #
    # 这一列是新的隐私边界。私聊视图 = present 里有她的消息；群戏写一次
    # present=[赫敏, 罗恩]，两边同时看得到，**一份存储零复制**——复制进各条
    # 历史会让同一段戏在几条线里各自演化、各自被压成概要，§23 那条硬规矩
    #
    # **nullable 是有意的，两种空含义不同**：
    #   None  = 不知道（迁移过来的老消息）→ 当所有人可见，老存档什么都不消失
    #   []    = 确定只有玩家一个人 → 不进任何 NPC 的视图
    # 把 None 写成 [] 会让老存档里所有群戏对 NPC 集体失忆
    present: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)

    # 本回合判定，只挂在 user 行上。null = 这轮没判定。
    # 挂 user 行而不是 assistant 行，是为了中断语义：assistant 行要等叙事跑完
    # 才创建，叙事中途崩了骰子就丢了——可玩家已经看过掷骰动画，会觉得
    # 「我掷的 20 呢」。挂 user 行则骰子和输入同生共死
    roll: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 本回合状态变化，只挂在 assistant 行上。
    # null = 未结算（中断或结算失败），要和「结算出来是空变化」区分开
    state_delta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 结算顺带产出的 3 条建议行动，不为此单开一次 LLM 调用
    suggestions: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 叙事那次调用的消耗
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 裁决 + 结算 + 建议的合计。和叙事分开存，token 面板才能显示
    # 「叙事 1240 / 判定结算 380」，让三次调用的代价对玩家可见
    aux_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    aux_output_tokens: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RpgSave(Base):
    """存档快照。有了权威状态就必须能反悔，否则一次坏判定毁掉整局。

    语义照 services/state_snapshot.py：存的是「这一回合生成之前的干净状态」。
    不复用那边的 Memory 表——它的 novel_id 是 NOT NULL。
    """
    __tablename__ = "rpg_saves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rpg_sessions.id"), nullable=False, index=True
    )

    # auto 保留最近 30 张，manual 永不自动清
    kind: Mapped[str] = mapped_column(String(10), default="auto")
    # 手动存档名；auto 存「第 12 回合」
    label: Mapped[str] = mapped_column(String(200), default="")
    turn_index: Mapped[int] = mapped_column(Integer, default=0)

    # id > 这个值的消息都是快照之后产生的，回溯时按它删
    before_message_id: Mapped[int] = mapped_column(Integer, default=0)

    # session 上全部可变字段的全量拷贝。summary 和 summarized_upto_id 必须
    # 一起存——否则回溯后摘要里还留着「未来」的剧情，模型会写出玩家没经历过
    # 的事，这是最难查的一类 bug
    state: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
