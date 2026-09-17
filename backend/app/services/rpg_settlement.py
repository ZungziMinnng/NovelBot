import copy
import json
import logging
import math
import re
import unicodedata
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select, update

from app.models.rpg import (
    RpgItem, RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgSession, RpgSkill, RpgTask,
)
from app.services import fact_guard, llm_client
from app.services.rpg_context import npc_place, turn_present, world_npcs
from app.services.rpg_dice import OUTCOME_LABELS
from app.services.rpg_memory import invalidate_summaries, text_revision
from app.services.rpg_prompts import render
from app.services.rpg_state import apply_flags, apply_state_delta, check_condition, check_full, check_zero, def_map, mark_met, match_npc, norm_name, open_task_names, push_chronicle

logger = logging.getLogger(__name__)


STATE_FIELDS = (
    "stats", "inventory", "flags", "location", "npc_states", "npc_notes",
    "npc_places", "place_notes", "status", "visited", "chronicle",
    # flag 的立起日期。必须跟 flags 同进同出：这一列是引擎在 apply_flags 里记的，
    # 而 AI 结算走的是 working 副本，不在这张表里就写不回会话——模型立起来的
    # flag 于是永远没有日期，「某事之后 N 天」判不过。
    # 模型碰不到它（不在 DOMAINS 的 keys 里，也就不在它能写的 delta 键里）
    "flag_days",
)
DOMAINS = {
    "scene": ("location", "npc_places", "place_notes"),
    "stats": ("stats",),
    "inventory": ("inventory",),
    "characters": ("relations", "npc_notes"),
    "flags": ("flags",),
    "memory": ("events", "chronicle"),
}
LABELS = {"scene": "地点与在场人物", "stats": "数值", "inventory": "背包", "characters": "人物", "flags": "处境", "memory": "长期记忆"}
DOMAIN_FIELDS = {
    "scene": ("location", "npc_places", "place_notes", "visited"),
    "stats": ("stats", "status"), "inventory": ("inventory",),
    # flag_days 跟着 flags 一起回滚：处境这一域被判为需要人工核对时，
    # 只退 flags 会留下一个指向不存在 flag 的日期
    "characters": ("npc_states", "npc_notes"), "flags": ("flags", "flag_days"),
    "memory": ("chronicle",),
}
PUBLIC_KEYS = ("status", "revision", "attempts", "domains", "changes", "warnings", "facts", "applied", "proposed", "retryable")
EVENT_KINDS = {"state", "move", "gain", "loss", "transfer", "injury", "recovery", "relationship", "promise", "rescue", "death", "public"}
CONTRACT = """
=== 结算核对协议（必须遵守） ===
读取本回合完整正文，区分真实发生、计划、否定、转述和假设。已有状态不是本轮新变化。
在原 JSON 中增加 checks 和 events：
"checks": {"scene":"changed或unchanged", "stats":"changed或unchanged", "inventory":"changed或unchanged", "characters":"changed或unchanged", "flags":"changed或unchanged", "memory":"changed或unchanged"}
每项都必须核对。unchanged 表示已检查且没有变化，不得用省略代替核对。
"events": [{"kind":"transfer", "quote":"正文中连续且逐字相同的原文", "summary":"已经发生的事实，60字以内", "domains":["inventory","characters"], "participants":[12], "witnesses":[12], "visibility":"witnessed"}]
kind 可用 state/move/gain/loss/transfer/injury/recovery/relationship/promise/rescue/death/public。普通数值或处境变化用 state。
移动、物品获得/失去/交接、受伤/恢复，以及拜师、救命、结仇、承诺等重大事实都要记录依据。
quote 必须直接摘录正文，不能改写、拼接或省略。没有事件时 events 输出 []。
quote 只摘取与变化直接相关的连续句子，通常 120 字以内，不要引用整篇剧情。
domains 标出事件应改变的项目；交给 NPC 的物品必须同时核对背包和接收人的持有近况，不能只改一边。
每个发生变化的项目至少关联一条事件原文。物品交接事件还要写 item（物品名）、qty（正整数）、from 和 to（player 或 npc:数字id）。
一次交接给出多件物品时，inventory 按物品的实际名称分条写，event 写一条即可，item 填正文里的统称。
交接事件涉及的那个 NPC，必须同时在 npc_notes 或 relations 里写一笔，不能只改背包。
participants 和 witnesses 填下面角色表中的数字 id。提到一个人的名字不代表他在场或知情。
visibility 默认 witnessed；只有正文明确写出已经传播/公告的事件可填 public。私聊事件不能公开。
relations/npc_notes/npc_places 的角色键优先写 npc:数字id，地名使用完整登记名称。
已有的伤势痊愈、物品给出、目标结束时，相关近况或处境写 null 删除，不能留下过期事实。
引擎已结算的移动、数值、物品和关系效果不可再次应用。
建议行动、摘要和传闻不能代替状态更新。不要把历史回忆当作本回合新变化。
"""


class SettlementConflict(ValueError):
    pass


def capture(sess) -> dict:
    return {field: copy.deepcopy(getattr(sess, field, None)) for field in STATE_FIELDS}


def public_report(report: dict | None) -> dict | None:
    return {key: report[key] for key in PUBLIC_KEYS if key in report} if report else None


def normalize_proposal(data: dict) -> dict:
    npc_places = data.get("npc_places")
    if isinstance(npc_places, dict):
        # 空串是「她回去了，这一格清掉、作息表重新说了算」的约定写法，是一种变化
        # 而不是没填。从前在这里被当成空值筛掉，于是整个 npc_places 变成 {}，
        # 下游看见「声称有变化却什么都没写」，scene 域连同地点一起整域打回
        data["npc_places"] = {
            identity: place.strip() for identity, place in npc_places.items()
            if isinstance(place, str)
        }
    return data


def _normalized_evidence(text: str) -> str:
    """Normalize harmless formatting differences while retaining the original quote."""
    folded = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(char for char in folded if not unicodedata.category(char).startswith("P") and not char.isspace()).lower()


def _quote_in_narration(quote: str, narration: str) -> bool:
    normalized_quote = _normalized_evidence(quote)
    normalized_narration = _normalized_evidence(narration)
    return bool(normalized_quote) and normalized_quote in normalized_narration


def _mentioned_text(value: str, text: str) -> bool:
    needle = _normalized_evidence(value)
    haystack = _normalized_evidence(text)
    return bool(needle) and needle in haystack


def _name_mentioned(name: str, text: str) -> bool:
    key = _normalized_evidence(name)
    haystack = _normalized_evidence(text)
    if not key or not haystack:
        return False
    if key in haystack:
        return True
    return len(key) >= 3 and (key[:2] in haystack or key[-2:] in haystack)


def _place_ref(value, places):
    if not isinstance(value, str):
        return value
    names = [place.name.strip() for place in places if getattr(place, "name", None) and place.name.strip()]
    if not names:
        return value.strip()
    key = norm_name(value)
    exact = [real for real in names if norm_name(real) == key]
    if len(exact) == 1:
        return exact[0]
    hits = [real for real in names if len(norm_name(real)) >= 2 and norm_name(real) in key]
    if len(hits) == 1:
        return hits[0]
    reverse = [real for real in names if len(key) >= 2 and key in norm_name(real)]
    if len(reverse) == 1:
        return reverse[0]
    return value.strip()


def _entity_candidates(narration, npcs, places, inventory):
    """Find registered entities mentioned with full names, short forms, or keywords."""
    text = str(narration or "")
    people = []
    for npc in npcs or []:
        aliases = [npc.name, *(str(npc.keywords or "").replace("，", ",").split(","))]
        if any(_mentioned_text(alias, text) for alias in aliases if isinstance(alias, str) and alias.strip()):
            people.append({"id": npc.id, "name": npc.name})
    places_found = []
    for place in places or []:
        if place.name and _mentioned_text(place.name, text):
            places_found.append(place.name)
    items_found = []
    for item in inventory or []:
        if isinstance(item, dict) and item.get("name") and _mentioned_text(item["name"], text):
            items_found.append(item["name"])
    return {"characters": people, "places": places_found, "items": items_found}


# 报上来的类别 → 存进 sess.discoveries 的 kind。顺序就是同名去重的优先级：
# 一个名字既像人又像地方时，按人处理——建错了删一行，漏建一个人代价更大。
# 技能和任务排在最后：它俩最容易和道具撞名（「破军刀」既是件东西也是一招）
DISCOVERY_KINDS = (
    ("characters", "npc"), ("places", "place"), ("items", "item"),
    ("skills", "skill"), ("tasks", "task"),
)


def filter_discoveries(data, narration, npcs, places, inventory, items, message_id,
                       pending=(), skills=(), tasks=(), owned=(), claims=()):
    """从结算 JSON 的 discoveries 里挑出真正没登记过的名字。

    模型报什么一律不作数，全部本地复核：名字得在正文里真出现过，hint 得是正文
    原话，而且不能撞上任何已登记的角色（含别名）、地点、模组道具或背包里的写法。
    同名跨类只留优先级最高的一类，免得同一个名字建出两行。

    pending 是这一局已经挂在待办里、还没处理的发现项。一个人只要还在正文里被
    反复提起，每回合都会被重新报上来——不拿它去重的话，侧栏里就会堆出一串
    同名的行，作者得一条条点掉。**必须排除本条剧情自己上一轮记的那些**，
    否则同一条剧情重算时新结果会被旧结果挡住。

    skills / tasks 是模组里的技能和任务定义，owned 是本局已经会的招和已经接下的事
    （形状同 inventory，`[{"name": ...}]`）——两边都要看：剧情里刚学会但还没登记进
    模组的不算新发现，不然同一招每回合都会被重新报一遍。

    但模组里有定义**不足以**筛掉一招：技能和任务光有模组行这一局还用不了，得
    另外学会/接下（见 rpg.py 的 apply_discoveries 为什么要多调一次 learn_skill）。
    两个条件当一个用的话，「模组有行、这一局没拿到」就成了一个出不去的状态——
    发现报不上来，于是永远没人去学它。所以模组定义只挡**别的类别**（同名的
    人或东西还是不该重建），本类别只认 owned。

    claims 是挂在「道具栏待确认」里的东西（形状同 inventory）。一件东西该走哪条
    路是二选一的：玩家拿走了的走待确认（进背包，顺手在模组道具表里落一行定义，
    见 rpg.py 的 confirm_item_claim），没拿走的才走发现（只建档）。模板里写明了
    不许两边都报，但**光靠提示词管不住**——被认领的那几件在进背包之前就从 delta
    里摘掉了（见 apply_proposal），所以它们不在 working.inventory 里，也就不在上面
    那圈 known 里。模型哪天同一件东西两边都报，一件东西就出两条待办，得点两次。

    同小说侧 character_agent.filter_discovered 的路子——发现本身不额外调模型，
    是结算那一次调用顺带产出的，所以这里必须当成"不可信输入"来洗。
    """
    raw = data.get("discoveries")
    if not isinstance(raw, dict):
        return []
    known = set()
    for entry in pending or []:
        if isinstance(entry, dict):
            known.add(norm_name(entry.get("name") or ""))
    for npc in npcs or []:
        known.add(norm_name(npc.name))
        for alias in str(npc.keywords or "").replace("，", ",").split(","):
            known.add(norm_name(alias))
    for place in places or []:
        known.add(norm_name(place.name))
    for row in items or []:
        known.add(norm_name(row.name))
    for entry in [*(inventory or []), *(owned or []), *(claims or [])]:
        if isinstance(entry, dict):
            known.add(norm_name(entry.get("name") or ""))
    known.discard("")
    # 模组里定义过的技能/任务名。只挡**别的**类别：同名的人或东西不该再建一行，
    # 但同类别得放过去——这一局还没学会/接下的话，那一行就是个摆设，
    # 拦住它等于让玩家永远学不到（见上面 docstring）
    defined = {
        "skill": {norm_name(row.name) for row in skills or []} - {""},
        "task": {norm_name(row.name) for row in tasks or []} - {""},
    }

    found, seen, dropped = [], set(), []
    for key, kind in DISCOVERY_KINDS:
        # 模组里定义过的名字，只挡别的类别（skill 定义挡 item，不挡 skill 自己）
        blocked = {name for other, names in defined.items()
                   if other != kind for name in names}
        for entry in raw.get(key) or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()[:100]
            slug = norm_name(name)
            # 一个字的名字太容易是截断或代词，不收
            if len(slug) < 2 or slug in known or slug in blocked or slug in seen:
                dropped.append(f"{kind}:{name}:已登记或重复")
                continue
            # 名字这道关按类别松紧不一样，因为「名字」这个词对五类的意思不一样：
            # - 差事的名字是模型自己起的一句标签（「陪雏田去集市」），正文里写的是
            #   「能陪我一起去集市吗」——逐字永远对不上，查了就是把每一桩差事都
            #   误杀。它的依据是下面那道 hint 关（必须是正文原话），那一道够了
            # - 地方的名字常得带个归属才认得出是哪儿（正文「她的公寓门前」→
            #   「纲手的公寓」），所以用「半个名字也算」那把尺，同 _name_mentioned
            #   在这份文件里其它地方的用法
            # - 人、东西、本事的名字本来就原样写在正文里，照旧逐字查
            if kind == "task":
                named = True
            elif kind == "place":
                named = _name_mentioned(name, narration)
            else:
                named = _mentioned_text(name, narration)
            if not named:
                dropped.append(f"{kind}:{name}:名字不在正文里")
                continue
            hint = str(entry.get("hint") or "").strip()[:200]
            if not _quote_in_narration(hint, narration):
                dropped.append(f"{kind}:{name}:hint 不是正文原话")
                continue
            seen.add(slug)
            found.append({"id": uuid.uuid4().hex[:12], "kind": kind, "name": name,
                          "hint": hint, "message_id": message_id})
    # 四道关全是静默丢弃，不记一笔的话「模型压根没报」和「报了但被筛掉」
    # 在外面看起来一模一样，没法判断该调模板还是该调这里
    if dropped:
        logger.info("发现项被筛掉 %d 条（msg=%s）：%s", len(dropped), message_id, "；".join(dropped))
    return found


def filter_task_updates(data, narration, open_names, message_id, pending=()):
    """从结算 JSON 的 task_updates 里挑出能当**提议**的那几条。

    注意这里产出的是提议不是事实：任务算不算办完由玩家点头，模型只有提名权。
    所以三道关照抄 filter_discoveries——
      1. name 必须命中一桩**还开着**的待办（模型不能宣布你办完了一件没接的事）
      2. reason 必须是本回合正文里的原话（防止「我觉得他大概去了」这种脑补）
      3. 同名去重，且排除已经挂在待确认里的——一桩事只该弹一次窗

    pending 是这一局还没被玩家处理的提议。玩家点了「不算完」的那条会被路由
    从 pending 里删掉，下一回合正文要是又写到它，允许再提一次。
    """
    raw = data.get("task_updates")
    if not isinstance(raw, list):
        return []
    live = {norm_name(name): name for name in open_names or []}
    live.pop("", None)
    seen = {norm_name(p.get("name") or "") for p in (pending or []) if isinstance(p, dict)}
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        slug = norm_name(entry.get("name") or "")
        if slug not in live or slug in seen:
            continue
        action = str(entry.get("action") or "").strip().lower()
        if action not in ("done", "failed"):
            continue
        reason = str(entry.get("reason") or "").strip()[:200]
        if not _quote_in_narration(reason, narration):
            continue
        seen.add(slug)
        # name 存库里那一份写法，不存模型抄的——它可能少字，后面按名字改状态会找不着
        out.append({"id": uuid.uuid4().hex[:12], "name": live[slug],
                    "action": action, "reason": reason, "message_id": message_id})
    return out


def _is_new_gain(entry, held) -> bool:
    """这一条背包变化是不是「新拿到一件东西」——要玩家先点头的那种。

    切分（apply_proposal 把它从 delta 里摘掉）和挂待办（filter_item_claims）
    共用这一个判据。两处各写一遍迟早会漂移，而漂移的那一次是「摘掉了但没人报」
    ——东西既没进背包，也没出现在待确认里，凭空消失。
    """
    if not isinstance(entry, dict):
        return False
    qty = entry.get("qty")
    # bool 是 int 的子类，True 会被当成 1。同 apply_proposal 里那道校验
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        return False
    name = str(entry.get("name") or "").strip()
    return bool(name) and norm_name(name) not in held


def filter_item_claims(data, narration, inventory, items, message_id, pending=()):
    """从结算 JSON 的 inventory 里切出「玩家新拿到一件东西」，等玩家认领。

    判据见 _is_new_gain：正数、且背包里还没有同名。模组道具表里定义过的名字
    **照样要认**——定义里有只说明作者写过这件东西，不说明这一轮玩家真拿到了它。
    区别只在要不要问「一次性还是重复使用」：定义里已经有 consumable，所以带上
    known_item_id，前端凭它少问一句。

    pending 是本局已经挂着、还没处理的待确认道具，按名字去重：一件东西只要还在
    正文里被反复提起，每回合都会被重新报上来。**必须排除本条剧情自己上一轮记的
    那些**，否则同一条剧情重算时新结果会被旧结果挡住（同 filter_discoveries）。

    hint 取正文里提到它的那一句：名字往往只是个称呼（「那包药」），不摆原话
    玩家没法判断这到底是不是他真拿到的东西。同 filter_discoveries，这一路不额外
    调模型，所以模型报什么都当「不可信输入」洗一遍。
    """
    raw = data.get("inventory")
    if not isinstance(raw, list):
        return []
    held = {norm_name(item.get("name")) for item in (inventory or []) if isinstance(item, dict)}
    known = {norm_name(row.name): row for row in (items or [])}
    seen = {norm_name(entry.get("name") or "") for entry in (pending or []) if isinstance(entry, dict)}
    seen.discard("")

    out = []
    for entry in raw:
        if not _is_new_gain(entry, held):
            continue
        name = str(entry.get("name") or "").strip()[:100]
        slug = norm_name(name)
        # seen 挡的是跨回合的重复；同一份提议里把同一件东西分条列两遍也很常见，
        # 收进来之后立刻记上，这一轮内也只报一条
        if slug in seen:
            continue
        seen.add(slug)
        definition = known.get(slug)
        out.append({
            "id": uuid.uuid4().hex[:12], "name": name, "qty": int(entry["qty"]),
            "note": str(entry.get("note") or "").strip()[:200],
            "hint": _gain_hint(name, narration), "message_id": message_id,
            "known_item_id": definition.id if definition is not None else None,
        })
    return out


def _gain_hint(name, narration) -> str:
    """正文里提到这件东西的那一句。挑不到就空着——宁可不给依据，也不能给一句
    不是原话的话：玩家就是靠它判断该不该认下这件东西的。"""
    key = str(name or "").strip()
    if not key:
        return ""
    for sentence in re.split(r"[。！？\n]", str(narration or "")):
        text = sentence.strip()
        if text and _mentioned_text(key, text):
            return text[:200]
    return ""


def seed_settlement(sess, user_id, engine_before, engine_note, fixed_location, mode, private_with, present) -> dict:
    return {
        "status": "pending", "baseline": capture(sess), "engine_before": engine_before,
        "engine_note": engine_note, "fixed_location": fixed_location, "source_user_id": user_id,
        "mode": mode, "private_with": private_with, "origin_present": list(present or []),
        "clock": [sess.day, sess.slot, sess.turn_count], "attempts": 0, "retryable": True,
    }


def state_changes(before: dict, after: dict) -> tuple[dict, list[str]]:
    applied = {field: {"before": before.get(field), "after": after.get(field)}
               for field in STATE_FIELDS if before.get(field) != after.get(field)}
    lines = []
    if "location" in applied:
        lines.append(f"抵达 {after.get('location') or '未知地点'}")
    for name in sorted(set(before.get("stats") or {}) | set(after.get("stats") or {})):
        previous = (before.get("stats") or {}).get(name, 0)
        current = (after.get("stats") or {}).get(name, 0)
        if isinstance(previous, (float, int)) and isinstance(current, (float, int)) and previous != current:
            lines.append(f"{name} {current - previous:+g}")
    old_bag = {item["name"]: item.get("qty", 0) for item in before.get("inventory") or [] if isinstance(item, dict) and "name" in item}
    new_bag = {item["name"]: item.get("qty", 0) for item in after.get("inventory") or [] if isinstance(item, dict) and "name" in item}
    for name in sorted(old_bag.keys() | new_bag.keys()):
        amount = new_bag.get(name, 0) - old_bag.get(name, 0)
        if amount:
            lines.append(f"{name} {amount:+g}")
    for field, label in (("npc_notes", "人物近况已更新"), ("npc_states", "人物关系或相识记录已更新"),
                         ("npc_places", "人物位置已更新"), ("place_notes", "地点近况已更新"), ("flags", "处境已更新")):
        if field in applied:
            lines.append(label)
    # 归零的后果（check_zero 会把 status 置成 dead）从前只在黄色警告里挂一句，
    # 而 changes 这一行才是玩家真正会看的——一局结束了不该藏在警告里
    if "status" in applied and after.get("status") != "alive":
        lines.append("这一局结束了")
    return applied, lines


def rebase_state(baseline: dict, previous: dict, current: dict) -> tuple[dict, list[tuple]]:
    missing = object()
    protected = []

    def merge(original, applied, live, path):
        if applied == live:
            return copy.deepcopy(original) if original is not missing else missing
        if all(isinstance(value, dict) for value in (original, applied, live)):
            result = {}
            for key in original.keys() | applied.keys() | live.keys():
                value = merge(original.get(key, missing), applied.get(key, missing), live.get(key, missing), (*path, key))
                if value is not missing:
                    result[key] = value
            return result
        protected.append(path)
        return copy.deepcopy(live) if live is not missing else missing

    return merge(baseline, previous, current, ()), protected


def preserve_edits(state: dict, current: dict, paths: list[tuple]) -> None:
    for path in paths:
        target, source = state, current
        for key in path[:-1]:
            target = target.setdefault(key, {})
            source = source.get(key, {})
        if path[-1] in source:
            target[path[-1]] = copy.deepcopy(source[path[-1]])
        else:
            target.pop(path[-1], None)


def _npc_ref(value, npcs):
    name = str(value).strip()
    if name.startswith("npc:") and name[4:].isdigit():
        return next((npc for npc in npcs if npc.id == int(name[4:])), None)
    key = norm_name(name)
    exact = [npc for npc in npcs if norm_name(npc.name) == key]
    if len(exact) > 1:
        return None
    if len(exact) == 1:
        return exact[0]
    return match_npc(name, npcs)


def _evidence_events(data, narration, npcs, report):
    events, errors = [], []
    raw_events = data.get("events", [])
    if not isinstance(raw_events, list):
        return [], ["事件列表格式错误"]
    known = {npc.id: npc for npc in npcs}
    original = set(report.get("origin_present") or [])
    for event in raw_events:
        if not isinstance(event, dict):
            errors.append("事件格式错误")
            continue
        kind, quote = event.get("kind"), event.get("quote")
        if not isinstance(kind, str) or kind not in EVENT_KINDS or not isinstance(quote, str) or not quote.strip() or not _quote_in_narration(quote, narration):
            errors.append("事件缺少可核对的连续原文依据")
            continue
        participants = event.get("participants") or []
        witnesses = event.get("witnesses") or []
        domains = event.get("domains") or []
        if not all(isinstance(value, list) for value in (participants, witnesses, domains)):
            errors.append("事件人物或关联项目格式错误")
            continue
        possible = original | {npc.id for npc in npcs if npc.name and _name_mentioned(npc.name, quote)}
        if report.get("mode") == "private":
            possible = original
        participants = [identity for identity in participants if isinstance(identity, int) and identity in known and identity in possible]
        witnesses = [identity for identity in witnesses if isinstance(identity, int) and identity in possible]
        visibility = "witnessed"
        if event.get("visibility") == "public" and report.get("mode") != "private" and re.search(r"传开|传遍|众所周知|公告|公之于众|人尽皆知|公开宣布", quote):
            visibility = "public"
        domains = [domain for domain in domains if isinstance(domain, str) and domain in DOMAINS]
        required = {"move": "scene", "gain": "inventory", "loss": "inventory"}.get(kind)
        if required and required not in domains:
            domains.append(required)
        if kind == "transfer":
            domains = list(dict.fromkeys([*domains, "inventory", "characters"]))
        payload_domains = {
            domain for domain, keys in DOMAINS.items()
            if any(data.get(key) for key in keys)
        }
        domains = [domain for domain in domains
                   if domain in payload_domains or domain == required or kind == "transfer"]
        events.append({
            "kind": kind, "quote": quote, "summary": str(event.get("summary") or quote)[:120],
            "domains": domains,
            "participants": participants, "witnesses": witnesses, "visibility": visibility,
            **({key: event.get(key) for key in ("item", "qty", "from", "to")} if kind == "transfer" else {}),
        })
    return events, errors


def _suspected_events(narration, places, player_name, npcs):
    suspects = []
    for sentence in re.split(r"[。！？\n]", narration):
        sentence = sentence.strip()
        if not sentence or re.search(r"[“”「」『』\"]|如果|打算|准备|想要|听说|曾经|当年|没有|并未|还没|别去|不要", sentence):
            continue
        subject = rf"(?:你|{re.escape(player_name or '玩家')})"
        if re.search(subject + r"(?:终于|已经|径直|便|就|缓缓|悄悄|顺利|也|们|都|一行人)*.{0,12}(?:来到|抵达|到达|走进|进入|前往|奔向|赶往|返回|回到)", sentence):
            targets = [place.name for place in places if place.name and _mentioned_text(place.name, sentence)]
            if targets:
                suspects.append(("scene", sentence, max(targets, key=len)))
        # 只加确实指向「东西易手」的词。这一条命中之后是**硬**问题（见下面
        # 「疑似漏记关键事件」和「关键事件缺少原文记录」），所以宁可漏抓也别错抓：
        # 「她递给你一个眼神」这种要是算进来，一整轮闲聊都会被打回
        if re.search(subject + r".{0,24}(?:获得|拿到|收下|接过|收起|揣进|捡起|取出|装入|买到|借到|归还|失去|用掉|吃掉|服下|丢弃|遗失|被夺|交给|递给|送给|交还)", sentence):
            suspects.append(("inventory", sentence, None))
        if re.search(r"受伤|中刀|伤口愈合|伤势痊愈|伤好了", sentence):
            domain = "characters" if any(npc.name and _name_mentioned(npc.name, sentence) for npc in npcs) else "flags" if re.match(subject, sentence) else "memory"
            suspects.append((domain, sentence, None))
        if re.search(r"拜师|结拜|认亲|发誓|承诺|答应|许诺|道谢|感谢|原谅|信任|结仇|救命之恩", sentence):
            suspects.append(("characters" if any(npc.name and _name_mentioned(npc.name, sentence) for npc in npcs) else "memory", sentence, None))
        if re.search(subject + r".{0,20}(?:疲惫|精疲力竭|精力|体力|灵力|法力|气血|金钱|银两|灵石|声望|威望|积分).{0,12}(?:下降|减少|增加|恢复|耗尽|获得|损失|提升|降低|变得)", sentence):
            suspects.append(("stats", sentence, None))
    return suspects


# 判定失败时「付了账」算哪几个键。**没有 npc_notes**：「她皱了下眉」是文字，
# 不是代价。inventory 算，丢一件东西是实打实的损失
COST_KEYS = ("stats", "flags", "relations", "inventory")
# 从 OUTCOME_LABELS 反推，别手写「失败」「大失败」两个字面量——
# 进结算的是中文档位名（见 settle_turn 的 label），改档位名时这里要跟着变
FAIL_LABELS = {OUTCOME_LABELS["fail"], OUTCOME_LABELS["crit_fail"]}
# repair 轮也没给出代价时引擎兜底立的那一条。固定一个键名，所以连着失手几次
# 只有一条，不会糊一屏
FAIL_FLAG = "这一次失手了"


def _costless_failure(data, report) -> bool:
    """判定掷出了失败，而这一轮谁都没付账。

    这是「数值不是事实来源」最贵的一种表现：骰子说没成，正文写「你勉力撑住」，
    结算交上来一份空 delta——于是失败的唯一后果是多看了一段字。失败不疼，
    判定就只是掷骰子的动画。

    **引擎已经扣过就不算**：点按钮那条路 effects 是作者写死的，扣完才轮到判定，
    这时候模型交空 delta 是对的（账已经结了，再扣一遍就是双花）。判据是
    engine_before 和 baseline 之间有没有差，同 _block_engine_duplicates 的口径。

    掷骰默认是关的（check_mode="never"），那时 outcome_label 是空串，这里一路
    返回 False——所以这条门禁只在作者真的开了判定之后才生效。
    """
    if report.get("outcome_label") not in FAIL_LABELS:
        return False
    if any(data.get(key) for key in COST_KEYS):
        return False
    before, after = report.get("engine_before") or {}, report.get("baseline") or {}
    return not any(before.get(field) != after.get(field)
                   for field in ("stats", "inventory", "flags", "status"))


def inspect_proposal(data, narration, npcs, places, report, player_name):
    """核对模型交上来的结算 JSON。返回 (硬问题, 软提示, 已取证的事件)。

    **硬问题**一票否决：那个域一个字都不写。**软提示**只挂在报告里，照常应用。
    分这两档是因为从前只有一档，而模型在长模板下漏一个字段是常态，代价却是
    「整域不写」——最常见的表现就是玩家写了「我要去酒馆」，模型也填了
    location，只因为漏了一句 checks.scene，地点就纹丝不动。
    """
    issues = {domain: [] for domain in DOMAINS}
    soft = {domain: [] for domain in DOMAINS}
    checks = data.get("checks") if isinstance(data.get("checks"), dict) else {}
    for domain, keys in DOMAINS.items():
        if not isinstance(checks.get(domain), str) or checks[domain] not in {"changed", "unchanged"}:
            # 漏写核对声明是模型没守契约，不是玩家的状态有问题：记一笔，照常应用
            soft[domain].append("尚未明确核对")
        elif checks[domain] == "changed" and not any(data.get(key) for key in keys):
            issues[domain].append("已报告变化，但缺少对应更新")
        for key in keys:
            if key not in data:
                continue
            expected = list if key in {"inventory", "events", "chronicle"} else str if key == "location" else dict
            if not isinstance(data[key], expected):
                issues[domain].append(f"{key} 格式错误")
    events, errors = _evidence_events(data, narration, npcs, report)
    issues["memory"].extend(errors)

    checks = data.get("checks") if isinstance(data.get("checks"), dict) else {}
    for domain, keys in DOMAINS.items():
        if checks.get(domain) != "changed" or any(data.get(key) for key in keys):
            continue
        if not any(domain in event["domains"] for event in events):
            issues[domain] = [warning for warning in issues[domain]
                              if warning != "已报告变化，但缺少对应更新"]

    if data.get("chronicle") and not any(event["visibility"] == "public" for event in events):
        issues["memory"].append("公共大事记缺少正文中的传播或公告依据")
    for domain, keys in DOMAINS.items():
        if domain == "memory" or not any(data.get(key) for key in keys):
            continue
        if domain == "scene" and report.get("fixed_location") is not None and not any(data.get(key) for key in ("npc_places", "place_notes")):
            continue
        if not any(domain in event["domains"] for event in events):
            # 这条是防幻觉的门禁：凭空加的数值必须有正文依据。但地点另有一层
            # 硬校验（必须在登记地点表里，还要过 enter_requires），幻觉地名根本
            # 进不来，于是这一条对它只剩副作用——模型填对了地点、忘了写 event，
            # 人就留在原地。只放宽「这一轮 scene 域只改了 location」这一种情况
            only_location = domain == "scene" and not any(
                data.get(key) for key in ("npc_places", "place_notes"))
            (soft if only_location else issues)[domain].append("状态变化缺少关联的原文依据")
    for event in events:
        for domain in event["domains"]:
            if domain != "memory" and not any(data.get(key) for key in DOMAINS[domain]):
                if domain == "scene" and report.get("fixed_location") is not None:
                    continue
                issues[domain].append(f"事件尚未回填：{event['quote'][:60]}")
        if event["kind"] == "transfer":
            for domain in ("inventory", "characters"):
                if not any(data.get(key) for key in DOMAINS[domain]):
                    issues[domain].append(f"物品交接尚未同时核对背包和人物持有情况：{event['quote'][:60]}")
            item, quantity = event.get("item"), event.get("qty")
            source, target = event.get("from"), event.get("to")
            other = target if source == "player" else source
            npc = _npc_ref(other, npcs)
            bag = data.get("inventory")
            inbound = target == "player"
            entries = [entry for entry in bag if isinstance(entry, dict)] if isinstance(bag, list) else []
            # 背包里对得上名字的那一条。对不上很正常：正文写「几颗丹药」，
            # 模型的 item 就写「丹药」，而背包记的是固元丹、安神丹、春阳丹——
            # 这不是造假，是一次交接落成了好几条。所以名字对不上就退一步，
            # 只看背包有没有朝正确的方向动
            named = [entry for entry in entries if norm_name(entry.get("name")) == norm_name(item)]
            checked = named or entries
            # 数量只看正负号。event 里的 qty 和背包的 qty 都是同一个模型写的，
            # 逐个数字比对只能查出它自己前后不一致，查不出它有没有骗人；
            # 真正要拦的是「说给了你，背包却少了一件」这种反向
            matched = any(isinstance(entry.get("qty"), int) and not isinstance(entry.get("qty"), bool)
                          and (entry["qty"] > 0 if inbound else entry["qty"] < 0)
                          for entry in checked)
            # 交接必须两边都记一笔，不能只改背包。但只要求「这个人这一轮被写到了」：
            # 从前还要求 NPC 给东西时必须往 npc_notes 里写一个 null 去删旧近况——
            # 可她要是本来就没有一条「身上带着丹药」的近况，就没有东西可删，
            # 于是这条永远过不去，所有「NPC 掏东西给你」的回合都被打回
            has_owner = npc is not None and any(
                isinstance(block, dict) and any(_npc_ref(key, npcs) is npc for key in block)
                # 就是 DOMAINS["characters"] 那两个键，别换成 npc_states——
                # 那是会话列的名字，模型从来不写它
                for block in (data.get("npc_notes"), data.get("relations"))
            )
            if not isinstance(item, str) or not item or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0 or npc is None or not matched or not has_owner:
                issues["inventory"].append("物品交接缺少匹配的物品数量、交接对象或持有状态")
                issues["characters"].append("物品交接缺少匹配的物品数量、交接对象或持有状态")
    suspects = _suspected_events(narration, places, player_name, npcs)
    last_destination = next((entry[2] for entry in reversed(suspects) if entry[0] == "scene"), None)
    for domain, quote, destination in suspects:
        if domain == "scene" and report.get("fixed_location") is not None:
            if destination != report["fixed_location"]:
                issues["scene"].append(f"剧情抵达「{destination}」，与引擎地点「{report['fixed_location']}」冲突")
            continue
        if domain == "scene" and destination == (report.get("baseline") or {}).get("location"):
            continue
        if domain == "scene" and destination == last_destination and data.get("location") != destination:
            issues["scene"].append(f"正文已抵达「{destination}」，结算地点尚未对应")
        if not any(data.get(key) for key in DOMAINS[domain]):
            issues[domain].append(f"疑似漏记关键事件：{quote[:80]}")
        if domain == "inventory" and re.search(r"交给|递给|送给", quote) and any(npc.name and npc.name in quote for npc in npcs):
            if not any(event["kind"] == "transfer" and (event["quote"] in quote or quote in event["quote"]) for event in events):
                issues["inventory"].append("物品交接需要同时核对背包与接收人的持有状态")
                issues["characters"].append("物品交接需要同时核对背包与接收人的持有状态")
        if not any(event["quote"] in quote or quote in event["quote"] for event in events):
            issues["memory"].append(f"关键事件缺少原文记录：{quote[:80]}")
    if _costless_failure(data, report):
        # 判成硬问题（而不是 soft）就是为了走 repair 那一轮——那是这一整条
        # 门禁的正身，兜底的 flag 只是 repair 也不肯给时的下限。
        #
        # 两个域都挂：repair 回来之后只有 repairs 里那些域的键会被搬进 data
        # （见 settle_turn 那圈 for domain in repairs），只挂 stats 的话模型
        # 答了一条 flag 也会被原地丢掉。这一路上 stats/flags 本来都是空的
        # （_costless_failure 的前提），所以打回去不会赔掉任何已经填对的东西
        for domain in ("stats", "flags"):
            issues[domain].append(
                f"判定结果是「{report.get('outcome_label')}」，但这一轮没有任何代价："
                "扣一项数值或立一条处境标记，并在 events 里附上正文里对应的那句话"
            )
    return issues, soft, events


def _block_engine_duplicates(delta, report):
    before = report.get("engine_before") or {}
    after = report["baseline"]
    for field in ("stats",):
        changes = delta.get(field)
        if isinstance(changes, dict):
            delta[field] = {key: value for key, value in changes.items()
                            if (before.get(field) or {}).get(key) == (after.get(field) or {}).get(key)}
    old_bag = {item.get("name"): item.get("qty") for item in before.get("inventory") or [] if isinstance(item, dict)}
    new_bag = {item.get("name"): item.get("qty") for item in after.get("inventory") or [] if isinstance(item, dict)}
    if isinstance(delta.get("inventory"), list):
        delta["inventory"] = [item for item in delta["inventory"] if not isinstance(item, dict) or old_bag.get(item.get("name")) == new_bag.get(item.get("name"))]
    if report.get("fixed_location") is not None:
        delta.pop("location", None)


def _event_groups(events):
    """必须整组一起成立、否则整组都不写的域。

    只有物品交接是这种关系：背包少一件和接收人多一件必须同时成立，只写一边
    就是凭空造物或凭空蒸发（CONTRACT 里写死的约定）。

    从前这里算的是所有事件 domains 的**传递闭包**：事件 A(scene,stats) 和事件
    B(stats,inventory) 只要共用 stats 就焊成一组，于是背包差一个数量能把地点
    一起回滚回去。爆炸半径和「一致性」没关系，纯粹是事件恰好挨着。
    """
    return [{"inventory", "characters"}] if any(event["kind"] == "transfer" for event in events) else []


def apply_proposal(module, working, data, npcs, places, report, issues, soft, events,
                   items=(), pending_claims=(), message_id=None):
    delta = copy.deepcopy(data)
    _block_engine_duplicates(delta, report)
    # 「新拿到一件东西」先摘出来，不进背包：那是模型读正文得出的判断，读歪了玩家
    # 得有个划掉的地方，而背包进去了就只剩「用掉」一个出口（见 models.item_claims）。
    #
    # 摘在这里而不是在 settle_turn 里改 data，两个理由：
    #   1. data 要原样存进 report["proposed"]、还要回喂给修复那一轮。动它等于改了
    #      模型的原始提议，事后对不上账——delta 是本函数一进来就 deepcopy 的副本，
    #      改动只活在这一趟里（同 _block_engine_duplicates 的做法）
    #   2. 本函数会被 dry-run 跑第二遍。摘取是纯函数，两遍算出同一份结果，不会
    #      出现「第一遍摘了第二遍没摘」这种只在某条路径上现形的 bug
    #
    # 引擎这一轮自己发过的东西（玩家点「使用」那条路）不会重复挂待确认：它已经写进
    # working.inventory 了，held 里有同名，_is_new_gain 直接判 False
    held = {norm_name(item.get("name")) for item in (working.inventory or []) if isinstance(item, dict)}
    item_claims = filter_item_claims(data, report.get("narration"), working.inventory,
                                     items, message_id, pending_claims)
    if isinstance(delta.get("inventory"), list):
        # 被 pending 去重挡掉、因而没进 item_claims 的那些也一样要摘：它既不该进
        # 背包，也不该报第二遍——玩家点上一轮那条确认时，东西自然会进去
        delta["inventory"] = [entry for entry in delta["inventory"] if not _is_new_gain(entry, held)]
    known_places ={place.name.strip(): place for place in places if place.name and place.name.strip()}
    if working.location:
        known_places.setdefault(working.location, None)
    available = world_npcs(npcs)
    original = set(report.get("origin_present") or [])
    named = {npc.id for npc in available if npc.name and _name_mentioned(npc.name, report["narration"])}
    allowed = original | named
    if report.get("mode") == "private":
        allowed = original
    mapped = {}
    amounts = delta.get("stats")
    if isinstance(amounts, dict):
        for key, amount in amounts.items():
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
                issues["stats"].append(f"数值「{key}」的增减量不是有效数字")
    bag = delta.get("inventory")
    if isinstance(bag, list):
        balances = {norm_name(item.get("name")): item.get("qty", 0) for item in working.inventory or [] if isinstance(item, dict)}
        for item in bag:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip() or isinstance(item.get("qty"), bool) or not isinstance(item.get("qty"), int):
                issues["inventory"].append("背包变化必须包含物品名称和整数增减量")
            else:
                name = norm_name(item["name"])
                balances[name] = balances.get(name, 0) + item["qty"]
        if any(quantity < 0 for quantity in balances.values()):
            issues["inventory"].append("失去或交出的物品数量超过当前持有数量")
    flags = delta.get("flags")
    if isinstance(flags, dict) and any(isinstance(value, (dict, list)) for value in flags.values()):
        issues["flags"].append("处境必须使用扁平字段，不能包含对象或数组")
    for key, domain in (("relations", "characters"), ("npc_notes", "characters"), ("npc_places", "scene")):
        changes = delta.get(key)
        mapped[key] = {}
        if not isinstance(changes, dict):
            continue
        for reference, value in changes.items():
            npc = _npc_ref(reference, available)
            if npc is None or npc.id not in allowed:
                issues[domain].append(f"人物「{reference}」未唯一匹配或未参与本轮")
                continue
            if key == "npc_places":
                if not isinstance(value, str):
                    issues[domain].append(f"人物「{npc.name}」的目的地未登记")
                    continue
                canonical = _place_ref(value, places)
                if value and canonical not in known_places:
                    issues[domain].append(f"人物「{npc.name}」的目的地未登记")
                    continue
                value = canonical
            if key in {"relations", "npc_notes"} and value is not None and not isinstance(value, dict):
                issues[domain].append(f"人物「{npc.name}」的变化格式错误")
                continue
            if key == "npc_notes" and isinstance(value, dict) and any(entry is not None and not isinstance(entry, str) for entry in value.values()):
                issues[domain].append(f"人物「{npc.name}」的近况必须是文字或 null")
                continue
            if key == "npc_notes":
                existing = (working.npc_notes or {}).get(str(npc.id)) or {}
                merged = {**existing, **(value or {})} if value is not None else {}
                conflict = fact_guard.check_life_death(existing, merged)
                if conflict:
                    issues[domain].append(f"{npc.name}：{conflict['reason']}")
                    continue
            if key == "relations":
                if not isinstance(value, dict) or any(isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) for amount in value.values()):
                    issues[domain].append(f"人物「{npc.name}」的关系增减量不是有效数字")
                    continue
                engine_before = (report.get("engine_before") or {}).get("npc_states") or {}
                engine_after = report["baseline"].get("npc_states") or {}
                value = {stat: amount for stat, amount in value.items()
                         if (engine_before.get(str(npc.id)) or {}).get(stat) == (engine_after.get(str(npc.id)) or {}).get(stat)}
            mapped[key][str(npc.id)] = value
    # 地名没登记时只扣下 location 这一个字段，不整域打回。挂在这里而不是
    # issues["scene"]：issues 会让整个 scene 域判为 needs_review，连同一轮里
    # 「谁走到哪了」「门被踹坏了」一起赔掉——那两件事和这个地名没有任何关系。
    # 也没挂 soft，因为 soft 不参与 status，scene 会变成 done，前端那颗
    # 「仅重新结算」按钮就不出现了（SettlementReport.tsx 只在未完成时给它），
    # 而下面这句话正是让作者去点它的。走 warnings 得到 partial：scene 不在
    # _event_groups 的任何一组里，partial 不会触发组回滚，字段留得住
    location_warning = None
    destination = delta.get("location")
    if destination and isinstance(destination, str):
        canonical = _place_ref(destination, places)
        if known_places and canonical not in known_places:
            # 后面半句是出路，不是补充说明：看到这条的人十有八九不知道下一步该干
            # 什么，就以为这一轮废了。说成「要是」而不是「已记进新发现」——发现项
            # 是这一趟结算的末尾才算的（见下面 filter_discoveries 的调用），
            # 模型没报或者被洗掉的话这儿就成了假话
            delta.pop("location", None)
            location_warning = (
                f"目的地「{destination}」未登记，这一轮没有移动你。"
                "要是这地方该有，到侧栏「新发现」里加进模组，再点「仅重新结算」")
        else:
            delta["location"] = canonical
            destination = canonical
        if destination in known_places and known_places.get(destination) is not None and destination != working.location:
            passed, reason = check_condition(known_places[destination].enter_requires, working, npcs)
            if not passed:
                issues["scene"].append(f"无法进入「{destination}」：{reason}")
    groups = _event_groups(events)
    # 人工改过的字段不让 AI 覆盖。这一档按**域**算而不是跟着事件组走：组现在只剩
    # 物品交接一种，跟着组走的话别的域就完全没有保护了。
    #
    # 但只在 AI 这一轮**真的要写**这个域的时候才拦：它什么都不写的时候整域盖回
    # live_state，会把 rebase_state 刚算对的那些回退又按回去（重算一条被手工删掉
    # 的近况时，同一个人另一条该恢复成基线的字段会被留在旧值上）
    protected_fields = {path[0] for path in report.get("protected_paths", []) if path}
    for domain, keys in DOMAINS.items():
        if domain == "memory" or not any(delta.get(key) for key in keys):
            continue
        if not protected_fields.intersection(DOMAIN_FIELDS[domain]):
            continue
        for field in DOMAIN_FIELDS[domain]:
            value = copy.deepcopy(report["live_state"][field])
            setattr(working, field, value)
            report["working_before"][field] = copy.deepcopy(value)
        issues[domain].append("这一项包含人工修改，已保留当前值，需要人工核对")
    for related in groups:
        if any(issues[domain] for domain in related):
            for domain in related:
                issues[domain].append("关联事件未完整通过校验，本组暂不应用")
    reports = {}
    for domain, keys in DOMAINS.items():
        before = capture(working)
        if issues[domain]:
            reports[domain] = {"status": "needs_review",
                               "warnings": list(dict.fromkeys([*issues[domain], *soft.get(domain, [])]))}
            continue
        warnings = []
        if domain == "scene" and location_warning:
            warnings.append(location_warning)
        try:
            if domain == "memory":
                pass
            else:
                portion = {key: delta[key] for key in keys if key in delta and key not in mapped}
                warnings.extend(apply_state_delta(module, working, portion, available,
                                                  note_npcs=[npc for npc in available if npc.id in allowed],
                                                  move_npcs=[npc for npc in available if npc.id in allowed],
                                                  places=list(known_places), finalize=False))
                for key in keys:
                    for identity, value in mapped.get(key, {}).items():
                        npc = next(npc for npc in available if npc.id == int(identity))
                        warnings.extend(apply_state_delta(module, working, {key: {npc.name: value}}, [npc],
                                                          note_npcs=[npc], move_npcs=[npc], places=list(known_places), finalize=False))
        except Exception as error:
            for field, value in before.items():
                setattr(working, field, value)
            warnings.append(f"{LABELS[domain]}应用失败：{type(error).__name__}")
        changed = any(before.get(field) != getattr(working, field) for field in DOMAIN_FIELDS[domain])
        # 软提示只挂在报告里，不参与 status：让它把状态压成 partial 的话，
        # 下面那轮组回滚会把刚写进去的东西又抹掉，等于没放宽
        reports[domain] = {"status": "partial" if warnings else "updated" if changed else "unchanged",
                           "warnings": list(dict.fromkeys([*warnings, *soft.get(domain, [])]))}
    for related in groups:
        if any(reports[domain]["status"] in {"partial", "needs_review"} for domain in related):
            for domain in related:
                for field in DOMAIN_FIELDS[domain]:
                    setattr(working, field, copy.deepcopy(report["working_before"].get(field)))
                reports[domain] = {"status": "needs_review", "warnings": [*reports[domain]["warnings"], "关联事件未完整应用，已保留本组原状态"]}
    zero_warnings = check_zero(module, working)
    reports["stats"]["warnings"].extend(zero_warnings)
    # 填满的后果同归零：算在 working 上，跟着 after 一起写回会话
    reports["stats"]["warnings"].extend(check_full(module, working))
    here = turn_present(available, working, report.get("mode", "group"), report.get("private_with"))
    mark_met(working, [npc.id for npc in here])
    facts = [event for event in events if event["kind"] != "state" and not any(reports[domain]["status"] in {"partial", "needs_review"} for domain in event["domains"])]
    if reports["memory"]["status"] == "needs_review":
        facts = []
    elif facts:
        push_chronicle(working, [event["summary"] for event in facts if event["visibility"] == "public"])
        reports["memory"]["status"] = "updated"
    return reports, facts, here, item_claims


def _working(sess, state):
    # tasks 跟 day/slot 一样是"带过来给模板看的"，不在 STATE_FIELDS 里，
    # 也就不会被结算结果覆写回去——任务状态只认玩家点头
    return SimpleNamespace(**copy.deepcopy(state), day=sess.day, slot=sess.slot,
                           time_slots=sess.time_slots, turn_count=sess.turn_count,
                           tasks=copy.deepcopy(sess.tasks or []))


def _open_tasks(sess) -> list[dict]:
    """喂给结算模板的待办清单。只列还开着的，最多 10 条——判定依据是
    objective（作者写的「怎样算办完」），剧情里冒出来的差事没有，就用描述顶上。"""
    rows = []
    for task in (getattr(sess, "tasks", None) or []):
        if not isinstance(task, dict) or str(task.get("status") or "open") != "open":
            continue
        name = str(task.get("name") or "").strip()
        if not name:
            continue
        rows.append({"name": name, "goal": str(task.get("goal") or task.get("desc") or "")[:120]})
    return rows[:10]


def _prompt(module, sess, npcs, places, narration, label, report, place_block):
    participants = [npc for npc in world_npcs(npcs)
                    if npc.id in report.get("origin_present", []) or (npc.name and _name_mentioned(npc.name, narration))]
    if report.get("mode") == "private":
        participants = [npc for npc in participants if npc.id in report.get("origin_present", [])]
    stat_specs = def_map(module.stat_defs)
    relation_specs = def_map(module.relation_stat_defs)
    states = sess.npc_states or {}
    # 每轮变化上限。两张表并成一份给模型看：同名又不同上限的话这句提示会说错
    # 一个数，但**夹取本身不受影响**——apply_state_delta 两路各查各的 def_map
    step_caps = {name: spec["step_max"] for name, spec in {**stat_specs, **relation_specs}.items()
                 if spec.get("step_max") is not None}
    prompt = render(
        # outcome_failed 是从 label 推出来的，不另传一个档位键：先跟模型把
        # 「失败要留代价」说在前面，比等它交了空 delta 再打回去便宜一整轮调用
        "rpg_settle.jinja2", narration=narration, outcome_label=label,
        outcome_failed=label in FAIL_LABELS,
        stats=sess.stats or {}, location=sess.location or "",
        place_note=(sess.place_notes or {}).get(sess.location, ""),
        inventory=sess.inventory or [], flags=sess.flags or {},
        # 关系值要带**当前数字**，不能只给名字：不给的话模型无从判断「她已经
        # 90 了」还是「刚认识」，只能闭着眼给增量，于是好感一路涨到顶。
        # 只挑定义过的键，把 met 这类内部标记挡在外面
        npcs=[{
            "id": npc.id, "name": npc.name,
            "notes": (sess.npc_notes or {}).get(str(npc.id), {}),
            "relations": {name: value for name, value in (states.get(str(npc.id)) or {}).items()
                          if name in relation_specs},
        } for npc in participants],
        note_keys=sorted({key for notes in (sess.npc_notes or {}).values() if isinstance(notes, dict) for key in notes}),
        relation_names=list(relation_specs), step_caps=step_caps,
        engine_note=report.get("engine_note", ""), chronicle=(sess.chronicle or [])[-10:],
        # 还开着的待办。模型只能在这份清单里挑「看着像办完了」的，挑不出就别提
        tasks=_open_tasks(sess),
        # 有时段才问「这一幕收尾了吗」。没时钟的模组问了也没处用——
        # 那颗按钮根本不出现。同 outcome_label / tasks 的条件渲染
        has_clock=bool(str(getattr(sess, "slot", "") or "").strip()),
    )
    prompt += place_block(participants, [place.name for place in places], sess)
    prompt += CONTRACT
    prompt += "\n角色表：" + json.dumps([
        {"id": npc.id, "name": npc.name, "location": npc_place(npc, sess.slot, sess.npc_places)} for npc in participants
    ], ensure_ascii=False)
    prompt += "\n地点表：" + json.dumps([place.name for place in places], ensure_ascii=False)
    candidates = _entity_candidates(narration, world_npcs(npcs), places, sess.inventory or [])
    prompt += "\n=== 正文实体候选（仅作提取提示，不能据此虚构变化）===\n" + json.dumps(candidates, ensure_ascii=False)
    if report.get("source_action"):
        prompt += "\n=== 本轮玩家输入（仅辅助理解意图，状态变化必须引用上方正文）===\n" + str(report["source_action"])
    prompt += "\n请逐句扫描本回合正文，包括玩家输入造成的直接后果和对话承诺；凡正文明确发生的数值、物品、人物关系、位置或处境变化，都要在对应字段填写，并用 events.quote 引用原文。"
    if report.get("fixed_location") is not None:
        prompt += f"\n玩家地点已由引擎确定为「{report['fixed_location']}」，不得改写。"
    return prompt


async def _claim(store, sess):
    stamp = datetime.utcnow()
    result = await store.execute(
        update(RpgSession).where(RpgSession.id == sess.id, RpgSession.updated_at == sess.updated_at)
        .values(updated_at=stamp).execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise SettlementConflict("游戏状态正在改变，请稍后重试结算")
    sess.updated_at = stamp


async def _require_latest(store, row):
    later = (await store.execute(select(RpgMessage.id).where(
        RpgMessage.session_id == row.session_id, RpgMessage.id > row.id,
    ).limit(1))).scalar()
    if later is not None:
        raise SettlementConflict("这段剧情之后已有新回合。请使用对应玩家消息的「改完重发」回滚重玩，不能直接覆盖后续状态")


async def settle_turn(session_id, message_id, narration, label, engine_note, fixed_location,
                      session_factory, json_call, place_block):
    attempt = uuid.uuid4().hex
    async with session_factory() as store:
        sess = await store.get(RpgSession, session_id)
        row = await store.get(RpgMessage, message_id)
        if sess is None or row is None or row.session_id != session_id or row.role != "assistant":
            raise SettlementConflict("只能结算已保存的 GM 剧情")
        if row.content != narration or not narration.strip():
            raise SettlementConflict("剧情已改变，请刷新后重新结算")
        report = copy.deepcopy(row.settlement or {})
        revision = text_revision(narration)
        if report.get("invalidated_by"):
            raise SettlementConflict("前面的剧情已修改，本回合依赖的状态已经过期，请从对应玩家消息回滚重玩")
        if report.get("status") == "done" and report.get("revision") == revision:
            return {"state": capture(sess), "warnings": [], "suggestions": row.suggestions or [],
                    "outcome_consistent": None, "aux_input_tokens": 0, "aux_output_tokens": 0,
                    "settlement": public_report(report), "discoveries": [],
                    "item_claims": [], "scene_wrapped": False}
        if not report.get("baseline"):
            raise SettlementConflict("这条旧剧情没有独立结算基线，请从对应玩家消息回滚重玩；直接补算可能重复扣除物品或数值")
        await _claim(store, sess)
        await _require_latest(store, row)
        if report.get("status") == "running":
            started = datetime.fromisoformat(report["started_at"])
            if datetime.utcnow() - started < timedelta(minutes=10):
                raise SettlementConflict("这一轮正在结算，请等待完成后再试")
        if report.get("clock") != [sess.day, sess.slot, sess.turn_count]:
            raise SettlementConflict("此后游戏时间已推进，请先读档或回滚到这一回合再重新结算")
        module = await store.get(RpgModule, sess.module_id)
        npcs = list((await store.execute(select(RpgNpc).where(RpgNpc.module_id == module.id))).scalars())
        places = list((await store.execute(select(RpgLocation).where(RpgLocation.module_id == module.id))).scalars())
        # 模组道具表：结算本身用不着它（背包按名字走），但判断"这件东西登记过没有"要看。
        # 技能表和任务表同理，只服务发现去重
        items = list((await store.execute(select(RpgItem).where(RpgItem.module_id == module.id))).scalars())
        skills = list((await store.execute(select(RpgSkill).where(RpgSkill.module_id == module.id))).scalars())
        tasks = list((await store.execute(select(RpgTask).where(RpgTask.module_id == module.id))).scalars())
        # 已经挂着的待确认道具，拿去按名字去重。**排除本条剧情自己上一轮记的**，
        # 否则重算时新结果会被旧结果挡住（同下面 discoveries 的 kept）
        pending_claims = [entry for entry in (sess.item_claims or [])
                         if isinstance(entry, dict) and entry.get("message_id") != message_id]
        source_action = None
        source_id = report.get("source_user_id")
        if isinstance(source_id, int):
            source = await store.get(RpgMessage, source_id)
            if source is not None and source.session_id == session_id and source.role == "user":
                source_action = source.content
        current = capture(sess)
        prior = copy.deepcopy(report)
        previous = report.get("after") or report["baseline"]
        base, protected = rebase_state(report["baseline"], previous, current)
        protected = list(dict.fromkeys([*(tuple(path) for path in report.get("protected_paths", [])), *protected]))
        preserve_edits(base, current, protected)
        if base["location"] != report["baseline"]["location"]:
            raise SettlementConflict("你已在这段剧情后移动到别处，请先读档或回滚到这一回合再结算")
        report.update({"status": "running", "revision": revision, "attempt_id": attempt,
                       "started_at": datetime.utcnow().isoformat(), "attempts": report.get("attempts", 0) + 1,
                       "retryable": True, "warnings": [], "outcome_label": label})
        if source_action:
            report["source_action"] = source_action
        report["protected_paths"] = [list(path) for path in protected]
        row.settlement = report
        await store.commit()
        expected_stamp = sess.updated_at
        working = _working(sess, base)
        evaluation = {**report, "narration": narration, "working_before": copy.deepcopy(base), "live_state": current}
        if source_action:
            evaluation["source_action"] = source_action
        clock = (sess.day, sess.slot, sess.turn_count, sess.time_slots)
        player_name = sess.char_name

    input_tokens = output_tokens = 0
    try:
        prompt = _prompt(module, working, npcs, places, narration, label, report, place_block)
        model, api_format = llm_client.get_agent_client("memory", module.fast_model_ref)
        data, used_in, used_out = await json_call([{"role": "user", "content": prompt}], model, api_format, max_tokens=4096)
        input_tokens += used_in
        output_tokens += used_out
        if not isinstance(data, dict):
            raise ValueError("结算结果必须是 JSON 对象")
        data = normalize_proposal(copy.deepcopy(data))
        issues, soft, events = inspect_proposal(data, narration, npcs, places, evaluation, player_name)
        dry_domains, _, _, _ = apply_proposal(module, _working(working, base), data, npcs, places, evaluation, issues, soft, events,
                                              items, pending_claims, message_id)
        repairs = {domain: info["warnings"] for domain, info in dry_domains.items() if info["status"] == "needs_review"}
        repair_warning = ""
        if repairs:
            try:
                repaired, used_in, used_out = await json_call([
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
                    {"role": "user", "content": "仅修复以下未通过的项目，并输出完整 JSON。已正确的变化保持原样；"
                     "不要累加刚才的输出。核对依据只能来自正文：\n" + json.dumps(repairs, ensure_ascii=False)},
                ], model, api_format, max_tokens=4096)
                input_tokens += used_in
                output_tokens += used_out
                if isinstance(repaired, dict):
                    for domain in repairs:
                        for key in DOMAINS[domain]:
                            data.pop(key, None)
                            if key in repaired:
                                data[key] = repaired[key]
                        checks = dict(data.get("checks") or {}) if isinstance(data.get("checks"), dict) else {}
                        checks[domain] = (repaired.get("checks") or {}).get(domain) if isinstance(repaired.get("checks"), dict) else None
                        data["checks"] = checks
                    # events 同样不属于任何 domain，上面那圈也搬不到它——而取证门禁
                    # 要的正是它。少了这一段，repair 补上一笔数值却带不进对应的那句
                    # 原文，第二次 inspect 就以「状态变化缺少关联的原文依据」再打回
                    # 一次，于是**这一轮 repair 结构上修不好任何需要新依据的项**。
                    # 只并进和被修的那几个域相关的条目：别让 repair 轮顺手给没被问到
                    # 的域补依据，那等于绕过第一轮的判定
                    fixed_events = repaired.get("events")
                    if isinstance(fixed_events, list):
                        seen = data.get("events") if isinstance(data.get("events"), list) else []
                        data["events"] = seen + [
                            event for event in fixed_events
                            if isinstance(event, dict) and event not in seen
                            and set(event.get("domains") or []) & set(repairs)
                        ]
                    # discoveries 不属于任何 domain，上面那圈搬不到它。但修复那一轮是
                    # 完整重出一份 JSON，它常会补上第一轮漏掉的人和地方——合过来而不是
                    # 覆盖，两轮各报了一半时才不会丢。重复的名字由 filter_discoveries 去重
                    fixed = repaired.get("discoveries")
                    if isinstance(fixed, dict):
                        merged = dict(data.get("discoveries") or {}) if isinstance(data.get("discoveries"), dict) else {}
                        for bucket, _ in DISCOVERY_KINDS:
                            extra = fixed.get(bucket)
                            if isinstance(extra, list):
                                seen = merged.get(bucket) if isinstance(merged.get(bucket), list) else []
                                merged[bucket] = seen + [item for item in extra if item not in seen]
                        data["discoveries"] = merged
                    data = normalize_proposal(data)
            except Exception as error:
                input_tokens += getattr(error, "input_tokens", 0)
                output_tokens += getattr(error, "output_tokens", 0)
                repair_warning = f"补充核对失败：{error}"
        if prior.get("applied_revision") == revision and isinstance(prior.get("proposed"), dict):
            retained = set()
            for domain, info in (prior.get("domains") or {}).items():
                if domain not in DOMAINS or domain == "memory" or info.get("status") not in {"updated", "unchanged"}:
                    continue
                retained.add(domain)
                for key in DOMAINS[domain]:
                    data.pop(key, None)
                    if key in prior["proposed"]:
                        data[key] = copy.deepcopy(prior["proposed"][key])
                checks = dict(data.get("checks") or {}) if isinstance(data.get("checks"), dict) else {}
                checks[domain] = (prior["proposed"].get("checks") or {}).get(domain)
                data["checks"] = checks
            old_events, _ = _evidence_events(prior["proposed"], narration, npcs, report)
            preserved = [event for event in old_events if isinstance(event, dict)
                         and set(event.get("domains") or []).issubset(retained)]
            new_events = data.get("events") if isinstance(data.get("events"), list) else []
            data["events"] = preserved + [event for event in new_events if isinstance(event, dict)
                                         and not (set(event.get("domains") or []) & retained) and event not in preserved]
        issues, soft, events = inspect_proposal(data, narration, npcs, places, evaluation, player_name)
        working = _working(working, base)
        evaluation["working_before"] = copy.deepcopy(base)
        domains, facts, here, item_claims = apply_proposal(module, working, data, npcs, places, evaluation, issues, soft, events,
                                                          items, pending_claims, message_id)
        # repair 那一轮也没给出代价。引擎自己立一条处境标记，**不去猜该扣哪一项
        # 数值**——猜错一个数比不给更糟，而且这里没有任何依据能选中某一项。
        #
        # 写在 apply_proposal 之后、走 working 而不是往 data 里塞一笔，照的是
        # check_zero 的先例：data 里的每一笔都要过「状态变化缺少关联的原文依据」
        # 那道取证门禁，而引擎记的账依据是骰子，不是正文，塞进去只会被自己的
        # 门禁打回来。stats/flags 两域此时是 needs_review（没应用过任何东西），
        # 所以这一笔不会被回滚覆盖
        if _costless_failure(data, evaluation):
            domains["flags"]["warnings"].extend([
                *apply_flags(working, {FAIL_FLAG: True}),
                f"判定结果是「{label}」而结算没给出代价，已代记一条「{FAIL_FLAG}」",
            ])
        after = capture(working)
        preserve_edits(after, current, protected)
        warnings = [warning for info in domains.values() for warning in info["warnings"]]
        if protected:
            warnings.append("已保留此回合后人工修改的状态字段")
        if repair_warning:
            warnings.append(repair_warning)
        if data.get("outcome_consistent") is False:
            # 正文已经吐完了，改不了；能保证的是**账按判定结果记**（上面那道
            # 门禁），所以这句话要说的是「别信这段字，信数值」，而不是从前那句
            # 含糊的「好像没照判定结果写」——玩家读完只会一头雾水
            warnings.append(f"这段剧情没写出「{label}」该有的样子，数值按判定结果记")
        applied, changes = state_changes(report.get("engine_before") or base, after)
        report.update({
            "status": "partial" if any(info["status"] in {"partial", "needs_review"} for info in domains.values()) else "done",
            "domains": domains, "proposed": data, "applied": applied, "changes": changes,
            "warnings": list(dict.fromkeys(warnings)), "facts": facts, "after": after,
            "applied_revision": revision,
        })
        report["retryable"] = report["status"] != "done"
        async with session_factory() as store:
            fresh = await store.get(RpgSession, session_id)
            fresh_row = await store.get(RpgMessage, message_id)
            if fresh is None or fresh_row is None or fresh_row.content != narration or (fresh_row.settlement or {}).get("attempt_id") != attempt:
                raise SettlementConflict("结算期间剧情已修改或回滚，结果未应用")
            if fresh.updated_at != expected_stamp or capture(fresh) != current:
                raise SettlementConflict("结算期间游戏状态发生变化，结果未应用，请重试")
            await _claim(store, fresh)
            await _require_latest(store, fresh_row)
            for field, value in after.items():
                setattr(fresh, field, value)
            # 待确认的新道具：重算先清掉自己这一条剧情上一轮记的再追加。
            # 不进 after / report——它不是游戏状态，是「模型说你拿到了，你认不认」。
            # **排在发现项之前**，因为下面要拿这份名单给发现项去重
            kept_claims = [entry for entry in (fresh.item_claims or [])
                           if not (isinstance(entry, dict) and entry.get("message_id") == message_id)]
            fresh.item_claims = kept_claims + item_claims
            # 同一条剧情重算时先把上一轮为它记的发现清掉再追加，否则重结算一次多一份。
            # 发现项不进 report、也不进 after：它不是游戏状态，是给作者的待办。
            # 算在这里而不是 apply_proposal 里面，因为那个函数会被上面的 dry-run 跑第二遍
            kept = [entry for entry in (fresh.discoveries or [])
                    if not (isinstance(entry, dict) and entry.get("message_id") == message_id)]
            # 已经会的招和已经接下的事读 fresh 而不是 working：它俩不在 STATE_FIELDS 里，
            # working 上那份是 _working 复制过去给模板看的，写入点始终是会话本身
            owned = [*(fresh.skills or []), *(fresh.tasks or [])]
            discoveries = filter_discoveries(data, narration, npcs, places, working.inventory,
                                             items, message_id, kept, skills, tasks, owned,
                                             fresh.item_claims)
            fresh.discoveries = kept + discoveries
            # 待办收线的提议，同上：重算先清掉自己这一条剧情上一轮记的。
            # 它只是提议，任务的 status 一个字都不动——那要玩家点头
            kept_tasks = [entry for entry in (fresh.task_proposals or [])
                          if not (isinstance(entry, dict) and entry.get("message_id") == message_id)]
            task_proposals = filter_task_updates(
                data, narration, open_task_names(fresh), message_id, kept_tasks
            )
            fresh.task_proposals = kept_tasks + task_proposals
            if prior.get("after") and prior.get("after") != after:
                invalidate_summaries(fresh)
            fresh_row.settlement = report
            fresh_row.state_delta = {field: value["after"] for field, value in applied.items()}
            suggestions = data.get("suggestions")
            fresh_row.suggestions = [value.strip()[:100] for value in suggestions if isinstance(value, str) and value.strip()][:3] if isinstance(suggestions, list) else []
            fresh_row.aux_input_tokens = (fresh_row.aux_input_tokens or 0) + input_tokens
            fresh_row.aux_output_tokens = (fresh_row.aux_output_tokens or 0) + output_tokens
            await store.commit()
            state = {**capture(fresh), "day": clock[0], "slot": clock[1], "time_slots": clock[3],
                     "npc_activities": fresh.npc_activities or {}}
            suggestions = fresh_row.suggestions
        return {"state": state, "warnings": report["warnings"], "suggestions": suggestions,
                "outcome_consistent": data.get("outcome_consistent"), "aux_input_tokens": input_tokens,
                "aux_output_tokens": output_tokens, "settlement": public_report(report),
                "discoveries": discoveries, "task_proposals": task_proposals,
                # 这一轮新挂上的待确认道具。前端拿它刷道具格的角标和「新获取」
                "item_claims": item_claims,
                # 纯建议，一个状态字段都不动（同 outcome_consistent）。只有 true
                # 才算提议：缺、null、false 一律当「没意见」
                "scene_wrapped": data.get("scene_wrapped") is True}
    except Exception as error:
        async with session_factory() as store:
            row = await store.get(RpgMessage, message_id)
            if row and (row.settlement or {}).get("attempt_id") == attempt and row.content == narration:
                failed = {**prior, "status": "failed", "revision": revision, "retryable": True,
                          "attempt_id": attempt, "attempts": report["attempts"], "warnings": [str(error)]}
                failed["after"] = prior.get("after") or current
                failed["domains"] = prior.get("domains") or {domain: {"status": "failed", "warnings": [str(error)]} for domain in DOMAINS}
                failed["facts"] = prior.get("facts") or []
                row.settlement = failed
                row.aux_input_tokens = (row.aux_input_tokens or 0) + input_tokens + getattr(error, "input_tokens", 0)
                row.aux_output_tokens = (row.aux_output_tokens or 0) + output_tokens + getattr(error, "output_tokens", 0)
                await store.commit()
        raise
