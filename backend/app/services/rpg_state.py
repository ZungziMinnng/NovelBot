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


def apply_state_delta(module, sess, delta, npcs=None) -> list[str]:
    """把模型提议的一整份改动落到 session 上，返回给玩家看的 warning。

    每一项独立 try：背包格式写错不该让数值一起丢。
    """
    if not isinstance(delta, dict):
        return []
    warnings: list[str] = []
    by_name = {norm_name(n.name): n.id for n in (npcs or [])}

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

    location = str(delta.get("location") or "").strip()
    if location:
        sess.location = location

    try:
        warnings.extend(check_zero(module, sess))
    except Exception:
        warnings.append("归零判定没能执行")
    return warnings
