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
# display：条 = 进度条（要有 max）/ 数字 = 纯数字 / 隐藏 = 玩家看不见的幕后计数器
DISPLAY_BAR, DISPLAY_NUMBER, DISPLAY_HIDDEN = "条", "数字", "隐藏"

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

# 数值的「影响」那几段最长多少字。同 NOTE_CHARS 的理由，而且更紧：说明每轮
# 发一遍，档位标签还要跟在每个数字后面画在侧栏上，长了就换行
EFFECT_CHARS = 30
TIER_LABEL_CHARS = 6
TIER_NOTE_CHARS = 20

# 引擎自己写进大事记的两类行。前缀是**合并的判据**——认不出「上一行也是
# 移动」的话，玩家在镇上连点五个地点就会刷出五条「你去了 X」
MOVE_TAG = "〔移动〕"
DAY_TAG = "〔日期〕"

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


def _num(value, fallback=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def norm_name(text) -> str:
    return str(text or "").translate(_NORMALIZE_TABLE).strip().lower()


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


def init_relation(defs, overrides=None) -> dict[str, int]:
    """一个角色的关系数值起点。overrides 是 RpgNpc.initial_state，
    只覆盖定义里有的键——模组改了定义之后，角色卡上的旧键不该复活。
    """
    over = overrides if isinstance(overrides, dict) else {}
    out = {}
    for name, spec in def_map(defs).items():
        raw = over[name] if name in over else spec.get("initial", 0)
        out[name] = clamp(spec, raw)
    return out


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
    by_name = {norm_name(n.name): n for n in (npcs or [])}
    states = sess.npc_states or {}
    for rule in cond.get("relations") or []:
        if not isinstance(rule, dict):
            continue
        who = str(rule.get("npc") or "").strip()
        npc = by_name.get(norm_name(who))
        if npc is None:
            return False, f"找不到角色「{who}」"
        op = _OPS.get(str(rule.get("op") or ">=").strip())
        if op is None:
            continue
        stat = str(rule.get("stat") or "").strip()
        want = _num(rule.get("value"))
        have = _num((states.get(str(npc.id)) or {}).get(stat))
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

    if cond.get("items"):
        owned = {norm_name(it.get("name")) for it in (sess.inventory or []) if isinstance(it, dict)}
        for want in cond["items"]:
            if norm_name(want) not in owned:
                return False, f"没有「{str(want).strip()}」"

    return True, ""


# ── 状态应用 ──────────────────────────────────────────────────────────────

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


def mark_met(sess, npc_ids) -> None:
    """标记见过面。外貌只在首次见面时注入，见过之后每轮再发一遍纯属浪费。"""
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
    return warnings


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

def reset_daily(module, sess) -> list[str]:
    """跨天回满。定义里勾了 reset_daily 的数值回到 max。

    是回 max 不是回 initial：「回满」这件事只在有上限时才成立，而且这样
    绕开了「建局时玩家把初始值改过」的归属问题。没上限的项（资金）跳过。
    """
    specs = def_map(module.stat_defs)
    stats = dict(sess.stats or {})
    notes: list[str] = []
    for name, spec in specs.items():
        if not spec.get("reset_daily") or spec.get("max") is None:
            continue
        full = clamp(spec, spec.get("max"))
        if _num(stats.get(name)) != full:
            stats[name] = full
            notes.append(f"{name}回到 {full}")
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


def advance_slot(module, sess) -> list[str]:
    """结束当前时段。走到最后一格就翻篇：回到第一格、天数 +1、跨天回满。

    返回给玩家看的话。模组没设时段时什么都不做——时钟不存在，
    按一下不该有任何后果。
    """
    names = slot_table(module, sess)
    if not names:
        return []

    now = str(sess.slot or "").strip()
    # 当前时段不在表里（刚建局、或建局后改过时段表）就从第一格重新数起
    index = names.index(now) + 1 if now in names else 0
    if index < len(names):
        sess.slot = names[index]
        return [f"现在是{names[index]}"]

    sess.slot = names[0]
    sess.day = _num(sess.day, 1) + 1
    # 只在翻篇这一格写大事记。每推一格都写的话，时钟噪音会把真正传开的
    # 事挤出去；一行都不写则换个地点就不知道过了几天
    push_chronicle(sess, f"{DAY_TAG}第 {sess.day} 天开始了")
    return [f"第 {sess.day} 天，{names[0]}"] + reset_daily(module, sess)


def apply_state_delta(
    module, sess, delta, npcs=None, allow_move: bool = True, note_npcs=None,
) -> list[str]:
    """把模型提议的一整份改动落到 session 上，返回给玩家看的 warning。

    每一项独立 try：背包格式写错不该让数值一起丢。

    allow_move=False 时丢掉 location：分线之后「在老兵线里被叙述走到别处」
    会变成看得见的 bug——老兵不在了，他的输入框永久置灰。场面线照旧放行，
    「自由打字绕过地图」这个决定（见文档 §13）的边界正好画在这里。

    note_npcs 是**允许被记近况的人**，默认就是 npcs。调用方传的是这一轮真的
    摆在模型眼前的那几个（在场的 + 线主），比关系数值那一路窄。理由是两者
    的代价不对称：关系是个数字，写错了下一轮就被盖掉；近况是长期事实，会
    原样画在角色卡上、每轮注入那个人的设定块，而剧情里随口提一句「老板」
    就足以让隔壁镇的老板凭空多出一条伤。
    """
    if not isinstance(delta, dict):
        return []
    warnings: list[str] = []
    by_name = {norm_name(n.name): n.id for n in (npcs or [])}
    # 同名的人（模组里常有三个「村民」）在这里会被折叠成最后一个——既有行为，
    # relations 一直如此，近况沿用同一套映射
    note_ids = {n.id for n in ((npcs or []) if note_npcs is None else note_npcs)}

    steps = [
        ("数值", lambda: apply_stats(module, sess, delta.get("stats"))),
        ("背包", lambda: apply_inventory(sess, delta.get("inventory"))),
        ("处境", lambda: apply_flags(sess, delta.get("flags"))),
    ]
    for label, run in steps:
        try:
            warnings.extend(run())
        except Exception:
            warnings.append(f"{label}变化没能应用")

    # 关系数值按角色名提议：模型记不住 id，但名字就在它眼前的【在场】块里
    for name, changes in (delta.get("relations") or {}).items():
        npc_id = by_name.get(norm_name(name))
        if npc_id is None:
            warnings.append(f"找不到角色「{name}」，关系变化没能应用")
            continue
        try:
            warnings.extend(apply_relations(module, sess, npc_id, changes))
        except Exception:
            warnings.append(f"{name}的关系变化没能应用")

    # 近况同样按角色名提议，但只认这一轮在模型眼前的人
    for name, changes in (delta.get("npc_notes") or {}).items():
        npc_id = by_name.get(norm_name(name))
        if npc_id is None:
            warnings.append(f"找不到角色「{name}」，近况没能记下")
            continue
        if npc_id not in note_ids:
            warnings.append(f"「{name}」这一轮不在场，关于他的近况没有记下")
            continue
        try:
            warnings.extend(apply_npc_notes(sess, npc_id, changes))
        except Exception:
            warnings.append(f"{name}的近况没能记下")

    location = str(delta.get("location") or "").strip()
    if location and not allow_move:
        warnings.append("这一轮的地点变化被忽略了（你正在和人单独说话）")
    elif location:
        sess.location = location
        note_visited(sess, location)

    try:
        warnings.extend(check_zero(module, sess))
    except Exception:
        warnings.append("归零判定没能执行")
    return warnings
