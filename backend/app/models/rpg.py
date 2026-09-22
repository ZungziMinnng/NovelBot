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


# 详细档案的英文键 → 中文键。
#
# RPG 从编辑器到提示词认的一直是中文：编辑器按中文键取值（见 RpgModule.tsx 的
# PROFILE_KEYS），rpg_context 把 key 当标签直接拼进提示词。可向导早期版本是照
# **酒馆**那套写的——酒馆存英文键、显示时翻成中文，方向正好相反——于是向导生成的
# 角色，档案内容在库里躺着、也进了提示词（标签是 background：），编辑器那三栏却
# 永远是空的。这份映射就是用来把老数据读回中文的。
PROFILE_ALIASES = {
    "appearance": "外貌身材",
    "background": "背景故事",
    "abilities": "能力特长",
    "relationships": "关系网络",
}


def normalize_profile_sections(sections, appearance: str = "") -> tuple[dict, str]:
    """把详细档案归一到 RPG 的规矩：中文键，且**外貌不进分栏**。

    返回 `(归一的档案, 顶层外貌)`。外貌那一格抽出来还给顶层的 appearance 字段：
    那本来就是它的家（编辑器里「外貌」单独一栏），留在分栏里会被注入两遍，
    立绘的提示词也会把同一段外貌拼两次。

    只归一读出来的值，不回写库——作者在编辑器里存一次，中文键就落到库里了。
    """
    out: dict[str, str] = {}
    for raw_key, raw_text in dict(sections or {}).items():
        text = str(raw_text or "").strip()
        if not text:
            continue
        key = PROFILE_ALIASES.get(str(raw_key).strip(), str(raw_key).strip())
        if key == "外貌身材":
            # 顶层填了就只留顶层那份；顶层空着才拿分栏这份补上，不丢内容
            appearance = appearance or text
            continue
        out[key] = text
    return out, appearance


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

    # 玩法类别：sim（模拟器）/ rpg（探索冒险，默认）/ slg（角色养成）。
    # 和 genre 是两根正交的轴：genre 说「世界长什么样」，它说「这局怎么玩」。
    # 同一个魔法学院，可以是身份模拟器、角色养成或探索冒险。
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
    opening_npc_ids: Mapped[list] = mapped_column(JSON, default=list)
    opening_npc_locations: Mapped[dict] = mapped_column(JSON, default=dict)

    # 时段表，如 ["早", "中", "晚"]。空 = 这个模组不用时段，一切照旧。
    # 这里是默认值，建局时可以改，改完存进 session 自己那一份
    time_slots: Mapped[list] = mapped_column(JSON, default=list)

    # 主角的名字和出身由模组定死，玩家在建局界面改不动。默认关 = 玩家自己填，
    # 和加这一列之前一样。**开了也必须有那张主角模板卡才生效**：没有卡就没有
    # 「定死的值」可用，锁着一个空名字等于谁都开不了局
    lock_protagonist: Mapped[bool] = mapped_column(Boolean, default=False)

    # 构思向导上一次回填写进来的东西，供下次回填先摘掉。
    # 形状：{slots: [...], stats: [...], relation_stats: [...],
    #        location_ids: [...], npc_ids: [...], item_ids: [...], action_ids: [...]}
    # 没有它就分不清「这套数值是向导写的还是作者手打的」：重新生成再回填时
    # 只能一律追加，于是模组里叠出两套。名字按 trim 后比对（同 newNamed）
    wizard_state: Mapped[dict] = mapped_column(JSON, default=dict)

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

    # ── 对抗：判定时对上某个角色的能力数值，而不是对一个固定基准 ──
    # 空 = 数值制：跟人对碰时比裁判挑中的那一项的同名数值，每点 RATE_PER_POINT。
    # 非空 = 等级制：一律比这一项（stat_defs 里的某个 name），每级 rank_per_level。
    # 「等级制还是数值制」就是这一个字段空不空——刻意不另立一个三值枚举，
    # 否则要处理「等级制但没指定是哪一项」这种自相矛盾的状态。
    # 等级的**名字**（金丹期/元婴期）不在这儿，用那一项自己的 tiers
    rank_stat: Mapped[str] = mapped_column(String(100), default="")
    # 等级每差一级多少个百分点。默认 15：差一级就明显吃力，差三级基本只能靠
    # 险胜档蹭过去。注意它在 medium 档的可用量程只有 −3…+2（±4 就撞上
    # RATE_MIN/MAX 了），九阶天梯会在两头压平，编辑器里有阶梯预览提醒作者
    rank_per_level: Mapped[int] = mapped_column(Integer, default=15)

    # ── 上下文与模型参数 ──
    # 世界书关键词往回扫几条消息，含义同酒馆
    scan_depth: Mapped[int] = mapped_column(Integer, default=3)
    context_turns: Mapped[int] = mapped_column(Integer, default=20)
    # 整段 system 的总闸，按 rpg_budget.SECTION_BASE 等比摊给各块。默认值
    # 就是原来写死的那个 21500，所以不填 = 今天的行为一个字不变
    context_budget: Mapped[int] = mapped_column(Integer, default=21500)
    temperature: Mapped[float] = mapped_column(Float, default=0.9)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    # 期望叙事字数（软约束）。RPG 单轮该比酒馆长，所以给默认值而不是 0
    reply_length: Mapped[int] = mapped_column(Integer, default=300)

    model_ref: Mapped[str] = mapped_column(String(100), default="")
    fast_model_ref: Mapped[str] = mapped_column(String(100), default="")
    settlement_model_ref: Mapped[str] = mapped_column(String(100), default="")
    adjudication_model_ref: Mapped[str] = mapped_column(String(100), default="")
    suggestion_model_ref: Mapped[str] = mapped_column(String(100), default="")
    activity_model_ref: Mapped[str] = mapped_column(String(100), default="")
    offscreen_model_ref: Mapped[str] = mapped_column(String(100), default="")
    discovery_model_ref: Mapped[str] = mapped_column(String(100), default="")
    # 压缩旧剧情用。空 = 跟着 fast_model_ref 走，所以老库行为不变。
    # 单独拎出来是因为摘要和裁决的要求不一样：裁决要快要便宜，摘要错一次
    # 会把错的东西一路带到局终（它的输出会喂给下一次摘要）
    summary_model_ref: Mapped[str] = mapped_column(String(100), default="")
    # 把中文源文转成 danbooru tag 用。这一路输出是 tag 串、过白名单校验、
    # 而且转完要给用户过目能删，所以最便宜的模型就够——单独拎出来是因为它
    # 从前跟着 model_ref 走，白花叙事模型的钱。空 = 跟着 fast_model_ref 走
    image_model_ref: Mapped[str] = mapped_column(String(100), default="")
    # 长期记忆的向量召回用。**空 = 整条向量路关闭**，不另设开关：没配就是
    # 一次嵌入接口都不调，召回退回 BM25 + 词面两路，和今天完全一样。
    # 单独一个开关会多出「配了却关着」这种谁也说不清的状态
    embedding_model_ref: Mapped[str] = mapped_column(String(100), default="")

    # 推时段时写一句「别处的传闻」进大事记。**默认关**：开了之后「结束这个
    # 时段」就不再是零模型调用了，这个承诺写在文档、按钮提示和测试里
    offscreen_brief: Mapped[bool] = mapped_column(Boolean, default=False)

    # 勾上之后，AI 调度那次调用会顺带问一句「这个人有没有话想找玩家说」，
    # 有就挂进 session.npc_inbox 等玩家点开（见那一列的说明）。
    #
    # **不多花一次调用**：它复用 idle_npc_activities 已有的那一次，只是多一行
    # 输出。所以它的前提是角色勾了 ai_scheduled——没人被调度就没有留言，
    # 这里勾了也不会有任何事发生。
    #
    # 默认关，理由同 offscreen_brief 和 ai_scheduled：老模组的行为要逐字不变
    npc_initiative: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── 时段推进的两个提醒阈值 ──
    # 起因是「有时候会忘记跳过时段」。时钟原先只能手动拨，忘了按世界就冻住：
    # 作息表不换班、npc_places 永久盖住作者排的班、跨天恢复永远不发生。
    #
    # 一个时段最多几格**行动**（点动作/道具/技能/移动，纯对话不算）。攒满
    # 自动推一格。**0 = 关**，一格都不会自己走。
    # 只数行动是有意的：turn_count 对每条玩家消息无差别 +1，拿它当预算等于
    # 「话多的人时间流逝快」；而「世界真的动了」引擎自己就知道，不用问模型
    #
    # 新模组默认 3 而不是 0：默认 0 时时钟只有玩家主动按才走，而推时段又带
    # 跨天恢复，于是「歇一晚」成了零成本回血，数值消耗不构成任何压力。老模组
    # 存的那个 0 不动（迁移时就写进行里了），行为逐字不变
    slot_budget: Mapped[int] = mapped_column(Integer, default=3)
    # 纯对话攒到几条就把「结束这个时段」这颗按钮点亮。**只提醒，不推时间**——
    # 聊得久不等于世界该变，那种判断交给结算里 GM 的 scene_wrapped 提议。
    # 0 = 关
    chat_nudge: Mapped[int] = mapped_column(Integer, default=0)
    # 自由打字要不要吃掉一格行动。开着时**不是每条都吃**：只有结算里 GM 报
    # scene_wrapped（这一幕收尾了）的那一轮才算一格。闲聊三句不收尾就是 0 格，
    # 一次演完的事才算一格。
    #
    # 默认关：老模组行为逐字不变，而且这条开关会让 scene_wrapped 从「只点亮
    # 按钮」变成真的动时间，那是对 chat_nudge 那条注释的有意破例——破例得由
    # 作者自己开。模拟器和角色养成两档才需要它，探索冒险基本不用
    free_costs_slot: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── NPC 立绘出图设置 ──
    # {"workflow": "npc_portrait", "style": "photorealistic, realistic",
    #  "extra": "absurdres", "prompt_form": "sd_tags", "frame": "cg_wide"}
    # 全项可空，老模组是 {}。style / pose 存的是展开后的 tag 串而不是选项 key，
    # 这样后端和拼提示词的地方都不用认识前端那张风格表。
    # 题材**不存在这里**——module.genre 已经是主字段，出图时现读，两处存会不同步
    #
    # prompt_form: 'natural_zh'（缺省）或 'sd_tags'。光辉这类 SDXL 系工作流走
    #   CLIP-L 只认英文 Danbooru tag，Z-Image 走 Qwen-3-4B 吃中文，两种提示词
    #   形态不通用。**缺省必须等于中文**，否则老模组的图会悄悄全变样。
    # frame: imageFrames.ts 里的 key（存 key 是因为它还带 width/height 两个数字，
    #   展开成一个 tag 串装不下），出图时前端回表查出尺寸传进请求体。
    image_config: Mapped[dict] = mapped_column(JSON, default=dict)

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


class RpgInstructionPreset(Base):
    """常用 GM 指令：攒顺手的一段 GM 指令，换个模组也能拿来用。

    与 TavernInstructionPreset 分表，理由同 RpgRule：酒馆那批是按逐轮陪聊调的，
    RPG 这批要管数值、判定、结算，混一张表会让两边的列表互相污染。

    取用是**拷贝一次就断开**：模组只存 system_instruction 那段文本，不存 preset_id。
    存了 id 会看着像活链接，而实际没有任何代码顺着它回写（理由详见 RpgStatPreset）。

    没有 enabled：它从不被自动注入，只有作者点一下才填进表单，停用没有含义。
    """
    __tablename__ = "rpg_instruction_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgStatPreset(Base):
    """数值套装：作者攒顺手的一整套数值系统，换个模组也能拿来用。

    归属根是 user_id 不是 module_id（照 RpgRule 那套）：它从头到尾的全部用处
    就是「换个模组也能拿来用」，挂在某个模组下等于宣布它只属于那个模组。

    套用是**拷贝一次就断开**：这张表里没有任何模组 id，模组那边也不存套装 id。
    不是图省事——建局时存档里的数值是**按名字**从 stat_defs 快照下来的，而改名
    或删掉一项数值没有任何迁移逻辑：老存档里的旧键成孤儿、check_condition 缺键
    静默按 0 算。一条「改库→回写已建模组」的路会让改一个字就悄悄改坏别人正在
    玩的局，而且全程不报错。

    为什么和 RpgActionPreset 分两张表而不是一张加 kind 列：A 的数值配 B 的动作
    是明确要支持的用法，两边本来就各查各的列表，合表之后每次查询都要带 kind
    过滤，而数值那两列对动作套装永远是空的。

    为什么没有 enabled：RpgRule 有它是因为规则会被自动注入 prompt，需要「暂时
    不用但别删」。预设从来不被自动消费，只有作者主动点「套用」才动，停用没有
    任何含义。

    为什么只有 note 没有结构化的 genre：一个 genre 字段会诱使套用时顺手改掉模组
    的题材那一行，那是拷贝之外的隐式写入。note 只给作者在列表里认人用，
    永远不进 prompt。
    """
    __tablename__ = "rpg_stat_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str] = mapped_column(String(200), default="")

    # 形状与 RpgModule.stat_defs / relation_stat_defs 逐字一致，套用就是整份拷
    # 过去、中间不做任何转换——多一层映射就多一处两边会悄悄漂移的地方
    stat_defs: Mapped[list] = mapped_column(JSON, default=list)
    relation_stat_defs: Mapped[list] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgActionPreset(Base):
    """动作套装：一组调顺手的动作按钮，换个模组也能拿来用。

    归属根、拷贝断开、为什么不和 RpgStatPreset 合表、为什么没有 enabled、
    为什么只有 note：见 RpgStatPreset 的注释，逐条同样适用。

    actions 存整包，不建子表：库里一套动作永远是整体读写，拆子表只多一套 CRUD。
    """
    __tablename__ = "rpg_action_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str] = mapped_column(String(200), default="")

    # [{name, prompt_hint, effects, relation_effects, needs_target}]，
    # 即 RpgAction 去掉 requires。可用条件引用的是某个模组自己的剧情标记、道具名、
    # 角色名和时段，搬到别的模组一条都对不上，存进库只会变成「套完就永远不满足」
    # 的死条件——按钮永远灰着，作者还得回去一个个翻为什么。
    #
    # 也刻意不存 stat_names 之类的派生字段：它是 effects 键的派生物，存一份就会和
    # actions 漂移，缺哪些属性由前端当场算
    actions: Mapped[list] = mapped_column(JSON, default=list)
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

    # 这条叫什么。纯粹给人看：列表上认条目、游戏里那行诊断报「本轮生效了谁」。
    # 加它的直接理由是条件事件全是「常驻 + 无关键词」，原先诊断条上只能显示成
    # 一串「常驻」，分不清是哪条（见 RpgPlay 那行诊断）。空 = 回退到按关键词显示
    title: Mapped[str] = mapped_column(String(100), default="")
    # 触发关键词，逗号分隔
    keywords: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # 常驻词条：不看关键词，每轮都注入
    constant: Mapped[bool] = mapped_column(Boolean, default=False)
    # 插入深度：0 = 拼进 system；n>0 = 插到倒数第 n 条消息开头
    depth: Mapped[int] = mapped_column(Integer, default=0)
    # 只放一次。「她终于肯叫你名字了」这种一次性剧情，条件一直满足就会一直
    # 注入、让模型每轮重演一次「终于」。
    #
    # 放过的 id 记在 RpgSession.fired_entries 里，**不记在这一条上**——词条是
    # 模组资产、跨局共用，记在这儿会让第二局开局就少一段剧情
    once: Mapped[bool] = mapped_column(Boolean, default=False)

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
    # 自由文本，不是数字：「十七八岁」「三百岁」「看不出年纪」都得能写。
    # 每轮随长相一起注入（见 _one_npc）
    age: Mapped[str] = mapped_column(String(20), default="")
    avatar_url: Mapped[str] = mapped_column(String(300), default="")
    # 当前这张立绘用的随机种子，0 = 没记录（自己上传的、或者还没生成过）。
    # 只由生成接口写，不进 Create/Update schema——否则会被表单那份整体 PATCH 冲掉
    avatar_seed: Mapped[int] = mapped_column(Integer, default=0)
    # 只给这个人的出图设置。形状和 RpgModule.image_config 一模一样，但**是稀疏的**：
    # 某个 key 不在 = 这一项跟随模组，在 = 只这个人覆写。所以 {} 是常态，
    # 不是「没配置」的坏值——模组那份才是总览和默认，这里只放微调。
    # 合并规则在 services/rpg_image.py，前端同一套在 pages/Rpg/imageConfig.ts
    # ——一份配置在两处按不同规则合并，预览和实际出的图就不是一回事
    image_config: Mapped[dict] = mapped_column(JSON, default=dict)

    # npc = 世界里的人 / protagonist = 主角模板，开局时预填玩家角色。
    # 两者共用同一个卡片编辑器，不写两套
    role: Mapped[str] = mapped_column(String(20), default="npc")

    # 一句话简介，给作者在列表里认人用，也进提示词
    description: Mapped[str] = mapped_column(Text, default="")
    # 分栏档案，存中文键：背景故事 / 能力特长 / 关系网络（外貌不进这里，它有自己
    # 的字段）。老库里可能留着英文键，读的时候过 normalize_profile_sections
    profile_sections: Mapped[dict] = mapped_column(JSON, default=dict)
    # [{"user": ..., "assistant": ...}]，只作为文字引用进提示词
    dialogue_examples: Mapped[list] = mapped_column(JSON, default=list)

    persona: Mapped[str] = mapped_column(Text, default="")
    # 每轮都注入。原先按 npc_states 里的 met 只在首次见面时给，代价是见过面
    # 之后人去了别处、又被提到时模型手上没有长相，只能现编（见 _one_npc）
    appearance: Mapped[str] = mapped_column(Text, default="")

    # 常驻地点。等于 session.location 即视为在场
    location: Mapped[str] = mapped_column(String(100), default="")
    # 作息表：{"早": "大礼堂", "晚": "寝室"}。当前时段在这张表里有值就用它，
    # 没有（或整个表是空的）就落回 location。**不是第二个在场判据**——
    # 它只是给 location 换了个按时段取值的算法，谁在场仍然只有一种问法
    slot_locations: Mapped[dict] = mapped_column(JSON, default=dict)
    # 仅在这些时段执行随机移动；空列表保持旧行为，表示所有时段都可随机移动。
    random_movement_slots: Mapped[list] = mapped_column(JSON, default=list)
    # 随机移动只能去这几个地点（存地点名，同 slot_locations 的值和 at_location
    # 的口径）。空列表 = 不限制，可以去模组里任何地点，语义和上面那张时段表
    # 逐字一致。地点改名或删掉之后这里会留下对不上的名字，一律静默滤掉
    # （同 apply_tweak 对不上就跳过），但前端要把它显出来，否则作者不知道少了一格
    random_movement_places: Mapped[list] = mapped_column(JSON, default=list)
    # 额外触发词：人不在场但被提到也注入，匹配方式同世界书
    keywords: Mapped[str] = mapped_column(String(500), default="")

    # 勾上之后，这一轮没被提到的人会自己过日子：模型给她写一句「最近在做什么」，
    # 记在 session.npc_activities 里，下回见面时注入。**默认关**——它意味着
    # 每轮多一次模型调用，而这个模式此前只有玩家说话时才花钱
    ai_scheduled: Mapped[bool] = mapped_column(Boolean, default=False)
    random_movement: Mapped[bool] = mapped_column(Boolean, default=False)

    # 这个人的关系数值起点。空 = 按模组的 relation_stat_defs 取 initial；
    # 填了就覆盖对应项（「她一开始就恨你」）
    initial_state: Mapped[dict] = mapped_column(JSON, default=dict)
    relation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    relation_stat_names: Mapped[list] = mapped_column(JSON, default=list)

    # 这个人有多强：{"境界": 4, "剑术": 18}，键是模组 stat_defs 里的名字。
    # 判定时玩家不再对一个固定基准，而是对这里的数字（见 rpg_dice.resolve_rate）。
    #
    # **稀疏**：只给真会跟玩家对上的人填。不在表里 = 这一项不参与对抗，
    # 那一轮就只剩难度档位说话。所以 {} 是常态，老模组一个字不用改。
    # 0 是**合法值**（作者明写的「凡人」），和「没填」是两件事，读的时候
    # 一律用 is None 判，别用真值判。
    #
    # 刻意**不进 session.npc_states 快照**：这是作者定的「这个人本来有多强」，
    # 作者把 BOSS 从 5 级调到 8 级，已经开着的局跟着变才是他要的——正好和
    # npc_activities（存这一局发生的事）相反。而且 npc_states 里所有非 met
    # 的键都被当关系数字用，塞进去会被 clamp 到关系数值的上下限里
    ability_stats: Mapped[dict] = mapped_column(JSON, default=dict)
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


class RpgSkill(Base):
    """技能。和道具是同一类东西——点一下数值由引擎精确增减，AI 碰不到这个数。

    和道具的差别只有两处：技能不会用掉（没有 consumable），但有**冷却**和
    **可用条件**。条件格式抄 RpgAction.requires，一处写完三处共用。
    """
    __tablename__ = "rpg_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rpg_modules.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # 主动 / 被动。只用来分组显示；被动的 usable 设 false 就点不动
    category: Mapped[str] = mapped_column(String(20), default="主动")

    usable: Mapped[bool] = mapped_column(Boolean, default=True)
    # {"精力": -10, "怀疑度": 5}，键必须是 stat_defs 里有的名字
    effects: Mapped[dict] = mapped_column(JSON, default=dict)
    # 可用条件，格式同世界书/RpgAction.requires。不满足时前端置灰并显示原因
    requires: Mapped[dict] = mapped_column(JSON, default=dict)
    # 用完要歇几个回合。0 = 随便用
    cooldown: Mapped[int] = mapped_column(Integer, default=0)
    # 开局就会。没有的技能得靠剧情学（「新发现」那条路）
    start_with: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgTask(Base):
    """任务。小说侧「伏笔」在 RPG 这边的对应物：剧情里冒出来的待办，
    有人替玩家记着，AI 判断该收线了就弹窗问一句，**玩家点头才算完成**。

    这张表是**定义**（模组资产，跨局共用）。某一局进行到哪一步存在
    RpgSession.tasks 里，两者靠名字对上，同道具/技能那一套。
    """
    __tablename__ = "rpg_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rpg_modules.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # 「怎样才算办完」。这一句是判定的唯一依据，会原样喂给结算那步的模型
    objective: Mapped[str] = mapped_column(Text, default="")
    # 主线 / 支线 / 日常。只用来分组显示
    category: Mapped[str] = mapped_column(String(20), default="支线")
    # 办完之后的数值奖励，键必须是 stat_defs 里有的名字
    effects: Mapped[dict] = mapped_column(JSON, default=dict)
    # 开局就挂在待办上。没勾的要靠剧情接下（「新发现」那条路）
    auto_start: Mapped[bool] = mapped_column(Boolean, default=False)
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
    # 目标可以是不在跟前的人（手机、传讯这类远程渠道）。默认 False：
    # 「夸她」这种动作对象必须在场，放开等于允许隔着三条街摸头。
    # 后端本来就不校验在场（_resolve_engine 在全量角色表里按名字找 target_npc），
    # 所以这一列只影响前端给谁选、以及 needs_target 那条置灰判据
    target_anywhere: Mapped[bool] = mapped_column(Boolean, default=False)
    # 点了把目标挪到玩家身边（写 sess.npc_places）。「召见秘书」就是这个：
    # 原先只能指望结算模型自己想起来改位置，那是个概率。
    summons_target: Mapped[bool] = mapped_column(Boolean, default=False)

    # 分栏用的自由文本，如「经营」「人事」。空 = 归到「其他」那一栏。
    # 不做成外键表：作者手上一共十几个动作，为了分栏建一张表加一套 CRUD
    # 不值得，而自由文本改名就是改名，不用管孤儿引用
    group: Mapped[str] = mapped_column(String(50), default="")
    # 点一下推进一格时段。默认 False——老动作一格时间都不该多花，
    # 而模拟器/养成那套「一个指令吃一格」的节奏靠作者逐个勾
    cost_slot: Mapped[bool] = mapped_column(Boolean, default=False)
    # 限定只在这个地点可用。空 = 随处可用。
    # 存名字不存 location_id：全项目的地点引用都是按名字归一（RpgNpc.location、
    # RpgSession.location、move_by_name 都走 norm_name），这里存 id 会是唯一的例外
    at_location: Mapped[str] = mapped_column(String(100), default="")

    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RpgSession(Base):
    """一局游戏。世界的权威状态就存在这行上。"""
    __tablename__ = "rpg_sessions"

    operation_token: Mapped[str] = mapped_column(String(40), default="")
    operation_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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

    # 这一局已经会的技能：[{"name": "听风辨位", "cooldown_left": 0}]
    # 形状对齐 inventory，理由一样——按名字认，模组那边改了 id 也不影响这一局。
    #
    # 不进 STATE_FIELDS：冷却是引擎扣的，让结算那步整列覆写会把刚用掉的技能
    # 冷却抹回去。和 discoveries 一样单独写（见 rpg_turn._use_skill）
    skills: Mapped[list] = mapped_column(JSON, default=list)
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
    # 上一个「时间还没被描写过」的起跳点，形如「第 1 天 · 早」，空 = 没有待补的时间。
    # 推时段是纯引擎、不调模型，这一段天然没有叙事；不记一笔的话下一轮模型只看到
    # 新的时段名，会接着上一轮的场景往下写（见 rpg_context.time_jump_block）。
    # **必须进 SNAPSHOT_FIELDS**：读档回到推时段之前，这句提示不该还挂着
    time_jump_from: Mapped[str] = mapped_column(String(40), default="")
    # 上一幕发生在哪个地点，形如「织云阁」，空 = 没有待说的断场。
    # 和 time_jump_from 是同一个病的两面：地点总览点【移动到这里】是纯引擎瞬移
    # （move_by_name，零 LLM、不产生任何消息），这次离开在对话历史里一个字都不留，
    # 下一轮模型眼前仍是「上一幕的长篇正文 + 玩家的下一句」，接着离开时那一幕往下
    # 写（见 rpg_context.scene_break_block）。
    #
    # **只由纯引擎瞬移写**。走一整轮的移动（前端 moveByTurn → _resolve_engine 的
    # move_to 分支）自己会产出「你走过去」那段正文，模型读得到，再贴一块提示是重复。
    # **必须进 SNAPSHOT_FIELDS**：读档回到移动之前，这句提示不该还挂着
    scene_break_from: Mapped[str] = mapped_column(String(40), default="")
    # 这一格里已经用掉的行动数 / 说过的纯对话条数，都由 advance_slot 归零。
    # 前者攒到 module.slot_budget 就自动推一格，后者只用来点亮按钮。
    # **两个都必须进 SNAPSHOT_FIELDS**：它们会随回合自己变，漏了不报错，
    # 只会让读档之后的时段预算错位（见 routes/rpg.py 那张表上的通则）
    slot_actions: Mapped[int] = mapped_column(Integer, default=0)
    slot_chats: Mapped[int] = mapped_column(Integer, default=0)

    # 剧情开关，扁平不嵌套。模型对嵌套结构做增量改动极不可靠；扁平键值的
    # 合并语义唯一：同键覆盖、新键追加、值为 null 表示删除
    flags: Mapped[dict] = mapped_column(JSON, default=dict)
    # 每个 flag **第一次**立起来那天是第几天。{"聊过电机": 4}
    #
    # 单独一列而不是把 flags 变成 {值, 天数} 的嵌套：上面那条注释就是理由——
    # 模型对嵌套结构做增量改动极不可靠，而 flags 是它每轮都在写的东西。
    # 这一列模型碰不到，只有引擎在 apply_flags 里记，所以能安全地嵌套演进。
    #
    # 只记第一次：同一个 flag 被重复写 True 不刷新天数，否则「聊过之后第三天」
    # 会被一次无关的重复置位推到永远不到。删掉 flag 时这里也删——那件事等于
    # 没发生过，留着日期会让重新触发时立刻满足三天
    flag_days: Mapped[dict] = mapped_column(JSON, default=dict)
    # 这一局里已经放过的一次性词条 id（RpgWorldEntry.once）。[12, 31]
    #
    # 存 id 不存名字，同 npc_states——名字会改，id 不会。
    # 和 flag_days 是同一类：模型一个字都碰不到，只有引擎在 mark_fired 里记，
    # 所以能安全地这么存。
    #
    # **必须进 SNAPSHOT_FIELDS**：读档回到那件事发生之前，它就该能再放一次——
    # 这也是「重新武装」的唯一入口，界面上不另做按钮
    fired_entries: Mapped[list] = mapped_column(JSON, default=list)
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

    # 这一局里**被改写掉的外貌**。{"3": {"胸部": "服丰元玉乳散后长出，已定形"}}，
    # 外层键同 npc_states，内层是自由键值，值一律字符串。注入时紧贴
    # RpgNpc.appearance 之后，并明说以它为准（见 rpg_context._one_npc）。
    #
    # 为什么不并进 npc_notes：那张表满 NOTE_LIMIT 条就**淘汰最久没更新的那条**，
    # 而身体改造恰恰是写一次就再不刷新的——它永远排在淘汰队列最前面。温眠第 3
    # 天服药长出的乳房就是这么没的：经历里那条被 NPC_HISTORY_LINES=5 挤出窗口，
    # 卡上的 appearance 还写着平坦，于是模型每轮都照作者原文写。
    #
    # 为什么不直接改 RpgNpc.appearance：那是角色卡字段，作用域是**整个模组**。
    # 同一个模组能开好几局，写进卡里等于 B 局第一次见到她就已经是 A 局玩出来的
    # 样子。理由同 npc_activities，这一列因此和它一样挂在会话上。
    #
    # 满了**拒绝新的、保留旧的**，和 npc_notes 正好相反：那张表新的近况比旧的
    # 要紧（伤好了就该被盖掉），这张表的每一条都没有自己消失的理由，该由玩家
    # 决定划掉哪条（见 apply_npc_appearance）
    npc_appearance: Mapped[dict] = mapped_column(JSON, default=dict)

    # AI 调度的产物：{"3": "在图书馆翻了一下午旧报纸"}。键同 npc_states
    # （npc_id 的字符串），值是**一句**话，每个角色只有一个。
    #
    # 存在这一局而不是角色卡上：同一个模组可以开好几局，写进卡里等于把 A 局的
    # 玩法带到 B 局——玩家在 B 局第一次见到赫敏，她已经在复述 A 局的事了。
    # 和 npc_notes 分开同理，那张表是 GM 从叙事里读出来的近况，这张是调度替
    # 不在场的人编的行动，两个写手共用一个键空间迟早互相盖
    npc_activities: Mapped[dict] = mapped_column(JSON, default=dict)

    # 上面那句话按时段留下的短流水，形状同 npc_history：
    # {"3": [{"day": 4, "slot": "晚", "content": "在图书馆翻了一下午旧报纸"}]}。
    # 一个人最多 ACTIVITY_LOG_LINES 条，一格只留最后一句，满了丢最旧的。
    #
    # 为什么不直接往 npc_history 里追加（这是最先想到的做法，别再回头试）：
    # 经历那一列每条都过了结算的取证门禁——必须在正文里找得到原话，而且只有
    # **参与了本轮**的人才写得进去。调度写的是不在场的人、凭人设编出来的背景
    # 活动，一条正文依据都没有。混进去之后「玩出来的事」和「模型编的事」在
    # 同一条时间线上再也分不开，而经历是要喂回模型的，等于让它把自己编的
    # 背景当成发生过的事实接着编下去。
    #
    # **只给人看，不进 prompt**。它存在的理由是玩家按了一串「结束时段」之后
    # 想知道这几格她在忙什么——那几格没产生正文，经历里理所当然是空的。
    # 要注入的长期记忆已经有经历和里程碑两份，再加一份编出来的只会挤掉它们。
    #
    # 进 SNAPSHOT_FIELDS，理由同 npc_activities；不进 STATE_FIELDS，
    # 理由也同它：结算不碰这一列，写它的只有 apply_npc_activity 一个入口
    npc_activity_log: Mapped[dict] = mapped_column(JSON, default=dict)

    # 这一局里每个人身上过了什么事，只追加不覆盖：
    # {"3": [{"day": 4, "slot": "晚", "content": "在图书馆翻了一下午旧报纸"}]}。
    # 外层键同 npc_states，day/slot 由引擎在写入那一刻盖章，不信模型自己填的。
    #
    # 刻意不并进 npc_notes：那一列是「这个人**现在**什么样」（伤势、身上带着
    # 什么），同一个键写第二遍就是覆盖，因为它本来就只该有一份现值。经历没有
    # 「现值」——上次受伤和这次受伤是两件事，盖掉旧的等于把这个人走过的路删了。
    # 一个 append 撞上一个 upsert，永远是 upsert 赢，而且全程不报错。
    #
    # 对齐小说侧 Character.full_sheet["character_history"]（那边是 {chapter,
    # day, content}）；游戏侧没有「章」，用 day + slot 定位
    npc_history: Mapped[dict] = mapped_column(JSON, default=dict)

    # 关系里程碑：这一局里「关系真的拐了个弯」的时刻。
    # [{"day": 4, "slot": "晚", "type": "动心", "a": "你", "b": "赫敏",
    #   "content": "..."}]，类型限定在 rpg_settlement._MILESTONE_TYPES 那七个，
    # 逐字沿用小说侧 Memory(memory_type="relationship_milestone") 的那一套。
    #
    # 为什么不在 npc_history 上打个标记了事，三件事都不一样：
    #  1. 它跨两个人。挂进某一个人的经历里等于只从一边记，另一边那一格拿不到，
    #     而关系本来就是两边的事。
    #  2. 它要**常驻注入**。经历是「这阵子在忙什么」，人不在场就不用管；里程碑是
    #     这段关系**为什么长这样**的事实锚——缺了它，模型手上只有「好感 62」，
    #     写「她为什么会信你」时只能现编一段旧事，下一轮又不记得，于是每轮编一个新的。
    #  3. 预算和筛选规则不同：经历按人切、每人一小份；里程碑是全局共享的一小段。
    #     混在一起之后，话多的那个人的经历会把别人的里程碑挤掉。
    npc_milestones: Mapped[list] = mapped_column(JSON, default=list)

    # 不在场的人想找玩家说的话，等玩家点开才落成真消息：
    # [{"id": "a1b2...", "npc_id": 3, "text": "在门口等你，有话说",
    #   "day": 4, "slot": "晚", "place": "图书馆"}]
    #
    # 和 npc_activities 同一次调度调用产出（一次调用，多一行输出），但**必须
    # 分开存**：那一列是「她这一阵子在做什么」，每人只有一句、新的盖掉旧的；
    # 这一列是待玩家处理的**事件**，一个人可以攒好几条，而且处理掉就该消失。
    # 合成一列的话，「盖掉旧的」会把玩家还没看的留言悄悄吃掉。
    #
    # day/slot/place 是留言写下那一刻的快照，只用来在界面上说「她昨晚在图书馆
    # 找过你」，不参与任何判断——事后拿 sess 回查算的是「现在」，人早走了。
    #
    # **不进 STATE_FIELDS**（结算不碰它，否则玩家还没看的留言会被下一轮整列
    # 覆写掉），但**进 SNAPSHOT_FIELDS**（读档要跟着回滚，否则档读回三天前，
    # 侧栏还挂着一条三天后才写下的留言）。理由同 item_claims
    npc_inbox: Mapped[list] = mapped_column(JSON, default=list)

    # 地点近况：{"地窖": "门被你踹坏了，合不上"}，键是**地名**，值是一句话。
    #
    # 这不是第四个记忆格。记忆按格子分（玩家一格、每个 NPC 各一格，见 summary /
    # thread_summaries），再给地点开一格意味着摘要次数翻倍，而且和玩家那一格
    # 大面积重叠——你在地窖干的事本来就写在你自己那一份里。这一列只装
    # **留在这个地方本身、下次回来还看得见**的那一句：门踹坏了、桌子掀了、
    # 血迹还在。它是事实，不是叙事，所以一句话够了，也不需要压缩。
    #
    # 每个地点只有一句，新的直接盖掉旧的（同 npc_activities），理由也一样：
    # 这是「现在这儿什么样」，不是流水账。
    place_notes: Mapped[dict] = mapped_column(JSON, default=dict)

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
    npc_places: Mapped[dict] = mapped_column(JSON, default=dict)
    npc_random_places: Mapped[dict] = mapped_column(JSON, default=dict)

    # 谁跟着玩家走：[3, 7]，装的是 npc id。
    #
    # **只装 id，不记位置**：她的位置就是玩家的位置，由 npc_place 的取值链当场
    # 算出来（剧情 → 跟随 → 作息表 → 常驻地）。再存一份位置就等于开了第二个
    # 「她在哪儿」的真相，玩家一走动它就和 sess.location 分叉——而分叉的表现是
    # 「人明明跟在你身后，侧栏说不在这儿」。
    #
    # **绝不进 rpg_settlement.STATE_FIELDS / DOMAINS**：模型一个字都不许碰它，
    # 否则它就能随口给人永久加一个同伴，那正是上面那条注释要防的事。写入者只有
    # 两个：引擎从玩家那句话里认出来、侧栏的 /follow 接口。
    npc_followers: Mapped[list] = mapped_column(JSON, default=list)

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

    # 玩家那一格的滚动摘要：你亲身经历过的**全部**（你就是你自己故事的唯一
    # 目击者，不管当时谁在场，见 rpg_context.message_slots）。它永远注入
    # （见 rpg_context.summary_block），所以老库一个字都不会丢
    summary: Mapped[str] = mapped_column(Text, default="")
    summarized_upto_id: Mapped[int] = mapped_column(Integer, default=0)

    # 每个 NPC 自己那一格：{"5": "与柳如烟的长期记忆"} / {"5": 已压到的消息 id}。
    # 她在跟前时才注入她这一份——「和角色的对话单独存」就落在这两列上。
    # 键是 NPC id 的字符串（JSON 的键只能是字符串）
    thread_summaries: Mapped[dict] = mapped_column(JSON, default=dict)
    thread_upto: Mapped[dict] = mapped_column(JSON, default=dict)

    # 已经嵌进向量库的消息推到哪了（见 rpg_vectors.sync_session）。和上面两个
    # 指针一样，**回溯时必须跟着回退**——否则被删掉的「未来」还留在向量库里，
    # 检索得回来，那正是 RpgSave 注释里说的最难查的一类 bug
    vector_upto_id: Mapped[int] = mapped_column(Integer, default=0)

    # 结算顺带认出来的、模组里还没登记的人/地方/东西，等作者勾选：
    # [{"id": "a1b2...", "kind": "npc|place|item", "name": "老周", "hint": "正文原话", "message_id": 88}]
    #
    # 只是待办，不是游戏状态——所以不进 STATE_FIELDS（结算不碰它），
    # 但进 SNAPSHOT_FIELDS（读档要跟着回滚，否则档读回去了，角标还挂着
    # 一条指向已经不存在的剧情的发现）。
    #
    # 作者点「加入」之后才真的建行；建出来的 NPC/地点/道具是模组资产，
    # 回滚不会撤销它们（和存档是两回事，模组本来就跨局共用）
    discoveries: Mapped[list] = mapped_column(JSON, default=list)

    # 这一局的待办清单：
    # [{"name": "去后巷见老周", "desc": "...", "status": "open|done|failed",
    #   "task_id": 3|None, "source": "module|story",
    #   "opened_turn": 4, "closed_turn": 0}]
    #
    # task_id 指向模组里的定义（剧情里临时接下的没有定义，就是 None）。
    # 不进 STATE_FIELDS：**完成与否必须玩家点头**，让结算那步整列覆写
    # 等于模型可以自说自话地把事办了
    tasks: Mapped[list] = mapped_column(JSON, default=list)

    # 模型提议「这桩事看着办完了」，等玩家确认：
    # [{"id": "a1b2...", "name": "去后巷见老周", "action": "done|failed",
    #   "reason": "正文原话", "message_id": 88}]
    #
    # 提议和事实分开存，和小说侧伏笔回收是同一个做法：模型只有建议权。
    # 形状刻意对齐 discoveries，前端那套勾选 UI 能照抄
    task_proposals: Mapped[list] = mapped_column(JSON, default=list)

    # 结算说「你拿到了一件新东西」，等玩家认领：
    # [{"id": "a1b2...", "name": "固元丹", "qty": 1, "note": "...",
    #   "hint": "正文原话", "message_id": 88, "known_item_id": 12|None}]
    #
    # 为什么不直接进 inventory：这是模型从正文里读出来的判断，读歪的路子太多
    # （把别人手里的东西读成你的、把你明确拒绝的读成收下）。而背包只有「加」和
    # 「用掉」两个口子，东西一旦进去，玩家就没有「这不是我拿的」这个出口了。
    #
    # 只拦「正数 + 背包里还没有同名」：负数（用掉、交出、失去）永远直接应用，
    # 拦下来等于把已经写出来的剧情推回去；已有同名的直接 +qty，否则捡第二根箭
    # 还要再点一次确认。
    #
    # 和 discoveries 一样是待办而不是游戏状态：**不进 STATE_FIELDS**（结算不碰
    # 它，否则玩家还没处理的会被下一轮整列覆写掉），但**进 SNAPSHOT_FIELDS**
    # （读档要跟着回滚，否则档读回去了，道具格上还挂着一件来自已经不存在的
    # 剧情的东西）
    item_claims: Mapped[list] = mapped_column(JSON, default=list)

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
    turn_request: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    before_save_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
    settlement: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
