"""RPG 的数值系统：定义解析、条件求值、状态应用。纯函数，无 IO，不碰 LLM。

这个模式的地基是「数值在动、跨过某条线就解锁新东西」，所以本模块是整套
RPG 最该守住的地方：数值的上下界、归零后果、关系数值的独立性都在这儿。

条件求值器 check_condition 一处写完三处共用——世界书的 trigger_condition、
动作按钮的 requires、地点的 enter_requires。它们是同一个东西，没理由写三遍。

模型提议的改动一律经过这里再落库：AI 给 -999 也只会被夹到下界，而且会留一条
warning 给玩家看见。有定义的数值（道具、动作按钮、移动）根本不走模型，
数字是死的。
"""

# 数值定义缺字段时的兜底。initial 给 0 而不是报错——
# 模组作者填一半就去开局是很正常的事
DEFAULT_MIN = 0
# 归零后果：无 = 什么都不做 / 死亡 = 这一局结束 / 标记 = 写一条 flag 让剧情自己接
ON_ZERO_NONE, ON_ZERO_DEAD, ON_ZERO_FLAG = "无", "死亡", "标记"
# 填满后果：无 = 什么都不做 / 标记 = 写一条 flag。没有「死亡」那一档——
# 填满致死没有语义，要那个效果就用 on_zero 表达
ON_FULL_NONE, ON_FULL_FLAG = "无", "标记"
# display：条 = 进度条（要有 max）/ 数字 = 纯数字 / 隐藏 = 玩家看不见的幕后计数器
DISPLAY_BAR, DISPLAY_NUMBER, DISPLAY_HIDDEN = "条", "数字", "隐藏"
# 格子 = 一格一格的进度条。配 on_full = 标记 就是进度时钟：平滑条看不出
# 「再推一次就满」，而那正是时钟唯一想说的事。纯显示，后端一律不看它
DISPLAY_CELLS = "格子"

# flags 最多留这么多条。模型很爱往里塞「刚刚打了个喷嚏」这种一次性状态，
# 不设上限迟早把 system 撑爆
FLAG_LIMIT = 40

# 大事记最多留这么多条。同 FLAG_LIMIT：不分线之后它要撑起跨线的记忆，
# 塞满了小事就把真正传开的事挤出去了
CHRONICLE_LIMIT = 40

# 去过的地点最多记这么多个。同 FLAG_LIMIT 的理由：结算模型能把玩家「移动」到
# 任何一个它现编的地名上，不设上限就没边了
VISITED_LIMIT = 100

# 每个 NPC 最多记几条近况、每条最长多少字。比 FLAG_LIMIT 紧得多：这些行会
# 原样画在玩家盯着看的角色卡上，也会每轮注入那个人的设定块（预算只有
# NPC_TOKEN_BUDGET，全体在场角色分）。模型很爱记「情绪：有点紧张」
NOTE_LIMIT = 10
NOTE_CHARS = 60

# 每个 NPC 最多被改写几处外貌、每处长多少字。比 NOTE_LIMIT 松：这不是「今天怎么了」，
# 而是一个人的身体被永久改动过的地方，一局下来也就那么几处（药师改造、断手、
# 毁容、纹身）。40 字足够写清一处变化，比 NOTE_CHARS 短是因为注入时它紧贴
# appearance，而那张卡还要跟在场所有人分 NPC_TOKEN_BUDGET
APPEARANCE_LIMIT = 12
APPEARANCE_CHARS = 40

# AI 调度的角色「最近在做什么」，每个角色只有一句，所以比 NOTE_CHARS 更短：
# 它和近况并排画在同一张卡上，长了两行挤在一起
ACTIVITY_CHARS = 40

# 那句话按时段留下的短流水，一个人最多几条（见 models.npc_activity_log）。
# 12 条约合四个游戏日。不设成「和经历一样不封顶」：经历每一条都过了取证门禁
# （必须在正文里找得到原话），这一列是模型随口编的背景活动，攒成一本无限长的
# 流水只会把真正玩出来的那几条淹掉
ACTIVITY_LOG_LINES = 12

# NPC 留言。比 ACTIVITY_CHARS 宽一点：它会原样落成一条真消息给玩家看，
# 太短会像半句话被截断。INBOX_PER_NPC 是一个人最多攒几条——不封顶的话，
# 玩家一直不理她，红点上的数字会涨到没边，而那些话早就过时了。
# INBOX_LIMIT 是这一局总共几条，理由同 PLACE_LIMIT
INBOX_CHARS = 60
INBOX_PER_NPC = 3
INBOX_LIMIT = 20

# 地点近况，每个地点一句。同 ACTIVITY_CHARS 的理由：它跟在地点描述后面
# 进【场面】块，长了就把作者写的那段挤没了。
# PLACE_LIMIT 是这一局总共记几个地方——玩家逛过的地方会一直涨，不封顶的话
# 它就成了第二份大事记（而大事记有自己的上限，理由一样）
PLACE_CHARS = 40
PLACE_LIMIT = 30

# 数值「影响」那段最长多少字。这是**提示词预算**的上限，不是排版上限——它每轮
# 随数值表发一遍，数值多的模组会把上下文吃掉。之前是 30，太紧：像「金钱」这种
# 要说清用途的数值，一句话写不完就被切在半句上，模型读到半句比没有还糟。
# 档位标签是另一回事：它跟在侧栏每个数字后面画出来（StatBar），长了就换行，所以照旧紧。
EFFECT_CHARS = 150
TIER_LABEL_CHARS = 6
# 档位说明不上界面——编辑器里那一栏自己写着「只给模型看，玩家看不见」，
# 它唯一的去处是 _meaning_block。所以它跟 label 不是一类，跟 effect 才是一类，
# 之前 20 字是照着 label 一起定的，属于顺手：「70 起 出轨妇=会主动说脏话但还会脸红」
# 这种一句话就到头了，而档位说明恰恰是最该写清的那句——数值的含义靠 effect，
# 到了这个数**具体是什么表现**只有它能说。同 EFFECT_CHARS 的理由封在预算上：
# 一档一句，档数乘上去才是每轮的开销，所以给得比 effect 保守
TIER_NOTE_CHARS = 60

# 引擎自己写进大事记的两类行。前缀是**合并的判据**——认不出「上一行也是
# 移动」的话，玩家在镇上连点五个地点就会刷出五条「你去了 X」
MOVE_TAG = "〔移动〕"
DAY_TAG = "〔日期〕"
# 开场那一幕也进大事记，理由见 api/routes/rpg.py 的建局处。只取开头这么多字：
# 大事记是一行一条的硬事实，整段旁白塞进去会常驻吃掉外场那点预算
OPENING_TAG = "〔开场〕"
OPENING_CHARS = 120

# 外场简报（见 agents/rpg_turn.offscreen_brief）。用「别处」不用「外场」：
# 注入时那一整块块的标题就叫【外场】，行内再挂一个同名标签等于说两遍
OFFSCREEN_TAG = "〔别处〕"
OFFSCREEN_CHARS = 40

# 背包里同名道具的模糊匹配：去空格后比对。模型写「铁 钥匙」很常见
_NORMALIZE_TABLE = str.maketrans("", "", " 　\t")

_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


# 待办的三种状态。只有 open 会注入上下文、只有 open 能被模型提议收线
TASK_OPEN = "open"
TASK_DONE = "done"
TASK_FAILED = "failed"
DAILY_TASK_CATEGORY = "日常"


def _num(value, fallback=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def norm_name(text) -> str:
    return str(text or "").translate(_NORMALIZE_TABLE).strip().lower()


# 角色名里的间隔号。只在人名比对时去掉，不进 norm_name——背包那边的
# 「铁-钥匙」和「铁钥匙」是不是一件东西，是另一个问题，别顺手一起改
_NAME_SEPS = str.maketrans("", "", "·•・.-_、,，")

# 半个名字最少要这么长才敢认。一个字的「李」能撞上一整屋人
_MIN_PARTIAL = 2


def match_npc(name, npcs):
    """按名字找人，允许模型只写一半。返回角色对象，认不出就是 None。

    模型眼前的【在场】块写的是全名，但中文里没人会通篇写「赫敏格兰杰」，
    它就是会写「赫敏」。只认全等的话，每一轮都掉一条「找不到角色「赫敏」」，
    关系和近况全部白算。

    放宽只放到「一头对齐」为止：全等 → 去掉间隔号再全等 → 一方是另一方的
    前缀或后缀（短的那头至少两个字）。而且**必须只对上一个人**：模组里常有
    三个「村民」，认错人比不认更糟——关系数字会记到另一个人头上，作者事后
    根本查不出来。对上两个就当没对上，照旧发警告。
    """
    people = list(npcs or [])
    key = norm_name(name)
    if not key:
        return None

    exact = [n for n in people if norm_name(n.name) == key]
    if exact:
        # 同名的人折叠成最后一个，沿用既有行为（relations 一直如此）
        return exact[-1]

    bare = key.translate(_NAME_SEPS)
    if not bare:
        return None
    same = [n for n in people if norm_name(n.name).translate(_NAME_SEPS) == bare]
    if same:
        return same[-1]

    hits = []
    for npc in people:
        full = norm_name(npc.name).translate(_NAME_SEPS)
        if not full or min(len(full), len(bare)) < _MIN_PARTIAL:
            continue
        if full.startswith(bare) or full.endswith(bare) \
                or bare.startswith(full) or bare.endswith(full):
            hits.append(npc)
    return hits[0] if len(hits) == 1 else None


def match_place(name, known):
    """把模型写的地名对回模组地点表里的真名字。对不上就原样返回。

    模型爱给地名加修饰：模组里叫「藏经阁」，它写「外门藏经阁」。这一个字的
    差别会把整条在场判定打断——`here_npcs` 是按地名**全等**比的，于是站在
    同一间屋里的人全部算作不在场：那一轮的关系、近况一条都记不下，侧栏说
    「这里没有别人」，地图上「你在这里」谁也不亮，地点总览里更找不到这个
    地方，玩家连走回去纠正的入口都没有。

    只放宽到「真名字整个包在模型写的那串里」为止（藏经阁 ⊂ 外门藏经阁），
    反过来不认：模组里只有「藏经阁顶层」而模型写「藏经阁」时，把人塞到
    顶层去是凭空编造。对上多个取最长的，「阁」那种一个字的短名不参与。

    非字符串原样退回，**不能顺手 str() 一下**：模型偶尔把值写成
    {"地点": "宿舍"}，而 apply_npc_place 正是靠「这不是字符串」把它丢掉的；
    在这里先转成字符串，那道拦截就永远拦不到了
    """
    if not isinstance(name, str):
        return name
    raw = name.strip()
    key = norm_name(raw)
    if not key:
        return raw
    names = [str(n or "").strip() for n in (known or [])]
    for real in names:
        if norm_name(real) == key:
            return real
    hits = [
        real for real in names
        if len(norm_name(real)) >= _MIN_PARTIAL and norm_name(real) in key
    ]
    return max(hits, key=len) if hits else raw


# ── 数值定义 ──────────────────────────────────────────────────────────────

def def_map(defs) -> dict[str, dict]:
    """[{name, ...}] → {name: def}。没名字的条目丢掉，不报错。"""
    out: dict[str, dict] = {}
    for item in defs or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            out[name] = item
    return out


def clamp(spec: dict | None, value) -> int:
    """按定义夹住一个值。max 为 None 表示无上限（钱、声望）。"""
    spec = spec or {}
    num = _num(value)
    low = _num(spec.get("min"), DEFAULT_MIN) if spec.get("min") is not None else DEFAULT_MIN
    if num < low:
        num = low
    high = spec.get("max")
    if high is not None:
        top = _num(high, num)
        if num > top:
            num = top
    return num


def cap_delta(specs: dict[str, dict], delta) -> tuple[dict, list[str]]:
    """把一轮的变化幅度夹进作者定的 step_max。返回（夹过的 delta，提示）。

    和 clamp 分开是因为两者夹的不是一回事：clamp 夹的是**结果**（好感不能超过
    100），这里夹的是**一次能动多少**（一轮最多 ±3）。只有上限没有幅度限制时，
    模型一句「她彻底原谅了你」就能把好感从 0 拉到 100，作者定的那条成长曲线
    直接作废——而提示词里那句「一轮一般在 -3 到 +3 之间」是软的，不守也没人管。

    **只夹模型提议的那一路**：动作和道具的 effect 是作者自己写死的数字，
    夹了就是改他的设计。所以这个函数只在 apply_state_delta 里调，
    rpg_turn 的引擎那条路（_use_item / _run_action）不经过它。

    step_max 没写 = 不限（老模组行为不变）。写 0 = 这一项模型一点都不许动，
    只能靠动作和道具改——这是作者能表达的一个合理意思，所以不当成「没写」。
    """
    if not isinstance(delta, dict):
        return {}, []
    out: dict = {}
    warnings: list[str] = []
    for name, amount in delta.items():
        limit = (specs.get(str(name or "").strip()) or {}).get("step_max")
        # bool 是 int 的子类，True 会被当成 1 —— 挡在这里，别让它进 _num
        if limit is None or isinstance(amount, bool) or not isinstance(amount, (int, float)):
            out[name] = amount
            continue
        top = abs(_num(limit))
        want = _num(amount)
        got = max(-top, min(top, want))
        if got != want:
            warnings.append(f"{name} 这一轮只动了 {got}（本来要动 {want}，每轮上限 {top}）")
        out[name] = got
    return out, warnings


# 等级一轮最多升几级。刻意**只夹上行**：修为被废从 8 掉到 0 是正当的剧情，
# 而「打赢一场就从练气飞到元婴」不是。cap_delta 的 step_max 是对称的，
# 所以这一条不能借它来实现
RANK_GAIN_MAX = 1


def rank_stat_of(module) -> str:
    """模组的等级项名字。空串 = 数值制。

    用 getattr 是因为结算那边传的是 working 副本、测试里的 module 常是手搓
    对象，两种都可能没有这个属性（同下面 stat_defs 的写法）。
    """
    return str(getattr(module, "rank_stat", "") or "").strip()


def cap_rank_gain(module, delta) -> tuple[dict, list[str]]:
    """等级这一项一轮最多升 RANK_GAIN_MAX 级。只夹正的那一头。

    作者自己在这一项上填了 step_max 就听他的（含填 0 = 一点都不许动）——
    那时 cap_delta 会接手，这里不再插手。数值制（rank_stat 为空）一律不动。
    """
    if not isinstance(delta, dict):
        return {}, []
    rank = rank_stat_of(module)
    if not rank or rank not in delta:
        return dict(delta), []
    spec = def_map(getattr(module, "stat_defs", None)).get(rank) or {}
    if spec.get("step_max") is not None:
        return dict(delta), []
    amount = delta[rank]
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return dict(delta), []
    want = _num(amount)
    if want <= RANK_GAIN_MAX:
        return dict(delta), []
    out = dict(delta)
    out[rank] = RANK_GAIN_MAX
    return out, [f"{rank} 这一轮只升了 {RANK_GAIN_MAX}（本来要升 {want}，一轮最多 {RANK_GAIN_MAX} 级）"]


def tier_list(spec: dict | None) -> list[dict]:
    """一个数值的分档表，洗干净并按下界排好序：[{at, label, note}]。

    只写一个下界 at、不写区间：区间让作者留得出空隙和重叠，落进空隙就是
    「没有档」、落进重叠就是「两个档」，而且都不报错。单下界让这两件事不可能。

    这里排序而不是信作者填的顺序——编辑器不强制排序，而「取第一个够得上的」
    会让乱序的表匹配到错的档。字数在这儿就截掉，读的人不必各自记上限。
    """
    out = []
    for tier in (spec or {}).get("tiers") or []:
        if not isinstance(tier, dict):
            continue
        # 一行填歪了（at 还空着）不该把整张档表废掉，跳过它就行。必须用 None
        # 兜底而不是 0：0 是个合法的下界，拿 0 兜底会把没填完的那一行变成一个
        # 永远匹配得上的最低档
        at = _num(tier.get("at"), None)
        if at is None:
            continue
        out.append({
            "at": at,
            "label": str(tier.get("label") or "").strip()[:TIER_LABEL_CHARS],
            "note": str(tier.get("note") or "").strip()[:TIER_NOTE_CHARS],
        })
    out.sort(key=lambda t: t["at"])
    return out


def tier_of(spec: dict | None, value) -> dict | None:
    """当前落在哪一档。at <= value 里 at 最大的那一档，都不够就 None。

    值低于最低档返回 None：无上限的钱、下界是负数的数值、只填了一档的表全都
    走这条路，不需要各自特例。
    """
    num = _num(value)
    hit = None
    for tier in tier_list(spec):
        if tier["at"] <= num:
            hit = tier
        else:
            break
    return hit


def init_stats(defs) -> dict[str, int]:
    """按定义生成开局数值表。"""
    return {
        name: clamp(spec, spec.get("initial", 0))
        for name, spec in def_map(defs).items()
    }


def init_relation(defs, overrides=None, names=None) -> dict[str, int]:
    """一个角色的关系数值起点。overrides 是 RpgNpc.initial_state，
    只覆盖定义里有的键——模组改了定义之后，角色卡上的旧键不该复活。
    """
    over = overrides if isinstance(overrides, dict) else {}
    selected = {str(name).strip() for name in (names or []) if str(name).strip()}
    out = {}
    for name, spec in def_map(defs).items():
        if selected and name not in selected:
            continue
        raw = over[name] if name in over else spec.get("initial", 0)
        out[name] = clamp(spec, raw)
    return out


def ensure_relation_states(module, sess, npcs=()) -> bool:
    """为后来才开启关系数值的 NPC 补齐本局初始值。

    开局时关闭关系数值的 NPC 不会进入 ``npc_states``。作者之后再打开开关时，
    既要保留已经存在的数值，也要把新增的关系项按角色卡初始值补进来。
    """
    states = dict(sess.npc_states or {})
    changed = False
    for npc in npcs or ():
        if getattr(npc, "relation_enabled", None) is False:
            continue
        defaults = init_relation(
            module.relation_stat_defs,
            getattr(npc, "initial_state", None),
            getattr(npc, "relation_stat_names", None),
        )
        if not defaults:
            continue
        key = str(npc.id)
        state = dict(states.get(key) or {})
        for name, value in defaults.items():
            if name not in state:
                state[name] = value
                changed = True
        if state and key not in states:
            changed = True
        if state:
            states[key] = state
    if changed:
        sess.npc_states = states
    return changed


def for_check_stats(defs) -> list[str]:
    """能拿来判定的数值名。资金不行，敏捷可以。"""
    return [n for n, spec in def_map(defs).items() if spec.get("for_check")]


def visible_defs(defs) -> list[dict]:
    """玩家能看见的那些。隐藏项用来放幕后计数器，不进面板。"""
    return [
        spec for spec in def_map(defs).values()
        if spec.get("display") != DISPLAY_HIDDEN
    ]


# ── 条件求值：世界书 / 动作按钮 / 地点入口共用 ────────────────────────────

# 关系条件里「不指定是谁」的写法。名字写这个，就没有哪个角色会跟它重名。
# 判据是**任意一个**角色达标（见 check_condition），不是全部
ANY_NPC = "*"


def _relation_value(sess, npc, stat):
    """这个角色此刻的这项关系数值。没在追踪就是 None——和「值等于 0」是两回事，
    前者该报「没有追踪」，后者才是真的不满足。"""
    if getattr(npc, "relation_enabled", None) is False:
        return None
    state = (sess.npc_states or {}).get(str(npc.id)) or {}
    return _num(state[stat]) if stat in state else None


def check_condition(cond, sess, npcs=None) -> tuple[bool, str]:
    """条件是否成立，返回 (成立, 不成立的原因)。

    语义唯一：条件是「附加约束」，列出来的每一条都要满足。空条件恒成立。
    原因串直接给玩家看（「精力不够」），所以写成人话而不是表达式。
    """
    if not isinstance(cond, dict) or not cond:
        return True, ""

    # 时段：列出来的就是「允许的时段」，! 前缀取反（同 flags 的写法）。
    # 没设时段时判不成立而不是放行——放行会让「只有晚上开」的门永远开着，
    # 而作者根本查不出来。同 relations 分支「名字对不上就算不成立」的理由
    slots = cond.get("slots")
    if slots:
        now = str(getattr(sess, "slot", "") or "").strip()
        if not now:
            return False, "这个模组没有设定时段"
        allow = [str(s).strip() for s in slots if not str(s).startswith("!")]
        deny = [str(s)[1:].strip() for s in slots if str(s).startswith("!")]
        if now in deny:
            return False, f"{now}不能做这件事"
        if allow and now not in allow:
            return False, f"只有{'、'.join(allow)}能做这件事（现在是{now}）"

    day_rule = cond.get("day")
    if isinstance(day_rule, dict) and day_rule:
        op = _OPS.get(str(day_rule.get("op") or ">=").strip())
        have = _num(getattr(sess, "day", 1), 1)
        if op is not None and not op(have, _num(day_rule.get("value"), 1)):
            return False, f"第 {have} 天不满足（需要 {day_rule.get('op')} {day_rule.get('value')}）"

    stats = sess.stats or {}
    for name, rule in (cond.get("stats") or {}).items():
        if not isinstance(rule, dict):
            continue
        op = _OPS.get(str(rule.get("op") or ">=").strip())
        if op is None:
            continue
        want = _num(rule.get("value"))
        have = _num(stats.get(name))
        if not op(have, want):
            return False, f"{name}不满足（当前 {have}，需要 {rule.get('op')} {want}）"

    # 关系条件按角色名写，这里转成 id 去 npc_states 里查。
    # 名字对不上就算不成立——静默放行会让「好感≥50」的词条在打错名字时
    # 每轮都注入，比直接不生效难查得多
    #
    # 名字写 ANY_NPC 是「不指定是谁」，**任意一个**角色达标就算成立。它在动作上
    # 自动变成「你这一轮选中的那个人」——_action_gate 喂进来的 npcs 只有那个目标；
    # 技能、地点、世界书喂的是全体，那时它才是「随便哪个角色」
    by_name = {norm_name(n.name): n for n in (npcs or [])}
    for rule in cond.get("relations") or []:
        if not isinstance(rule, dict):
            continue
        who = str(rule.get("npc") or "").strip()
        op = _OPS.get(str(rule.get("op") or ">=").strip())
        if op is None:
            continue
        stat = str(rule.get("stat") or "").strip()
        want = _num(rule.get("value"))
        if who == ANY_NPC:
            for npc in npcs or []:
                have = _relation_value(sess, npc, stat)
                if have is not None and op(have, want):
                    break
            else:
                return False, f"没有角色的{stat}满足（需要 {rule.get('op')} {want}）"
            continue
        npc = by_name.get(norm_name(who))
        if npc is None:
            return False, f"找不到角色「{who}」"
        have = _relation_value(sess, npc, stat)
        if have is None:
            return False, f"{who}没有追踪关系数值「{stat}」"
        if not op(have, want):
            return False, f"{who}的{stat}不满足（当前 {have}，需要 {rule.get('op')} {want}）"

    flags = sess.flags or {}
    for key in cond.get("flags") or []:
        name = str(key or "").strip()
        # 取反前缀：写「!已经拿到钥匙」表示这条 flag 不能立
        if name.startswith("!"):
            if flags.get(name[1:].strip()):
                return False, f"「{name[1:].strip()}」已经发生了"
        elif not flags.get(name):
            return False, f"还没有「{name}」"

    # 「某件事之后 N 天」。上面 day 那条是绝对天数（第 10 天开门），这条是相对的
    # ——AI 推进的剧情里没有写死的时间线，能锚的只有「那件事发生的那天」。
    # 天数由引擎在 advance_slot 里推，跟模型怎么写剧情无关，所以这个锚是可靠的。
    #
    # flag 没立过、或立过但没记日期（加 flag_days 这一列之前的老局），都判不成立：
    # 引擎不知道那天是哪天，放行等于凭空满足一个本该等待的条件
    flag_days = getattr(sess, "flag_days", None) or {}
    for rule in cond.get("after_days") or []:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("flag") or "").strip()
        if not name:
            continue
        wait = _num(rule.get("days"), 0)
        if not flags.get(name):
            return False, f"还没有「{name}」"
        since = flag_days.get(name)
        if since is None:
            return False, f"没记下「{name}」是哪天发生的"
        left = _num(since, 1) + wait - _num(getattr(sess, "day", 1), 1)
        if left > 0:
            return False, f"「{name}」之后还要等 {left} 天"

    if cond.get("items"):
        owned = {norm_name(it.get("name")) for it in (sess.inventory or []) if isinstance(it, dict)}
        for want in cond["items"]:
            if norm_name(want) not in owned:
                return False, f"没有「{str(want).strip()}」"

    return True, ""


# ── 状态应用 ──────────────────────────────────────────────────────────────

def effect_cost_reason(sess, effects, defs=()) -> str:
    specs = def_map(defs)
    for name, amount in (effects or {}).items():
        cost = _num(amount)
        minimum = _num((specs.get(name) or {}).get("min"), 0)
        if cost < 0 and _num((sess.stats or {}).get(name)) + cost < minimum:
            return f"{name}不足，需要至少 {minimum - cost}"
    return ""


def apply_stats(module, sess, delta) -> list[str]:
    """玩家数值增减。delta 是 {名字: 增量}，返回 warning 列表。

    定义里没有的键一律拒绝并 warning——模型很爱自创「疲劳度」，
    静默接受会让数值表长出玩家从没定义过的项。
    """
    specs = def_map(module.stat_defs)
    stats = dict(sess.stats or {})
    warnings: list[str] = []
    for name, amount in (delta or {}).items():
        key = str(name or "").strip()
        spec = specs.get(key)
        if spec is None:
            warnings.append(f"忽略了没定义的数值「{key}」")
            continue
        want = _num(stats.get(key)) + _num(amount)
        got = clamp(spec, want)
        if got != want:
            warnings.append(f"{key} 被限制在 {got}（本来要改成 {want}）")
        stats[key] = got
    # 整个赋回去才会被标脏，原地改 JSON 列不会触发更新
    sess.stats = stats
    return warnings


def apply_relations(module, sess, npc_id: int, delta) -> list[str]:
    """对某个角色的关系数值增减。每个角色各持一份，互不影响。"""
    specs = def_map(module.relation_stat_defs)
    states = dict(sess.npc_states or {})
    key = str(npc_id)
    if key not in states or not any(name in (states.get(key) or {}) for name in specs):
        return [f"这个角色没有启用关系数值，忽略了本次变化"]
    state = dict(states.get(key) or {})
    warnings: list[str] = []
    for name, amount in (delta or {}).items():
        stat = str(name or "").strip()
        spec = specs.get(stat)
        if spec is None:
            warnings.append(f"忽略了没定义的关系数值「{stat}」")
            continue
        want = _num(state.get(stat)) + _num(amount)
        got = clamp(spec, want)
        if got != want:
            warnings.append(f"{stat} 被限制在 {got}（本来要改成 {want}）")
        state[stat] = got
    states[key] = state
    sess.npc_states = states
    return warnings


def apply_npc_notes(sess, npc_id: int, delta) -> list[str]:
    """GM 这一局记下的某个人的近况。自由键值，作者没定义过任何一个键。

    合并语义同 flags：同键覆盖、新键追加、值为 null 表示这条不再成立、删掉。
    整份 delta 是 null 表示把这个人的记录全清掉。

    值一律转成字符串：模型迟早会写 {"伤势": ["左肩","右腿"]} 或者塞个嵌套
    字典进来（flags 上就常年如此），而一个裸字典交给 React 当子节点会把
    整页白屏——NpcSheet 上面没有 error boundary。

    满了淘汰**最久没被改过的那条**：删掉再追加，让刚写的移到末尾，同
    note_visited。照 apply_flags 那种「按插入顺序砍最早的」在这里正好反了——
    dict 重新赋值不会挪动键的位置，于是每轮都在刷新的「伤势」永远停在
    下标 0，先被砍掉的正是唯一要紧的那条。
    """
    table = {k: dict(v) for k, v in (sess.npc_notes or {}).items() if isinstance(v, dict)}
    key = str(npc_id)
    if delta is None:
        table.pop(key, None)
        sess.npc_notes = table
        return []
    if not isinstance(delta, dict):
        # 静默吞掉会让「她左肩还在流血」这句话落空，而且没人知道
        return ["角色近况格式不对，没能记下"]

    notes = table.get(key) or {}
    warnings: list[str] = []
    for name, value in delta.items():
        field = str(name or "").strip()
        if not field:
            continue
        notes.pop(field, None)      # 先删：写回去时它会落到末尾，见上面
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if len(text) > NOTE_CHARS:
            text = text[:NOTE_CHARS] + "…"
        notes[field] = text

    if len(notes) > NOTE_LIMIT:
        drop = list(notes)[:len(notes) - NOTE_LIMIT]
        for field in drop:
            notes.pop(field, None)
        warnings.append(f"这个人的近况超过 {NOTE_LIMIT} 条，清掉了最久没更新的 {len(drop)} 条")

    table[key] = notes
    # 整个赋回去才会被标脏，原地改 JSON 列不会触发更新
    sess.npc_notes = table
    return warnings


def apply_npc_appearance(sess, npc_id: int, delta) -> list[str]:
    """这个人的外貌被这一局改写到什么地步了。自由键值，作者没定义过任何一个键。

    和 apply_npc_notes 是同一套合并语义（同键覆盖、新键追加、null 表示不再成立、
    整份 delta 是 null 表示全清），区别只在**满了怎么办**：

    近况满了淘汰**最久没被更新的那条**——那张表里新的比旧的要紧，「伤好了」就该
    盖过「左肩中刀」。这张表正相反：**拒绝新的、保留旧的**。这里的每一条都是
    「这个人身上已经发生的永久改变」，没有任何一条会因为别处更新而变得不重要；
    按新旧淘汰，被扔掉的恰好是「服下丰元玉乳散」那条最早的、也是最要紧的一条。

    满员时把 refusals 原样返回给玩家看：结算还在往里写就说明模型认为有变化，
    这时候该做的是让玩家去侧栏划掉一条不再作数的，而不是悄悄丢掉新的。

    值一律转成字符串，理由同 apply_npc_notes：模型会写数组或嵌套字典，而裸字典
    交给 React 当子节点会白屏。
    """
    table = {k: dict(v) for k, v in (sess.npc_appearance or {}).items() if isinstance(v, dict)}
    key = str(npc_id)
    if delta is None:
        table.pop(key, None)
        sess.npc_appearance = table
        return []
    if not isinstance(delta, dict):
        return ["外貌变化格式不对，没能记下"]

    fields = table.get(key) or {}
    warnings: list[str] = []
    for name, value in delta.items():
        field = str(name or "").strip()
        if not field:
            continue
        # 先删再写，让它落到末尾：和 apply_npc_notes 一样，新条目排在后面，
        # 注入时顺序稳定；满员判定也因此总是从最早的开始数
        fields.pop(field, None)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if len(text) > APPEARANCE_CHARS:
            text = text[:APPEARANCE_CHARS] + "…"
        # 满员只拦**新键**。已有的键照样能改能删——不然一处写错的措辞
        # 会被永久焊死在那里，玩家除了读档没有别的办法
        if field not in fields and len(fields) >= APPEARANCE_LIMIT:
            warnings.append(
                f"这个人改写过的地方已经记满 {APPEARANCE_LIMIT} 处，"
                f"「{field}」没记下（先划掉一条不再作数的再试）")
            continue
        fields[field] = text

    table[key] = fields
    sess.npc_appearance = table
    return warnings


def place_note(sess, place) -> str:
    """这个地方现在什么样（GM 记的那一句）。没记过就是空串。"""
    key = str(place or "").strip()
    if not key:
        return ""
    table = sess.place_notes or {}
    # 地名对不上大小写/空格就等于没记过，同 here_npcs 那边一样按 norm_name 比
    want = norm_name(key)
    for name, text in table.items():
        if norm_name(str(name)) == want:
            return str(text or "").strip()
    return ""


def apply_place_note(sess, place, text) -> list[str]:
    """记下、或清掉一个地方的近况。**每个地点只有一句**，新的直接盖掉旧的。

    空串 / None = 清掉（玩家手动划掉走这条路）。这是「现在这儿什么样」，
    不是流水账——门踹坏了、桌子掀了，下次回来还看得见的那种事。

    满了淘汰最久没被改过的那条：先删再写，让刚记的落到末尾，同 apply_npc_notes。
    整个字典赋回去才标脏，原地改 JSON 列不会落库。
    """
    key = str(place or "").strip()
    if not key:
        return []
    # 模型会把值写成 {"门": "坏了"} 这样的嵌套字典，str() 一落库就是
    # "{'门': '坏了'}"，还会每轮注入【场面】块。那是格式错误，不是这地方的新样子。
    # None / 空串照旧走下面「清掉」那条老路，不能被这道检查挡下来
    if text is not None and not isinstance(text, str):
        return [f"「{key}」的近况格式不对，没能记下"]
    table = {str(k): str(v) for k, v in (sess.place_notes or {}).items()}
    # 先删：既是覆盖同名（大小写不同也算同一个地方），也是把它挪到末尾
    want = norm_name(key)
    for name in [n for n in table if norm_name(n) == want]:
        table.pop(name)

    value = str(text or "").strip()
    warnings: list[str] = []
    if value:
        if len(value) > PLACE_CHARS:
            value = value[:PLACE_CHARS] + "…"
        table[key] = value

    if len(table) > PLACE_LIMIT:
        drop = list(table)[:len(table) - PLACE_LIMIT]
        for name in drop:
            table.pop(name, None)
        warnings.append(f"地点近况超过 {PLACE_LIMIT} 条，清掉了最久没更新的 {len(drop)} 条")

    sess.place_notes = table
    return warnings


def npc_activity(sess, npc_id) -> str:
    """这个角色最近在做什么（AI 调度写的那一句）。没记过就是空串。"""
    value = (sess.npc_activities or {}).get(str(npc_id))
    return str(value or "").strip()


def apply_npc_activity(sess, npc_id: int, text) -> None:
    """记下、或清掉一个角色「最近在做什么」。

    空串 / None = 清掉（玩家手动划掉走这条路）。**每个角色只有一句**，
    新的一次直接盖掉旧的——这是「最近」，不是日志。被盖掉的那句不会没影：
    每次写入顺带往 npc_activity_log 里留一条按时段盖章的底。

    **清掉只清「最近」，不动那条流水**：流水是盖过时间戳的旧账，同经历，
    玩家在档案里看到的是「她那几格在忙什么」。划掉当前这句是说「现在别再
    拿它编下去了」，不是说那几天没发生过。

    和 npc_notes 分开存：那张表是 GM 从这一轮叙事里读出来的近况（伤在哪、
    身上带着什么），这张是调度替不在场的人写的行动。两个写手共用一套键名的
    话，模型迟早会用一个「伤势」盖掉刚记下的行动，而且两边都以为对方在管。

    整个字典赋回去才标脏，原地改 JSON 列不会落库。
    """
    table = dict(sess.npc_activities or {})
    key = str(npc_id)
    value = str(text or "").strip()
    if not value:
        table.pop(key, None)
    else:
        if len(value) > ACTIVITY_CHARS:
            value = value[:ACTIVITY_CHARS] + "…"
        table[key] = value
        _log_npc_activity(sess, key, value)
    sess.npc_activities = table


def _log_npc_activity(sess, key: str, value: str) -> None:
    """把刚记下的那句话按时段留一条底（见 models.RpgSession.npc_activity_log）。

    **同一格只留最后一句**：调度在回合那条路上每轮都跑，一格里能跑好几次，
    不按时段去重的话一天就能把窗口撑满，而玩家想看的是「那一格她在干嘛」。

    时间戳由引擎在写入这一刻盖，同经历那边——调度那次调用压根没被告知今天
    第几天。满 ACTIVITY_LOG_LINES 条丢最旧的。
    """
    day = max(1, int(getattr(sess, "day", 1) or 1))
    slot = str(getattr(sess, "slot", "") or "")
    rows = [row for row in (sess.npc_activity_log or {}).get(key) or []
            if not (row.get("day") == day and row.get("slot") == slot)]
    rows.append({"day": day, "slot": slot, "content": value})
    sess.npc_activity_log = {
        **(sess.npc_activity_log or {}), key: rows[-ACTIVITY_LOG_LINES:],
    }


def push_npc_inbox(sess, npc_id: int, text, place="") -> None:
    """记一条「她想找你说话」，等玩家点开（写进 sess.npc_inbox）。

    空串 / None 直接忽略：调度那边没写这一行就是没有留言，不是要清空。
    清理走 drop_npc_inbox（玩家点了「不要」）或 pop_npc_inbox（点了「查看」）。

    同一个人同一句话不重复挂：调度每轮都跑，她的处境没变时模型很容易写出
    逐字相同的一句，那样红点上的数字会一轮涨一个，而玩家看到的是同一句话。

    满了丢**最旧的**而不是拒绝新的：过时的留言没有价值，刚写的才是当下的
    处境。这和 place_notes 挤掉最久没更新的那一条是同一个取舍。

    day/slot/place 在这里快照。事后拿 sess 回查算的是「现在」——玩家早走了、
    时段早翻了，那时候算出来的地点会说她在一个她当时不在的地方。
    """
    value = str(text or "").strip()
    if not value:
        return
    if len(value) > INBOX_CHARS:
        value = value[:INBOX_CHARS] + "…"

    rows = [r for r in (sess.npc_inbox or []) if isinstance(r, dict)]
    key = int(npc_id)
    mine = [r for r in rows if _num(r.get("npc_id"), -1) == key]
    if any(str(r.get("text") or "").strip() == value for r in mine):
        return
    # 这个人自己那几条超了，先挤掉她最旧的一条。按人分别封顶而不是只看总数：
    # 只看总数的话，一个话多的角色会把别人的留言全挤出去
    if len(mine) >= INBOX_PER_NPC:
        drop = {id(r) for r in mine[:len(mine) - INBOX_PER_NPC + 1]}
        rows = [r for r in rows if id(r) not in drop]

    rows.append({
        "id": uuid.uuid4().hex[:12],
        "npc_id": key,
        "text": value,
        "day": _num(getattr(sess, "day", 1), 1),
        "slot": str(getattr(sess, "slot", "") or "").strip(),
        "place": str(place or "").strip(),
    })
    if len(rows) > INBOX_LIMIT:
        rows = rows[len(rows) - INBOX_LIMIT:]
    sess.npc_inbox = rows


def pop_npc_inbox(sess, entry_id) -> dict | None:
    """取出一条留言并从清单里摘掉，取不到返回 None。

    取出和摘掉是同一步：调用方拿它去落一条真消息，留在清单里就会被点第二次，
    于是同一句话在历史里出现两遍。
    """
    rows = [r for r in (sess.npc_inbox or []) if isinstance(r, dict)]
    found = next((r for r in rows if str(r.get("id") or "") == str(entry_id)), None)
    if found is None:
        return None
    sess.npc_inbox = [r for r in rows if str(r.get("id") or "") != str(entry_id)]
    return found


def drop_npc_inbox(sess, entry_id) -> None:
    """玩家说「不理她」。只把这一条划掉，什么都不留下——她没找过你。"""
    sess.npc_inbox = [r for r in (sess.npc_inbox or [])
                      if not (isinstance(r, dict) and str(r.get("id") or "") == str(entry_id))]


def apply_npc_place(sess, npc_id: int, place, *, source: str = "story") -> None:
    """剧情把这个人挪到哪儿了（写进 sess.npc_places）。

    空串 / None = 清掉，她回到作息表 / 常驻地点安排的地方。**这不是「撤回」的
    特例**，而是唯一的表达方式：作者排的作息表是「她该在哪儿」，清掉就等于
    剧情放她回去了。

    换时段时仍在玩家身边的人保留位置，离场者恢复日常安排。

    整个字典赋回去才标脏，原地改 JSON 列不会落库（同 apply_npc_activity）。
    """
    # 只收字符串：模型偶尔把值写成 {"地点": "宿舍"}，那样存进去的是一段 JSON
    # 文本，界面上直接把这段 JSON 当地名显示出来
    value = str(place or "").strip() if isinstance(place, (str, int, float)) else ""
    table = dict(sess.npc_places or {})
    key = str(npc_id)
    if value:
        table[key] = value
    else:
        table.pop(key, None)
    sess.npc_places = table
    random_places = dict(getattr(sess, "npc_random_places", None) or {})
    if source == "random" and value:
        random_places[key] = value
    else:
        random_places.pop(key, None)
    if hasattr(sess, "npc_random_places"):
        sess.npc_random_places = random_places


def apply_npc_followers(sess, npc_id: int, following: bool) -> bool:
    """把这个人加进 / 移出「跟着玩家走」的名单（sess.npc_followers）。返回是否真的变了。

    **这里不记位置**，只记「她跟着你」这件事：位置由 rpg_context.npc_place 的
    取值链当场算出来（剧情 → 跟随 → 作息表 → 常驻地），解析出来就是你此刻站
    的地方。所以这个名单**不需要任何「移动之后同步一遍」的收口**，玩家走到哪
    她就在哪，不可能和 sess.location 对不上。

    这份名单推时段不清，直到玩家明确解除跟随。

    返回布尔是为了让调用方能说「赫敏跟上了你」——没变的事不必报一遍。

    整份列表赋回去才标脏，原地改 JSON 列不会落库（同 apply_npc_place）。
    """
    try:
        key = int(npc_id)
    except (TypeError, ValueError):
        return False
    current = [int(x) for x in (sess.npc_followers or []) if isinstance(x, (int, float))]
    if following == (key in current):
        return False
    table = [x for x in current if x != key]
    if following:
        table.append(key)
    sess.npc_followers = table
    return True



def mark_met(sess, npc_ids) -> None:
    """标记见过面。**和注入无关**（外貌改成每轮都发了），它管的是「玩家认识谁」：
    【外场】只给见过面的、又不在跟前的人写近况（见 rpg_turn 的 offscreen_brief），
    前端 condition.ts 的 knownNpcs 也拿它筛列表。"""
    states = dict(sess.npc_states or {})
    changed = False
    for npc_id in npc_ids or []:
        key = str(npc_id)
        state = dict(states.get(key) or {})
        if not state.get("met"):
            state["met"] = True
            states[key] = state
            changed = True
    if changed:
        sess.npc_states = states


def mark_fired(sess, entry_ids) -> None:
    """记一笔「这条一次性词条已经放过了」（RpgWorldEntry.once）。

    语义同 mark_met：**上下文发出去就算放过**，叙事失败也算——模型确实已经
    拿到过那段文字了。想让它重来只有读档一条路（fired_entries 进
    SNAPSHOT_FIELDS），界面上不另做「重新武装」。

    只追加、不覆写整列：和 flag_days 一样是引擎独占的列，模型碰不到。
    """
    fired = list(sess.fired_entries or [])
    known = set(fired)
    changed = False
    for entry_id in entry_ids or []:
        if entry_id not in known:
            fired.append(entry_id)
            known.add(entry_id)
            changed = True
    if changed:
        sess.fired_entries = fired


def starting_inventory(module, items) -> list[dict]:
    """这一局开局的背包：模组的开局背包 + 定义里勾了「开局就有」的道具。

    两边合起来而不是二选一，因为它们说的不是一件事：`default_inventory` 是
    「这一局开场就多一件东西」（这一局专属的剧情道具），`start_with` 是「这件
    道具本身就该在身上」（跟着模组走的那几件补给）。作者会两个都用。

    认名字用的是 norm_name 而不是字面：定义里写「治伤药水」、开局背包里写
    「治伤药水 」（粘贴时带了个空格）按字面算就是两件，玩家背包里并排两条一样的。
    撞名时开局背包那份赢——它写了数量，比定义默认的一件更具体。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for row in module.default_inventory or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        # 原样搬过去，只把名字两头的空格去掉：开局背包是作者手写的整行数据，
        # 这里多补一个字段就等于多一处会和他写的东西打架的地方
        out.append({**row, "name": name})
        seen.add(norm_name(name))

    for item in items or []:
        if not getattr(item, "start_with", False):
            continue
        name = str(getattr(item, "name", "") or "").strip()
        if not name or norm_name(name) in seen:
            continue
        seen.add(norm_name(name))
        # 不带 note：背包里那一行要显示说明时会先看定义（见 StatusSidebar），
        # 定义里的 description 本来就比这里能写的长
        out.append({"name": name, "qty": 1, "note": ""})
    return out


def protagonist_identity(npcs) -> tuple[str, str] | None:
    """主角模板卡上的「名字 + 出身与动机」，没有那张卡就是 None。

    出身与动机是**一句话简介和性格拼起来**的，因为主角卡和 NPC 卡共用一个编辑器，
    这两栏在卡上是分开的，而这一局的 `char_desc` 只有一栏。前端建局界面预填的是
    同一个拼法（pages/Rpg/protagonist.ts）——两处拼得不一样的话，玩家在弹窗里
    看到的和锁定后真正存进去的就不是一回事。
    """
    for npc in npcs or []:
        if (getattr(npc, "role", "") or "npc") != "protagonist":
            continue
        name = str(getattr(npc, "name", "") or "").strip()
        if not name:
            continue
        desc = "\n\n".join(
            part for part in (
                str(getattr(npc, "description", "") or "").strip(),
                str(getattr(npc, "persona", "") or "").strip(),
            ) if part
        )
        return name, desc
    return None


def starting_skills(skills) -> list[dict]:
    """这一局开局会的技能：定义里勾了「开局就会」的那些。

    没有对应 `default_inventory` 的那一半——技能没有「这一局专属」的入口，
    模组层面只有定义表。同背包一行只存名字和冷却，说明去定义里取。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for skill in skills or []:
        if not getattr(skill, "start_with", False):
            continue
        name = str(getattr(skill, "name", "") or "").strip()
        if not name or norm_name(name) in seen:
            continue
        seen.add(norm_name(name))
        out.append({"name": name, "cooldown_left": 0})
    return out


def learn_skill(sess, name: str) -> bool:
    """这一局学会一招。已经会了就不动，返回是否真的加上了。

    剧情里「你学会了一招」之后技能栏得真有这一条，否则「发现」只把定义
    塞进了模组库，玩家这一局还是用不了。
    """
    name = str(name or "").strip()
    if not name:
        return False
    rows = [dict(s) for s in (sess.skills or []) if isinstance(s, dict)]
    if any(norm_name(str(s.get("name") or "")) == norm_name(name) for s in rows):
        return False
    rows.append({"name": name, "cooldown_left": 0})
    sess.skills = rows
    return True


def skill_cooldown_left(sess, name: str) -> int:
    for row in sess.skills or []:
        if isinstance(row, dict) and norm_name(str(row.get("name") or "")) == norm_name(name):
            return max(0, int(row.get("cooldown_left") or 0))
    return 0


def set_cooldown(sess, name: str, turns: int) -> None:
    """用掉一招之后压上冷却。名字模糊匹配，同背包。"""
    rows = [dict(s) for s in (sess.skills or []) if isinstance(s, dict)]
    for row in rows:
        if norm_name(str(row.get("name") or "")) == norm_name(name):
            row["cooldown_left"] = max(0, int(turns or 0))
    sess.skills = rows


def tick_cooldowns(sess) -> None:
    """每回合开头把所有冷却减一。没在冷却的不动，减到 0 就停。"""
    rows = [dict(s) for s in (sess.skills or []) if isinstance(s, dict)]
    changed = False
    for row in rows:
        left = max(0, int(row.get("cooldown_left") or 0))
        if left > 0:
            row["cooldown_left"] = left - 1
            changed = True
    if changed:
        sess.skills = rows


def starting_tasks(tasks, turn: int = 0) -> list[dict]:
    """这一局开局就挂着的待办：定义里勾了「开局就接下」的那些。"""
    out: list[dict] = []
    seen: set[str] = set()
    for task in tasks or []:
        if not getattr(task, "auto_start", False):
            continue
        name = str(getattr(task, "name", "") or "").strip()
        if not name or norm_name(name) in seen:
            continue
        seen.add(norm_name(name))
        out.append({
            "name": name,
            "desc": str(getattr(task, "description", "") or ""),
            # 「怎样才算办完」。存进这一局而不是每次回查模组行：判定用的标准
            # 应该跟接下这桩事的时候一致，作者后来改了定义不该影响进行中的局
            "goal": str(getattr(task, "objective", "") or ""),
            "category": str(getattr(task, "category", "") or ""),
            "status": TASK_OPEN,
            "task_id": getattr(task, "id", None),
            "source": "module",
            "opened_turn": turn,
            "closed_turn": 0,
        })
    return out


def sync_task_categories(sess, tasks=()) -> bool:
    """为旧存档补回任务定义里的分类，避免升级后丢失日常标记。"""
    by_id = {str(getattr(task, "id", "")): task for task in tasks or []}
    by_name = {norm_name(str(getattr(task, "name", "") or "")): task for task in tasks or []}
    rows = [dict(task) for task in (sess.tasks or []) if isinstance(task, dict)]
    changed = False
    for row in rows:
        if str(row.get("category") or "").strip():
            continue
        definition = by_id.get(str(row.get("task_id") or ""))
        if definition is None:
            definition = by_name.get(norm_name(str(row.get("name") or "")))
        category = str(getattr(definition, "category", "") or "").strip() if definition else ""
        if category:
            row["category"] = category
            changed = True
    if changed:
        sess.tasks = rows
    return changed


def reset_daily_tasks(sess, tasks=()) -> bool:
    """跨天重新开放本局已经结束的日常任务。"""
    sync_task_categories(sess, tasks)
    rows = [dict(task) for task in (sess.tasks or []) if isinstance(task, dict)]
    changed = False
    for row in rows:
        if str(row.get("category") or "").strip() != DAILY_TASK_CATEGORY:
            continue
        if str(row.get("status") or TASK_OPEN) == TASK_OPEN:
            continue
        row["status"] = TASK_OPEN
        row["opened_turn"] = int(getattr(sess, "turn_count", 0) or 0)
        row["closed_turn"] = 0
        changed = True
    if changed:
        sess.tasks = rows
    return changed


def open_task(sess, name: str, desc: str = "", goal: str = "", task_id=None,
              source: str = "story", category: str = "") -> bool:
    """这一局接下一桩事。同名的已经在清单上就不动，返回是否真的加上了。"""
    name = str(name or "").strip()
    if not name:
        return False
    rows = [dict(t) for t in (sess.tasks or []) if isinstance(t, dict)]
    if any(norm_name(str(t.get("name") or "")) == norm_name(name) for t in rows):
        return False
    rows.append({
        "name": name, "desc": str(desc or ""), "goal": str(goal or ""),
        "category": str(category or ""),
        "status": TASK_OPEN, "task_id": task_id, "source": source,
        "opened_turn": int(getattr(sess, "turn_count", 0) or 0), "closed_turn": 0,
    })
    sess.tasks = rows
    return True


def open_task_names(sess) -> list[str]:
    """还没了结的那几桩事的名字。判定和注入都只认这一份清单——模型只能在
    已经接下的事里选，不能凭空宣布「你办完了一件你从没接过的事」。"""
    return [
        str(t.get("name") or "").strip()
        for t in (sess.tasks or [])
        if isinstance(t, dict)
        and str(t.get("status") or TASK_OPEN) == TASK_OPEN
        and str(t.get("name") or "").strip()
    ]


def close_task(sess, name: str, status: str) -> dict | None:
    """把一桩事标成办完/砸了。返回被改的那一条（已经是这个状态就返回 None，
    奖励因此只发一次——玩家连点两下确认不会发两遍）。"""
    if status not in (TASK_DONE, TASK_FAILED):
        return None
    rows = [dict(t) for t in (sess.tasks or []) if isinstance(t, dict)]
    hit = None
    for row in rows:
        if norm_name(str(row.get("name") or "")) != norm_name(name):
            continue
        if str(row.get("status") or TASK_OPEN) != TASK_OPEN:
            return None
        row["status"] = status
        row["closed_turn"] = int(getattr(sess, "turn_count", 0) or 0)
        hit = row
    if hit is not None:
        sess.tasks = rows
    return hit


def apply_inventory(sess, changes) -> list[str]:
    """背包增删。changes 是 [{"name":..., "qty": ±n, "note":...}]。

    同名合并走模糊匹配（去空格忽略大小写）：模型写「铁 钥匙」很常见，
    严格比对会在背包里堆出两条同一把钥匙。
    """
    if changes and not isinstance(changes, list):
        # 静默吞掉会让「你捡起了钥匙」这句话落空且没人知道
        return ["背包变化格式不对，没能应用"]
    items = [
        dict(it) for it in (sess.inventory or [])
        if isinstance(it, dict) and str(it.get("name") or "").strip()
    ]
    warnings: list[str] = []
    for change in changes or []:
        if not isinstance(change, dict):
            continue
        name = str(change.get("name") or "").strip()
        if not name:
            continue
        qty = _num(change.get("qty"), 1)
        if qty == 0:
            continue
        target = norm_name(name)
        hit = next((it for it in items if norm_name(it.get("name")) == target), None)
        if hit is None:
            if qty < 0:
                warnings.append(f"背包里没有「{name}」，没能扣掉")
                continue
            entry = {"name": name, "qty": qty}
            if str(change.get("note") or "").strip():
                entry["note"] = str(change["note"]).strip()
            items.append(entry)
            continue
        left = _num(hit.get("qty"), 1) + qty
        if left <= 0:
            items.remove(hit)
        else:
            hit["qty"] = left
            if str(change.get("note") or "").strip():
                hit["note"] = str(change["note"]).strip()
    sess.inventory = items
    return warnings


def _sync_flag_days(sess, flags: dict) -> None:
    """按新的 flags 对齐 flag_days：新立的记下今天，落下的日期一并删掉。

    只在这一处对齐，所以两个写 flags 的地方（apply_flags / check_zero）行为一致，
    FLAG_LIMIT 砍掉的那几条也顺带清干净，不会留一堆指向不存在 flag 的日期。

    已经有日期的不刷新——「聊过之后第三天」要从第一次聊算起，重复置位不该往后推。
    置成 False 视同没发生：日期删掉，将来再立起来重新计时。
    """
    days = {k: v for k, v in (sess.flag_days or {}).items()}
    today = _num(getattr(sess, "day", 1), 1)
    for key in list(days):
        if not flags.get(key):
            days.pop(key, None)
    for key, value in flags.items():
        if value and key not in days:
            days[key] = today
    if days != (sess.flag_days or {}):
        sess.flag_days = days


def apply_flags(sess, delta) -> list[str]:
    """剧情开关。扁平不嵌套，合并语义唯一：同键覆盖、新键追加、null 删除。"""
    flags = {k: v for k, v in (sess.flags or {}).items()}
    for name, value in (delta or {}).items():
        key = str(name or "").strip()
        if not key:
            continue
        if value is None:
            flags.pop(key, None)
        else:
            flags[key] = value
    warnings: list[str] = []
    if len(flags) > FLAG_LIMIT:
        # 超了砍最早的：后进来的更可能是当下要紧的处境
        drop = list(flags)[:len(flags) - FLAG_LIMIT]
        for key in drop:
            flags.pop(key, None)
        warnings.append(f"处境开关超过 {FLAG_LIMIT} 条，清掉了最早的 {len(drop)} 条")
    sess.flags = flags
    _sync_flag_days(sess, flags)
    return warnings


def apply_tweak(
    module, sess, stats=None, relations=None, inventory=None, flags=None,
    *, npc_places=None, npcs=None, locations=None,
) -> list[str]:
    """修改器：玩家自己动手把某一项改成想要的值。返回只给面板看的那几句话。

    **不走 apply_state_delta**，走的是引擎那条路——rpg_turn 的 _use_item /
    _run_action 也是直接调 apply_stats 绕开它的。理由是 apply_state_delta 上面
    套着 cap_delta：那道每轮幅度上限是防模型一轮给自己加 80 点好感的，不是防
    玩家的手。玩家打开修改器就是明说要这个数字，中间再拦一道等于这功能没做。

    但 clamp（作者定的 min/max）照样生效：那是作者定义的数值范围，不是防作弊的
    闸。改完了也得落回作者画的那条线里，否则 on_zero / on_full / 分档全都会收到
    一个作者从没设想过的值。

    参数传的是**目标值**不是增减：面板上显示的就是当前值，玩家改完直接提交。
    差值由这里自己算，再交给现成的 apply_stats / apply_relations / apply_inventory，
    这样上下限、归零后果、满值标记全都还是走平时那一条路，不会出现只有修改器
    才有的怪状态。

    差为 0 的项直接跳过、不塞进 delta：一个 0 的增减落在一个已经越界的旧值上，
    apply_stats 会白冒一条「被限制在 X」——玩家只是没动它，却被念了一句。
    """
    notes: list[str] = []

    available_npcs = {
        str(npc.id): npc for npc in (npcs or [])
        if npc.module_id == module.id and npc.role != "protagonist"
    }
    available_places = {
        norm_name(place.name): place.name for place in (locations or [])
        if place.module_id == module.id and place.name.strip()
    }
    for npc_id, destination in (npc_places or {}).items():
        npc = available_npcs.get(str(npc_id))
        if npc is None:
            notes.append(f"忽略了不认识的角色「{npc_id}」")
            continue
        target = (destination or "").strip()
        if target:
            target = available_places.get(norm_name(target))
            if target is None:
                notes.append(f"{npc.name}的位置未修改：地点「{destination}」不在当前模组中")
                continue
        apply_npc_place(sess, npc.id, target)
        if not target or norm_name(target) != norm_name(sess.location):
            apply_npc_followers(sess, npc.id, False)

    # 数值：算差值。当前值取 sess.stats，缺项按 0 算（同 _num 的兜底）
    stats_delta: dict = {}
    current = dict(sess.stats or {})
    for name, want in (stats or {}).items():
        key = str(name or "").strip()
        if not key:
            continue
        diff = _num(want) - _num(current.get(key))
        if diff:
            stats_delta[key] = diff
    if stats_delta:
        notes.extend(apply_stats(module, sess, stats_delta))

    # 关系：按角色挨个处理。键是 npc_id 字符串（面板就是拿它当键的），
    # 对不上就跳过一个人，不能让整份提交作废
    for raw_id, changes in (relations or {}).items():
        try:
            npc_id = int(raw_id)
        except (TypeError, ValueError):
            notes.append(f"忽略了不认识的角色「{raw_id}」")
            continue
        # 当前值每次现取：上一个人的 apply_relations 会整份换掉 npc_states
        state = (sess.npc_states or {}).get(str(npc_id)) or {}
        diff = {}
        for name, want in (changes or {}).items():
            key = str(name or "").strip()
            if not key:
                continue
            gap = _num(want) - _num(state.get(key))
            if gap:
                diff[key] = gap
        if diff:
            notes.extend(apply_relations(module, sess, npc_id, diff))

    # 背包：qty 是**目标件数**不是增减。当前件数按 norm_name 模糊比对找，
    # 和 apply_inventory 一个口径——两处口径不一样的话，面板上写「绳子 5 件」
    # 会在这边算成 0、在那边又并排添一条新的
    changes = []
    for row in inventory or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        want = max(0, _num(row.get("qty")))
        key = norm_name(name)
        have = 0
        for item in sess.inventory or []:
            if isinstance(item, dict) and norm_name(item.get("name")) == key:
                have = _num(item.get("qty"), 1)
                break
        gap = want - have
        if gap:
            changes.append({"name": name, "qty": gap})
    if changes:
        # 模糊合并和「扣到 0 就删掉」都是 apply_inventory 自己会做的，这里只算差
        notes.extend(apply_inventory(sess, changes))

    # 处境开关本来就是覆盖 / 删除的语义，原样交出去。非空才调——
    # 空 dict 进去会白跑一趟 _sync_flag_days
    if flags:
        notes.extend(apply_flags(sess, flags))

    # 归零 / 填满的后果在这儿当场结掉，不能推到下一轮：跳过只是把后果推迟
    # （值已经是 0 了，下一轮照样触发），中间这一段反而是个前后不一致的状态——
    # 面板显示 0 而 status 还写着活着
    notes.extend(check_zero(module, sess))
    notes.extend(check_full(module, sess))

    # 上面这几句只回给面板，不进剧情、不进 GM 上下文：修改器对 GM 是完全静默的，
    # GM 每轮本来就拿当前数值，它只会看到新数字
    return notes


def check_zero(module, sess) -> list[str]:
    """数值归零的后果。死亡直接置 status，标记写一条 flag 让剧情自己接。"""
    stats = sess.stats or {}
    notes: list[str] = []
    flags = dict(sess.flags or {})
    dirty = False
    for name, spec in def_map(module.stat_defs).items():
        if _num(stats.get(name)) > 0:
            continue
        on_zero = str(spec.get("on_zero") or ON_ZERO_NONE).strip()
        if on_zero == ON_ZERO_DEAD:
            if sess.status == "alive":
                sess.status = "dead"
                notes.append(f"{name}归零，这一局结束了")
        elif on_zero == ON_ZERO_FLAG:
            key = f"{name}耗尽"
            if not flags.get(key):
                flags[key] = True
                dirty = True
                notes.append(f"{name}已经见底")
    if dirty:
        sess.flags = flags
        _sync_flag_days(sess, flags)
    return notes


def check_full(module, sess) -> list[str]:
    """数值填满的后果，check_zero 的镜像。这是「进度时钟」的触发点。

    一项有上限的数值配上 on_full=标记，就是一个填满就锁住的进度条：作者把
    「她开始信任你」定义成 max=8 的一项，推满立起「信任满」这条 flag，世界书的
    trigger_condition、动作的 requires、地点的 enter_requires 三处都能引用它。
    立 flag 而不是直接触发事件，理由同 check_zero——flag 走 _sync_flag_days，
    于是 after_days 也能用上（「她信任满了之后第 3 天」）。

    没上限的项（钱、声望）一律跳过：它们永远填不满，spec 里那个 on_full 是
    作者填错了，不是一条永不触发的规则。
    """
    stats = sess.stats or {}
    notes: list[str] = []
    flags = dict(sess.flags or {})
    dirty = False
    for name, spec in def_map(module.stat_defs).items():
        top = spec.get("max")
        if top is None:
            continue
        if _num(stats.get(name)) < _num(top):
            continue
        if str(spec.get("on_full") or ON_FULL_NONE).strip() != ON_FULL_FLAG:
            continue
        key = f"{name}满"
        if not flags.get(key):
            flags[key] = True
            dirty = True
            notes.append(f"{name}已经到顶")
    if dirty:
        sess.flags = flags
        _sync_flag_days(sess, flags)
    return notes


# ── 大事记：跨对话线共享的「已经传开的事」──────────────────────────────────

def chronicle_lines(sess) -> list[str]:
    """这一局的大事记，滤掉空串。"""
    return [str(x).strip() for x in (sess.chronicle or []) if str(x).strip()]


def push_chronicle(sess, lines) -> None:
    """追加若干条大事记，超上限砍最早的（同 flags）。

    整个列表赋回去才标脏——原地 append JSON 列不会触发更新。
    """
    if isinstance(lines, str):
        items = [lines]
    elif isinstance(lines, list):
        items = lines
    else:
        items = []
    now = chronicle_lines(sess)
    for line in items:
        text = str(line or "").strip()
        if text:
            now.append(text)
    sess.chronicle = now[-CHRONICLE_LIMIT:]


def _move_line(sess, to_name: str) -> str:
    stamp = f"第 {max(1, _num(sess.day, 1))} 天"
    slot = str(sess.slot or "").strip()
    return f"{MOVE_TAG}{stamp}{'·' + slot if slot else ''} 你去了{to_name}"


def note_move(sess, to_name: str) -> None:
    """移动记一笔，**但和上一条移动合并**。

    不合并的话大事记会变成流水账：玩家在镇上逛十个地方，十条「你去了 X」
    把真正传开的那件事挤没了。上一条不是移动行（比如中间跨了天）才新起一行。
    """
    line = _move_line(sess, to_name)
    now = chronicle_lines(sess)
    if now and now[-1].startswith(MOVE_TAG):
        now[-1] = line
    else:
        now.append(line)
    sess.chronicle = now[-CHRONICLE_LIMIT:]


def note_visited(sess, name) -> None:
    """去过的地方记一笔（地图的迷雾读它）。

    整个列表赋回去才标脏，同 push_chronicle。去重时把重复的那个挪到末尾，
    于是满了淘汰的是「最久没回去过的」——模型现编的一次性地名会先出局，
    起点那个镇子不会被挤掉。
    """
    text = str(name or "").strip()
    if not text:
        return
    key = norm_name(text)
    now = [x for x in (sess.visited or []) if norm_name(x) != key]
    now.append(text)
    sess.visited = now[-VISITED_LIMIT:]


# ── 时间：玩家自己拨的时钟 ────────────────────────────────────────────────

# 跨天恢复到上限的几成。**故意不是回满**：回满等于「睡一觉」是一颗零成本的
# 全恢复按钮，而推时段又是玩家自愿的，于是精力这类数值扣了根本不疼——扣多少
# 都能睡回来，最优策略变成不停休息。留七成是让消耗攒得起来，又不至于第二天
# 一开局就动不了
DAILY_RECOVER_RATIO = 0.7


def reset_daily(module, sess) -> list[str]:
    """跨天恢复。定义里勾了 reset_daily 的数值回到上限的七成。

    是按 max 算不是按 initial：这件事只在有上限时才成立，而且这样绕开了
    「建局时玩家把初始值改过」的归属问题。没上限的项（资金）跳过。

    **只往上抬，从不往下压**：昨天没怎么花、现在还高于七成的，睡一觉不该反而
    掉下来，否则养精蓄锐会变成惩罚。上限本身很小时（max=1）算出来的目标是 0，
    那就谁都抬不动，等于这一项不恢复——不为这种边角加分支
    """
    specs = def_map(module.stat_defs)
    stats = dict(sess.stats or {})
    notes: list[str] = []
    for name, spec in specs.items():
        if not spec.get("reset_daily") or spec.get("max") is None:
            continue
        target = clamp(spec, int(_num(spec.get("max")) * DAILY_RECOVER_RATIO))
        if _num(stats.get(name)) < target:
            previous = _num(stats.get(name))
            stats[name] = target
            notes.append(f"跨天恢复：{name}+{target - previous}（{previous} → {target}）")
    # 整个赋回去才会被标脏，原地改 JSON 列不会触发更新
    sess.stats = stats
    return notes


def slot_table(module, sess) -> list[str]:
    """这一局实际用的时段表：玩家建局时改过就用他改的那份，否则跟模组走。

    会话自己那一列为空 = 没定制过（老局、或建局时没动）。**「跟模组走」必须是活的**：
    模组后来把「早中晚」拆成三格，还没定制的局该跟着变，否则作者改了模组却发现
    已经开的局纹丝不动。定过的局仍然冻住，理由同 default_location。
    """
    raw = sess.time_slots or getattr(module, "time_slots", None) or []
    return [str(s).strip() for s in raw if str(s).strip()]


def random_movement_ok(npc, slot, place="") -> bool:
    """这个人此刻准不准被随机挪，以及挪到 place 算不算合法。

    三处共用：调度挑地点前的 movable 过滤、调度自己的对账循环、推时段时的
    _clear_expired_random_places。三处问的是同一件事，各写一遍必然漂移——
    作者事后改了白名单，漏掉哪一处的症状都是她永久停在一个已经不该待的地方，
    而且两边都不报错（同 npc_place 与前端 condition.npcPlace 那对镜像的教训）。

    place 留空 = 只问「此刻准不准随机移动」，不问去哪儿。
    两张白名单都是空列表 = 不限制，老数据行为逐字不变。
    """
    if npc is None or not getattr(npc, "random_movement", False):
        return False
    slots = {
        str(value).strip()
        for value in (getattr(npc, "random_movement_slots", None) or [])
        if str(value).strip()
    }
    if slots and str(slot or "").strip() not in slots:
        return False
    allowed = {
        norm_name(value)
        for value in (getattr(npc, "random_movement_places", None) or [])
        if str(value).strip()
    }
    # place 为空时不查这一张：那是「准不准动」的问法，去哪儿由调用方接着挑
    return not (allowed and place and norm_name(place) not in allowed)


def _clear_expired_random_places(sess, npcs=()) -> None:
    random_places = dict(getattr(sess, "npc_random_places", None) or {})
    if not random_places:
        return
    by_id = {str(getattr(npc, "id", "")): npc for npc in (npcs or [])}
    places = dict(sess.npc_places or {})
    for key, marked in list(random_places.items()):
        # marked 是引擎上次挑的那个地方，所以这一问连白名单一起判：
        # 作者把那个地点移出白名单之后，这条覆盖当场过期、位置落回作息表
        if not random_movement_ok(by_id.get(str(key)), sess.slot, marked):
            if norm_name(places.get(str(key))) == norm_name(marked):
                places.pop(str(key), None)
            random_places.pop(str(key), None)
    sess.npc_places = places
    sess.npc_random_places = random_places


def _has_schedule(npc) -> bool:
    """作者给这个人排过作息表吗——哪怕只排了一格。"""
    table = getattr(npc, "slot_locations", None)
    if not isinstance(table, dict):
        return False
    return any(str(value).strip() for value in table.values())


def advance_slot(module, sess, npcs=(), tasks=()) -> list[str]:
    """结束当前时段。走到最后一格就翻篇：回到第一格、天数 +1、跨天恢复。

    返回给玩家看的话。模组没设时段时什么都不做——时钟不存在，
    按一下不该有任何后果。
    """
    names = slot_table(module, sess)
    if not names:
        return []

    # 推时段不调模型，中间这一段天然没有叙事。记下起跳点留给下一轮的 prompt，
    # 否则模型只看到新的时段名，会接着上一轮的场景往下写。
    # 已经有起跳点就不覆盖：连着按两下、或者按完又攒满预算，中间那几格算同一段空白
    if not str(getattr(sess, "time_jump_from", "") or "").strip():
        day = max(1, int(getattr(sess, "day", 1) or 1))
        was = str(sess.slot or "").strip()
        # 名字拿不到（刚建局、或时段表改过）就只留天数——总比编一个时段名强
        sess.time_jump_from = f"第 {day} 天 · {was}" if was else f"第 {day} 天"

    from app.services.rpg_context import here_npcs

    here = str(sess.location or "").strip()
    followers = {str(identity) for identity in (sess.npc_followers or [])}
    retained = {
        str(identity): place for identity, place in (sess.npc_places or {}).items()
        if here and norm_name(place) == norm_name(here) and str(identity) not in followers
    }
    retained.update({
        str(npc.id): here
        for npc in here_npcs(list(npcs), here, sess.slot, sess.npc_places, sess.npc_followers)
        if str(npc.id) not in followers
    })
    # 引擎写的随机位置不在这一轮清理范围内。上面那两句清的是**结算写的**覆盖
    # （「你过来」办完事就该回作息表），而随机移动的覆盖有自己的到期规则：
    # 下面 _clear_expired_random_places 按「离开配置的时段」判。
    #
    # 一起清掉的后果是人会瞬移回常驻地：韩曼宁常驻「家」、没有作息表，被随机
    # 挪到菜市场之后玩家一推时段，覆盖没了 → 落回「家」。而 npc_random_places
    # 那张标记表这一步不动，于是两边对不上，下一次调度的对账循环发现现值和
    # 标记不一致，默默把标记也删了——两处都不报错，人就这么回了家
    random_places = dict(getattr(sess, "npc_random_places", None) or {})
    retained.update({
        key: place for key, place in (sess.npc_places or {}).items()
        if key in random_places and norm_name(random_places[key]) == norm_name(place)
        and key not in followers
    })
    # 一格子都没排过作息表的人，上面那两句同样不该清。清空的目的是「时段一变
    # 作息表重新说了算」，可她没有作息表——落回去的是常驻地那个常数，不是任何
    # 排期。实际后果是剧情刚把她挪去的地方被时钟抹掉，然后瞬移回常驻地：
    # 韩曼宁常驻「家」、作息表是空的，剧情写了她出门去健身房，玩家一按结束
    # 时段她就出现在同样在家的玩家面前。同上面 random_places 那条：清空为的是
    # 保住作者的排期手段，没有排期可保的时候它就只剩副作用。
    #
    # 判据是「**一格都没排**」，不是「这一格没排」。后者看着更贴切，实则会把
    # 那张表废掉：排了别的格子的人一旦留下这条覆盖，覆盖在取值链里排在作息表
    # 前面，他从此再也回不到自己排的那几格去（推时段那条测试逮住的就是这个）
    by_id = {str(npc.id): npc for npc in (npcs or [])}
    retained.update({
        key: place for key, place in (sess.npc_places or {}).items()
        if key not in followers and not _has_schedule(by_id.get(str(key)))
    })
    sess.npc_places = retained

    # 新的一格，两个计数器从零起。归零只写在这里：手动按按钮、动作勾了
    # cost_slot、行动预算攒满自动推，三条路都经过这个函数。
    # **在上面那个 return 之后**：没有时钟就没有「这一格」，不该动它们
    sess.slot_actions = 0
    sess.slot_chats = 0

    now = str(sess.slot or "").strip()
    # 当前时段不在表里（刚建局、或建局后改过时段表）就从第一格重新数起
    index = names.index(now) + 1 if now in names else 0
    if index < len(names):
        sess.slot = names[index]
        _clear_expired_random_places(sess, npcs)
        return [f"现在是{names[index]}"]

    sess.slot = names[0]
    _clear_expired_random_places(sess, npcs)
    sess.day = _num(sess.day, 1) + 1
    reset_daily_tasks(sess, tasks)
    # 只在翻篇这一格写大事记。每推一格都写的话，时钟噪音会把真正传开的
    # 事挤出去；一行都不写则换个地点就不知道过了几天
    push_chronicle(sess, f"{DAY_TAG}第 {sess.day} 天开始了")
    return [f"第 {sess.day} 天，{names[0]}"] + reset_daily(module, sess)


def spend_slot_action(module, sess, npcs=()) -> list[str]:
    """记一格行动，攒满 module.slot_budget 就自动推一格时段。返回给玩家看的话。

    只在**世界真的动了**那几轮调用（引擎产出了事实句），所以「条件没过、
    动作没做成」的那一轮不吃时间——同 _run_action 里「条件不过就数值不动」。

    slot_budget = 0（老模组的默认值）时只累加不推进，界面上也就没有任何
    变化，行为与加这个功能之前逐字一致。没设时段的模组同理：advance_slot
    自己会空转，这里连判都不用判。

    调用点必须在 apply_stats **之后**（理由同 rpg_turn._run_action 末尾那条
    注释：跨天恢复会把这一格自己的消耗抬掉），且在 seed_settlement 之前。
    """
    budget = _num(getattr(module, "slot_budget", 0), 0)
    sess.slot_actions = _num(sess.slot_actions, 0) + 1
    if budget <= 0 or sess.slot_actions < budget:
        return []
    # advance_slot 会把 slot_actions 归零，所以这里不用自己收尾。
    # 没设时段时它空转、返回空表，于是下面那句也不会拼——界面上什么都不会说
    facts = advance_slot(module, sess, npcs)
    if not facts:
        return []
    # 说清楚是「预算用完了」而不是玩家自己按的，否则时段看着像自己乱跳
    return ["这个时段的事做完了"] + facts


def note_slot_chat(sess) -> None:
    """记一条纯对话。只用来点亮按钮，不推时间。

    「聊得久」不等于世界该变——那种判断交给结算里 GM 的 scene_wrapped 提议。
    """
    sess.slot_chats = _num(sess.slot_chats, 0) + 1


def apply_state_delta(
    module, sess, delta, npcs=None, note_npcs=None, move_npcs=None, places=None, finalize=True,
) -> list[str]:
    """把模型提议的一整份改动落到 session 上，返回给玩家看的 warning。

    每一项独立 try：背包格式写错不该让数值一起丢。

    这里原先有个 allow_move 开关，用来在私聊线里丢掉玩家的 location 变化：
    分线的时候「在老兵线里被叙述走到别处」会变成看得见的 bug——老兵不在了，
    他那条线的输入框永久置灰。线拆掉之后那个 bug 没有了，开关也就没了——
    「自由打字绕过地图」是文档 §13 的既有决定，它当初的边界画在「场面线放行、
    私聊线不放行」上，现在没有别的线可分了。

    note_npcs 是**允许被记近况的人**，默认就是 npcs。调用方传的是这一轮真的
    摆在模型眼前的那几个（在场的），比关系数值那一路窄。理由是两者的代价
    不对称：关系是个数字，写错了下一轮就被盖掉；近况是长期事实，会原样画在
    角色卡上、每轮注入那个人的设定块，而剧情里随口提一句「老板」就足以让
    隔壁镇的老板凭空多出一条伤。

    move_npcs 是**允许被改位置的人**，默认空 = 一个都不准改（老调用点行为
    不变）。调用方传的是刚写出来的正文里真的出现过的人（named_npcs），比
    note_npcs 再紧一层：位置写错不是「卡上多一行字」，而是她凭空站在你面前、
    侧栏说「就在你面前」、还能拉进私聊——玩家没有任何纠正的入口。

    places 是模组地点表里的地名，用来把模型写的地名对回真名字（见
    match_place）。不传就是不对——地点表为空的纯对话模组行为不变。
    """
    if not isinstance(delta, dict):
        return []
    warnings: list[str] = []
    # 认名字走 match_npc：模型会把「赫敏格兰杰」写成「赫敏」。同名的人
    # （模组里常有三个「村民」）折叠成最后一个——既有行为，relations 一直如此，
    # 近况沿用同一套映射
    note_ids = {n.id for n in ((npcs or []) if note_npcs is None else note_npcs)}

    # 幅度上限只夹这一路。这个函数是模型提议的入口，引擎那条路
    # （rpg_turn._use_item / _run_action）直接调 apply_stats / apply_relations
    # 等级先单独夹一道再进 cap_delta：那一道是对称的，借它来限「一轮最多升
    # 1 级」会把「修为被废，8 掉到 0」也锁成 -1
    ranked, rank_caps = cap_rank_gain(module, delta.get("stats"))
    warnings.extend(rank_caps)
    stats_delta, stats_caps = cap_delta(def_map(module.stat_defs), ranked)
    warnings.extend(stats_caps)

    steps = [
        ("数值", lambda: apply_stats(module, sess, stats_delta)),
        ("背包", lambda: apply_inventory(sess, delta.get("inventory"))),
        ("处境", lambda: apply_flags(sess, delta.get("flags"))),
    ]
    for label, run in steps:
        try:
            warnings.extend(run())
        except Exception:
            warnings.append(f"{label}变化没能应用")

    # 关系数值按角色名提议：模型记不住 id，但名字就在它眼前的【在场】块里
    relation_specs = def_map(module.relation_stat_defs)
    for name, changes in (delta.get("relations") or {}).items():
        who = match_npc(name, npcs)
        if who is None:
            warnings.append(f"找不到角色「{name}」，关系变化没能应用")
            continue
        npc_id = who.id
        capped, caps = cap_delta(relation_specs, changes)
        warnings.extend(f"{name}的{note}" for note in caps)
        try:
            warnings.extend(apply_relations(module, sess, npc_id, capped))
        except Exception:
            warnings.append(f"{name}的关系变化没能应用")

    # 近况同样按角色名提议，但只认这一轮在模型眼前的人
    for name, changes in (delta.get("npc_notes") or {}).items():
        who = match_npc(name, npcs)
        if who is None:
            warnings.append(f"找不到角色「{name}」，近况没能记下")
            continue
        npc_id = who.id
        if npc_id not in note_ids:
            # 说「不在你跟前」而不是「不在场」：后者是界面上的词，指「和你在
            # 同一个地点」，两者混用会让玩家在诊断行和这条提示之间自相矛盾。
            # 也刻意和下面位置那条（「没在剧情里露面」）用不同措辞——一个说的是
            # 人在别处，一个说的是正文里压根没这个人，拒绝的理由不是一回事
            warnings.append(f"「{name}」不在你跟前，关于他的近况没有记下")
            continue
        try:
            warnings.extend(apply_npc_notes(sess, npc_id, changes))
        except Exception:
            warnings.append(f"{name}的近况没能记下")

    # 外貌改写同样只认这一轮在模型眼前的人，门比近况再紧一层：近况写错是卡上
    # 多一行字，外貌写错是**这个人在你眼前的样子被永久改掉**，而且它压在作者
    # 原文后面，模型会一直照着它写。门外的人连近况都不让记，这条更不该放行
    for name, changes in (delta.get("npc_appearance") or {}).items():
        who = match_npc(name, npcs)
        if who is None:
            warnings.append(f"找不到角色「{name}」，外貌变化没能记下")
            continue
        if who.id not in note_ids:
            warnings.append(f"「{name}」不在你跟前，关于他外貌的变化没有记下")
            continue
        try:
            warnings.extend(apply_npc_appearance(sess, who.id, changes))
        except Exception:
            warnings.append(f"{name}的外貌变化没能记下")

    # 人物位置：剧情把谁挪到哪儿了。空串 = 放她回作息表安排的地方。
    # 不看 allow_move——那个开关只管玩家自己的位置（见函数说明）
    #
    # 这里原先直接叫 places，把参数里那份**地点表**盖掉了：一旦这一轮的 delta
    # 带了 npc_places，下面两处 match_place 拿到的「已知地名」就成了一串人名，
    # 于是模型写的「外门藏经阁」再也对不回「藏经阁」——正是 match_place 存在
    # 要修的那个 bug，只在带人物位置的那些轮里复发
    moved = delta.get("npc_places")
    if isinstance(moved, dict) and moved:
        allowed = {n.id for n in (move_npcs or [])}
        for name, place in moved.items():
            who = match_npc(name, npcs)
            if who is None:
                warnings.append(f"找不到角色「{name}」，位置变化没能应用")
                continue
            if who.id not in allowed:
                # 只是嘴上被提到、正文里没露面的人不许挪：模型据此把
                # 一个没出场的人放到玩家跟前，就是纯凭空的编造
                warnings.append(f"「{name}」这一轮没在剧情里露面，他的位置没有改")
                continue
            # 空串是「放她回作息表」，match_place 原样放行
            apply_npc_place(sess, who.id, match_place(place, places))

    # 对回真地名再存：存错一个字，这里所有人立刻都算「不在你跟前」
    was = str(sess.location or "").strip()
    location = match_place(str(delta.get("location") or ""), places).strip()
    if location:
        sess.location = location
        note_visited(sess, location)

    # 地点近况：这一轮把这个地方弄成什么样了，一个地方一句。
    # 只认这一轮待过的那两个地方（出发的和到达的）。不设这道门的话，模型会
    # 顺手「更新」一个隔着三条街、它只在对话里提过一句的地方——理由同
    # note_npcs：这是长期事实，会每轮画在【场面】块上，而玩家没有纠正的入口
    stayed = {norm_name(n) for n in (was, sess.location) if n}
    for name, text in (delta.get("place_notes") or {}).items():
        real = str(match_place(str(name or ""), places) or "").strip()
        if norm_name(real) not in stayed:
            warnings.append(f"「{name}」不是你这一轮待过的地方，那儿的近况没有记下")
            continue
        try:
            warnings.extend(apply_place_note(sess, real, text))
        except Exception:
            warnings.append(f"{real}的近况没能记下")

    if finalize:
        try:
            warnings.extend(check_zero(module, sess))
        except Exception:
            warnings.append("归零判定没能执行")
        try:
            warnings.extend(check_full(module, sess))
        except Exception:
            warnings.append("填满判定没能执行")
    return warnings
