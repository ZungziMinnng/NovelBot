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
from app.services.rpg_state import RANK_GAIN_MAX, apply_flags, apply_state_delta, check_condition, check_full, check_zero, def_map, mark_met, match_npc, norm_name, open_task_names, push_chronicle, rank_stat_of
from app.services.rpg_suggestions import SuggestSources, clean_suggestions

logger = logging.getLogger(__name__)


STATE_FIELDS = (
    "stats", "inventory", "flags", "location", "npc_states", "npc_notes",
    # 这一局被改写掉的外貌。和 npc_notes 同进同出：两者都是模型从正文里读出来、
    # 写进会话语境、下一轮原样注入那个人的卡的东西，回滚时漏一个就留下一处
    # 改不回来的身体
    "npc_appearance",
    "npc_places", "place_notes", "status", "visited", "chronicle",
    # 只追加的两条长期记忆（见 models.RpgSession.npc_history / npc_milestones）。
    # **必须进这张表**：capture() 出来的这一份是异常回滚和存档快照唯一的来源，
    # 漏在外面的话写进去的经历回滚不掉，而且不报错
    "npc_history", "npc_milestones",
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
    # 经历和里程碑挂在人物这一域：写它们的是同一段正文、同一次判定
    "characters": ("relations", "npc_notes", "npc_appearance", "npc_history", "npc_milestones"),
    "flags": ("flags",),
    "memory": ("events", "chronicle"),
}
LABELS = {"scene": "地点与在场人物", "stats": "数值", "inventory": "背包", "characters": "人物", "flags": "处境", "memory": "长期记忆"}
DOMAIN_FIELDS = {
    "scene": ("location", "npc_places", "place_notes", "visited"),
    "stats": ("stats", "status"), "inventory": ("inventory",),
    # flag_days 跟着 flags 一起回滚：处境这一域被判为需要人工核对时，
    # 只退 flags 会留下一个指向不存在 flag 的日期
    # 经历和里程碑跟着人物域一起回滚：这一域被判为需要人工核对时它们一起退，
    # 否则「人物这一块要人工核对」而流水里已经多了一条谁也删不掉的经历
    "characters": ("npc_states", "npc_notes", "npc_appearance", "npc_history", "npc_milestones"),
    "flags": ("flags", "flag_days"),
    "memory": ("chronicle",),
}
PUBLIC_KEYS = ("status", "revision", "attempts", "domains", "changes", "warnings", "facts", "engine_facts", "applied", "proposed", "retryable")
EVENT_KINDS = {"state", "move", "gain", "loss", "transfer", "injury", "recovery", "relationship", "promise", "rescue", "death", "public"}
# 只追加、从不覆盖的两个键。单列出来是因为它们**不算「状态变化」**：
# 记一句「她今天经历了什么」不该被要求同时配一条 events（见 inspect_proposal
# 里那道取证门禁为什么跳过它们）。代价是它们自带一道更严的闸门——文本必须能
# 在正文里找到原话（见 _grounded）
APPEND_ONLY_KEYS = ("npc_history", "npc_milestones")

# 关系里程碑的七种类型，逐字沿用小说侧 Memory(memory_type=
# "relationship_milestone") 那一套：两个模式里的关系转折是同一批事，
# 类型名各写一套只会让「动心」和「心动」分家
_MILESTONE_TYPES = ("初见", "动心", "表白", "决裂", "和解", "身份揭露", "其他")
# 每回合最多几条。小说侧是每章 3 条（_MAX_MILESTONES_PER_CHAPTER），而游戏侧
# 一回合比一章细得多——一章的量里有七八个回合，还按 3 条算的话一局下来会糊成
# 一片，那正是里程碑要避免的
_MAX_MILESTONES_PER_TURN = 2
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
同场 NPC 改到别处（包括清空位置恢复作息）必须有该 NPC 实际离场的 move 事件，participants 包含该 NPC 的 id，quote 引用其离场过程。玩家的移动事件不能作为 NPC 离场的依据。
反过来也一样：角色表里写着在别处的 NPC 要改到玩家所在地，必须有该 NPC 赶来的 move 事件。玩家自己走到某地不等于那里的人来了，也不等于原本在别处的人出现在那里。
人物坐在房间、站在门边等场景描写不是移动。主角地点由引擎锁定时，不得仅因正文换用了偏殿、后院等地名，就把仍与主角交谈的 NPC 单独移走。
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


def _grounded(entry: dict, narration: str) -> bool:
    """这一条经历 / 里程碑在正文里有没有依据。

    先认模型另给的 quote（正文原话，同 discoveries 的 hint、task_updates 的
    reason）：经历那一句是**概括**——「她把伞留在了门口」在正文里逐字找不到，
    拿它去查会把每一条都误杀。没给 quote 才退回查 content 本身，那时只认正文
    里真出现过的字。

    两条路都走不通就判假：宁可少记一条，也不能记一条没发生过的事——
    里程碑会常驻注入，一条编出来的「表白」会一直杵在上下文里骗后面每一轮。
    """
    quote = str(entry.get("quote") or "").strip()[:200]
    if quote and _quote_in_narration(quote, narration):
        return True
    content = str(entry.get("content") or "").strip()
    return bool(content) and _mentioned_text(content, narration)


def _long_term_text(value, narration) -> str:
    """把一条经历归一成一句能落库的话。空串 = 这一条不要。

    收两种写法：一句人话，或 {"content": ..., "quote": ...}——模板里教的是后者，
    但模型给前者时不该整条丢掉，只要站得住就行。给了多条时只取头一条：每回合
    每人最多一条（游戏侧一回合比小说一章细得多，见 models.npc_history）。

    quote 只用来验真、**不落库**：落库的是那句概括，而「这概括是从这句原文来的」
    只在这一刻有意义，存下来下一轮也没人会再去比对。
    """
    if isinstance(value, list):
        value = value[0] if value else ""
    entry = value if isinstance(value, dict) else {"content": value}
    content = " ".join(str(entry.get("content") or "").split())[:200]
    if not content or not _grounded(entry, narration):
        return ""
    return content


def _filter_milestones(raw, narration, npcs, allowed) -> tuple[list[dict], list[str]]:
    """从结算 JSON 的 npc_milestones 里挑出这一轮真发生了的关系转折。
    返回 (留下的, 要往外报的原因)。

    三道关，全照 filter_discoveries / filter_task_updates 的路子——模型报什么
    一律本地复核：
      1. type 必须在那七个里。自造的静默丢掉，同 task_updates 丢掉 done/failed
         之外的 action
      2. a / b 两侧都得站得住。对不上名册的那一侧只认「你 / 玩家 / 我」（模板里
         教的就是这么写），对得上的必须**这一轮真的参与了**（allowed）——
         把两个不相干的人焊在一起不是转折，是幻觉
      3. content 必须能在正文里找到依据。**这一条要往外报**：它会常驻注入，
         静默丢掉的话「模型压根没写」和「写了但站不住」在外面看起来一模一样
    """
    if not isinstance(raw, list):
        return [], []
    kept: list[dict] = []
    dropped: list[str] = []
    for entry in raw:
        if len(kept) >= _MAX_MILESTONES_PER_TURN:
            break
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("type") or "").strip()
        if kind not in _MILESTONE_TYPES:
            continue
        a = str(entry.get("a") or "").strip()[:50]
        b = str(entry.get("b") or "").strip()[:50]
        if not a or not b:
            continue
        sides = [_npc_ref(name, npcs) for name in (a, b)]
        # 认出来的那几个必须参与了本轮；没认出来的那一侧只能是玩家自己
        if any(npc is not None and npc.id not in allowed for npc in sides):
            continue
        if not any(sides):
            continue
        if any(npc is None for npc in sides) and not ({a, b} & {"你", "玩家", "我"}):
            continue
        content = " ".join(str(entry.get("content") or "").split())[:200]
        if not content:
            continue
        if not _grounded(entry, narration):
            dropped.append(f"关系里程碑「{kind} {a}↔{b}」在正文里找不到依据，已丢弃")
            continue
        # 认出来的那一侧存**名册上的名字**，不存模型当时的写法。模型这一轮叫
        # 「赫敏姑娘」下一轮叫「赫敏」，原样存下来注入时是两个人，档案页也
        # 按名字挑不出「跟她有关的那几条」
        kept.append({
            "type": kind,
            "a": sides[0].name if sides[0] else a,
            "b": sides[1].name if sides[1] else b,
            "content": content,
        })
    return kept, dropped


def seed_settlement(sess, user_id, engine_before, engine_note, fixed_location, mode, private_with, present) -> dict:
    return {
        "status": "pending", "baseline": capture(sess), "engine_before": engine_before,
        "engine_note": engine_note, "fixed_location": fixed_location, "source_user_id": user_id,
        "mode": mode, "private_with": private_with, "origin_present": list(present or []),
        "clock": [sess.day, sess.slot, sess.turn_count], "attempts": 0, "retryable": True,
    }


def _npc_state_deltas(before: dict, after: dict, npc_names: dict | None) -> list[str]:
    """逐项列出这一轮变了几点关系数值。

    npc_names 是 {npc id 的字符串形式: 名字}。查不到名字的那个人整条跳过——
    这一行是拿给玩家看的，`npc:7 好感 +3` 不如不写；跳过之后那一笔会落回
    下面那句笼统标签。
    """
    if not npc_names:
        return []
    old = before.get("npc_states") or {}
    new = after.get("npc_states") or {}
    lines = []
    for identity in sorted(set(old) | set(new)):
        who = npc_names.get(str(identity))
        if not who:
            continue
        previous, current = old.get(identity), new.get(identity)
        if not isinstance(previous, dict) or not isinstance(current, dict):
            continue
        for stat in sorted(set(previous) | set(current)):
            a, b = previous.get(stat), current.get(stat)
            # met 是 bool，而 isinstance(True, int) 为真——不显式挡一道，
            # 这条相识标记会报成「+1」
            if isinstance(a, bool) or isinstance(b, bool):
                continue
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a != b:
                lines.append(f"{who}的{stat} {b - a:+g}")
    return lines


def state_changes(before: dict, after: dict, npc_names: dict | None = None) -> tuple[dict, list[str]]:
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
    listed = _npc_state_deltas(before, after, npc_names)
    for field, label in (("npc_notes", "人物近况已更新"), ("npc_appearance", "人物外貌已改写"),
                         ("npc_states", "人物关系或相识记录已更新"),
                         ("npc_places", "人物位置已更新"), ("place_notes", "地点近况已更新"), ("flags", "处境已更新")):
        if field not in applied:
            continue
        if field == "npc_states":
            # 逐项列过了就不再打一遍笼统标签，否则同一笔关系报两遍。
            # 一行都没列出来（比如只有 met 变了）才落回它
            lines.extend(listed or [label])
            continue
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
        for clause in re.split(r"[，,；;]", sentence):
            if re.match(subject + r"(?:终于|已经|径直|便|就|缓缓|悄悄|顺利|也|们|都|一行人)*.{0,12}(?:来到|抵达|到达|走进|进入|前往|奔向|赶往|返回|回到)", clause.strip()):
                targets = [place.name for place in places if place.name and _mentioned_text(place.name, clause)]
                if targets:
                    suspects.append(("scene", sentence, max(targets, key=len)))
        # 只加确实指向「东西易手」的词。命中之后是**软**提示（见 inspect_proposal
        # 里「疑似漏记关键事件」那两条），但提示会原样挂在报告上给玩家看，
        # 所以还是宁可漏抓也别错抓：「她递给你一个眼神」这种要是算进来，
        # 每一轮闲聊的提醒里都会挂一条假警报
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
            # npc_milestones 是跨两个人的一张表、不挂在谁名下，形状同 inventory；
            # 别的键（含 npc_history）都是「按角色名写的一张字典」
            expected = list if key in {"inventory", "events", "chronicle", "npc_milestones"} else str if key == "location" else dict
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
        # 经历和里程碑不参与这道门禁：它们自己带原话校验（_grounded），
        # 不需要再配一条 event。否则模型想记一句「她今天终于肯抬头看你」，
        # 就得顺手编一个事件出来交差——那正是这道闸门要防的事
        if domain == "memory" or not any(data.get(key) for key in keys if key not in APPEND_ONLY_KEYS):
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
            if domain != "memory" and not any(data.get(key) for key in DOMAINS[domain]
                                              if key not in APPEND_ONLY_KEYS):
                if domain == "scene" and report.get("fixed_location") is not None:
                    continue
                issues[domain].append(f"事件尚未回填：{event['quote'][:60]}")
        if event["kind"] == "transfer":
            for domain in ("inventory", "characters"):
                if not any(data.get(key) for key in DOMAINS[domain] if key not in APPEND_ONLY_KEYS):
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
            # 只挂提醒、不压 status：判据是**本地正则猜的**，不是模型自己报的。
            # 一句「你接过了话头」就够命中上面那张易手词表，而把一个域打回去
            # 的代价和「疑似」两个字的把握完全不相称
            soft[domain].append(f"疑似漏记关键事件：{quote[:80]}")
        if domain == "inventory" and re.search(r"交给|递给|送给", quote) and any(npc.name and npc.name in quote for npc in npcs):
            if not any(event["kind"] == "transfer" and (event["quote"] in quote or quote in event["quote"]) for event in events):
                issues["inventory"].append("物品交接需要同时核对背包与接收人的持有状态")
                issues["characters"].append("物品交接需要同时核对背包与接收人的持有状态")
        if not any(event["quote"] in quote or quote in event["quote"] for event in events):
            # 同上。挂在 memory 上还是全套里**最贵的那一档**：apply_proposal 末尾
            # 那句 `if reports["memory"]["status"] == "needs_review": facts = []`
            # 会把这一轮已经逐字取证过的事实整份清掉，大事记也跟着不写
            soft["memory"].append(f"关键事件缺少原文记录：{quote[:80]}")
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
    claimed = set((report.get("engine_effects") or {}).get("stats") or [])
    for field in ("stats",):
        changes = delta.get(field)
        if isinstance(changes, dict):
            delta[field] = {key: value for key, value in changes.items()
                            if str(key).strip() not in claimed
                            and (before.get(field) or {}).get(key) == (after.get(field) or {}).get(key)}
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


def _scene_protection_overlaps(report, delta, mapped):
    proposals = {
        "location": delta.get("location"),
        "visited": delta.get("location"),
        "npc_places": mapped.get("npc_places"),
        "place_notes": delta.get("place_notes"),
    }
    for path in report.get("protected_paths", []):
        if not path:
            continue
        proposed = proposals.get(path[0])
        if not proposed:
            continue
        if len(path) == 1 or not isinstance(proposed, dict) or path[1] in proposed:
            return True
    return False


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
    # 判定失败又没人付账的那一轮，经历和里程碑都不记。理由同 _costless_failure
    # 上面那段注释：「她皱了下眉」是文字，不是状态变化。把它记成一条经历等于
    # 每失手一次就在长期记忆里划一道痕，而那一轮其实什么都没发生；里程碑更重——
    # 它常驻注入，等于把一次没成的事永久钉进两个人的关系史
    quiet = _costless_failure(data, report)
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
    for key, domain in (("relations", "characters"), ("npc_notes", "characters"),
                        ("npc_appearance", "characters"),
                        ("npc_history", "characters"), ("npc_places", "scene")):
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
                fixed = report.get("fixed_location")
                if fixed:
                    current_place = npc_place(npc, working.slot, working.npc_places,
                                              working.npc_followers, working.location)
                    proposed_places = dict(working.npc_places or {})
                    if value:
                        proposed_places[str(npc.id)] = value
                    else:
                        proposed_places.pop(str(npc.id), None)
                    next_place = npc_place(npc, working.slot, proposed_places,
                                           working.npc_followers, working.location)
                    moved = any(event["kind"] == "move" and npc.id in event["participants"]
                                for event in events)
                    if (norm_name(current_place) == norm_name(fixed)
                            and norm_name(next_place) != norm_name(fixed) and not moved):
                        issues[domain].append(f"「{npc.name}」仍与玩家同场，缺少该角色实际离场的原文依据，未将其移到别处")
                        continue
                    # 反方向同一道门：**别处的人不许凭空出现在玩家跟前**。
                    # 上面那半只挡「同场的人被挪走」，于是调度到菜市场的人被写
                    # 成从玩家家的厨房出来时一路放行——她的名字因此出现在正文里，
                    # allowed = original | named 把这一句认成「剧情真的动了这个人」，
                    # 位置改成家。玩家看到的是她从菜市场瞬移回来，两张表都不报错。
                    #
                    # 走过来当然可以，但得有原文依据（她推门进来那一句）。
                    #
                    # **这个方向上不能只看有没有 move 事件**：事件的 quote 只被
                    # 校验过「逐字出自正文」，没人校验过那句话真的写了她过来。
                    # 真实存档里模型交上来的就是一条 kind=move、quote 是
                    # 「韩曼宁侧躺在床上，蜷着身子」的事件，summary 自己写着
                    # 「已从菜市场回到家中卧室」——正文里她根本没走这一趟，
                    # 是模型先当她在家写完了，再回头补一张过路条。
                    # 所以这半边要求 quote 里有「来 / 进 / 回」这类动作词
                    came = any(
                        event["kind"] == "move" and npc.id in event["participants"]
                        and re.search(r"来|进|回|到|赶|返|现身|出现|推门|敲门", event["quote"])
                        for event in events
                    )
                    if (norm_name(current_place) != norm_name(fixed)
                            and norm_name(next_place) == norm_name(fixed) and not came):
                        issues[domain].append(
                            f"「{npc.name}」原本在「{current_place}」，缺少该角色赶来的原文依据，未将其移到玩家跟前"
                        )
                        continue
            if key in {"relations", "npc_notes", "npc_appearance"} and value is not None and not isinstance(value, dict):
                issues[domain].append(f"人物「{npc.name}」的变化格式错误")
                continue
            if key in {"npc_notes", "npc_appearance"} and isinstance(value, dict) and any(entry is not None and not isinstance(entry, str) for entry in value.values()):
                label = "近况" if key == "npc_notes" else "外貌变化"
                issues[domain].append(f"人物「{npc.name}」的{label}必须是文字或 null")
                continue
            if key == "npc_notes":
                existing = (working.npc_notes or {}).get(str(npc.id)) or {}
                merged = {**existing, **(value or {})} if value is not None else {}
                conflict = fact_guard.check_life_death(existing, merged)
                if conflict:
                    issues[domain].append(f"{npc.name}：{conflict['reason']}")
                    continue
            if key == "npc_history":
                # 一句话，只追加不覆盖（见 models.RpgSession.npc_history）。
                # 写了东西却找不到正文依据的**整条丢并记一笔**：静默丢弃的话，
                # 「模型压根没写」和「写了但站不住」在外面长得一模一样，
                # 没法判断该调模板还是调这里
                line = "" if quiet else _long_term_text(value, report["narration"])
                if not line:
                    if not quiet and value:
                        issues[domain].append(
                            f"「{npc.name}」这一轮的经历在正文里找不到依据，已丢弃"
                            "（quote 必须逐字摘自正文）")
                    continue
                value = line
            if key == "relations":
                if not isinstance(value, dict) or any(isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) for amount in value.values()):
                    issues[domain].append(f"人物「{npc.name}」的关系增减量不是有效数字")
                    continue
                engine_before = (report.get("engine_before") or {}).get("npc_states") or {}
                engine_after = report["baseline"].get("npc_states") or {}
                claimed = set(((report.get("engine_effects") or {}).get("relations") or {}).get(str(npc.id)) or [])
                value = {stat: amount for stat, amount in value.items()
                         if str(stat).strip() not in claimed
                         and (engine_before.get(str(npc.id)) or {}).get(stat) == (engine_after.get(str(npc.id)) or {}).get(stat)}
            mapped[key][str(npc.id)] = value
    # 里程碑跨两个人、不挂在谁名下，所以不塞进上面那圈按 npc_ref 归一的循环。
    # mapped 里仍要占个空位：下面 portion 靠 `key not in mapped` 把它挡在
    # apply_state_delta 之外——那一层认的是会被覆盖的状态，不认只追加的流水
    mapped["npc_milestones"] = {}
    milestones, milestone_drops = ([], []) if quiet else _filter_milestones(
        delta.get("npc_milestones"), report["narration"], available, allowed,
    )
    for reason in milestone_drops:
        issues["characters"].append(reason)
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
        if domain == "scene" and not _scene_protection_overlaps(report, delta, mapped):
            continue
        for field in DOMAIN_FIELDS[domain]:
            value = copy.deepcopy(report["live_state"][field])
            setattr(working, field, value)
            report["working_before"][field] = copy.deepcopy(value)
        issues[domain].append("这一项在本回合后发生变化，已保留当前值，需要核对")
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
                        if key == "npc_history":
                            # 不走 apply_state_delta：那一层认的是数值 / 近况 /
                            # 位置这些**会被覆盖**的东西，而经历是只追加的流水。
                            # 时间戳由引擎盖，不信模型自己填的 day/slot——
                            # 它连「现在几点」都不一定看得对
                            stored = list((working.npc_history or {}).get(str(npc.id)) or [])
                            stored.append({"day": max(1, int(getattr(working, "day", 1) or 1)),
                                           "slot": str(getattr(working, "slot", "") or ""),
                                           "content": value})
                            working.npc_history = {**(working.npc_history or {}), str(npc.id): stored}
                            continue
                        warnings.extend(apply_state_delta(module, working, {key: {npc.name: value}}, [npc],
                                                          note_npcs=[npc], move_npcs=[npc], places=list(known_places), finalize=False))
                # 里程碑同样只追加，但它不挂在某个人名下，所以走不了上面那套
                # mapped。只在人物这一域做一次：别的域轮到这里时它是空的
                if domain == "characters" and milestones:
                    working.npc_milestones = [
                        *(working.npc_milestones or []),
                        *({"day": max(1, int(getattr(working, "day", 1) or 1)),
                           "slot": str(getattr(working, "slot", "") or ""),
                           **entry} for entry in milestones),
                    ]
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
    # 也就不会被结算结果覆写回去——任务状态只认玩家点头。
    # npc_followers 同理：它只在 npc_place 里定「跟着你的人此刻在哪儿」，
    # 结算一个字都不该写它（改它是引擎那侧的事），漏了它提示词就直接炸
    return SimpleNamespace(**copy.deepcopy(state), day=sess.day, slot=sess.slot,
                           time_slots=sess.time_slots, turn_count=sess.turn_count,
                           tasks=copy.deepcopy(sess.tasks or []),
                           npc_followers=sess.npc_followers or [])


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


def _with_cap(specs: dict, name: str, value):
    """数值带上分母：有上限的写成 "20/100"，没上限的保持原数字。

    只给当前值的话，模型无从判断「她已经 90 了」还是「刚认识」，只能闭着眼给
    增量，于是好感一路顶到上限。分母只认定义里真写了的 max——钱、声望没有，
    拼成 "/None" 只会让模型以为有一道看不见的天花板。
    """
    top = (specs.get(name) or {}).get("max")
    return f"{value}/{top}" if top is not None else value


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
    # 等级那一项有一道作者没填过的隐式上限（cap_rank_gain）。不告诉模型的话，
    # 它每轮提 +3，每轮换回来一条「境界这一轮只升了 1」的噪音。作者自己填了
    # step_max 时上面那行已经写进去了，这里不覆盖
    rank = rank_stat_of(module)
    if rank and rank in stat_specs and rank not in step_caps:
        step_caps[rank] = RANK_GAIN_MAX
    # 两张表合一份，同 step_caps。只收作者真填了 effect 的项：没填的给个空行
    # 等于告诉模型「这一项没有意思」，不如不提
    stat_meanings = {
        name: " ".join(str(spec.get("effect") or "").split())
        for name, spec in {**stat_specs, **relation_specs}.items()
        if str(spec.get("effect") or "").strip()
    }
    prompt = render(
        # outcome_failed 是从 label 推出来的，不另传一个档位键：先跟模型把
        # 「失败要留代价」说在前面，比等它交了空 delta 再打回去便宜一整轮调用
        "rpg_settle.jinja2", narration=narration, outcome_label=label,
        outcome_failed=label in FAIL_LABELS,
        stats={name: _with_cap(stat_specs, name, value)
               for name, value in (sess.stats or {}).items()}, location=sess.location or "",
        place_note=(sess.place_notes or {}).get(sess.location, ""),
        inventory=sess.inventory or [], flags=sess.flags or {},
        # 关系值要带**当前数字**，不能只给名字：不给的话模型无从判断「她已经
        # 90 了」还是「刚认识」，只能闭着眼给增量，于是好感一路涨到顶。
        # 只挑定义过的键，把 met 这类内部标记挡在外面
        npcs=[{
            "id": npc.id, "name": npc.name,
            "notes": (sess.npc_notes or {}).get(str(npc.id), {}),
            # 已经改写过的外貌。不给的话模型看不到自己上一轮写了什么，会把
            # 「她长出了乳房」这一件事每轮重写一遍——同一条变化在表里只有一份
            # （同键覆盖），重复写除了浪费 token 没别的后果，但它的 quote 可能是
            # 上一轮的正文，那一轮不在这次 narration 里，取证会直接挂掉
            "appearance": (sess.npc_appearance or {}).get(str(npc.id), {}),
            "relations": {name: _with_cap(relation_specs, name, value)
                          for name, value in (states.get(str(npc.id)) or {}).items()
                          if name in relation_specs},
        } for npc in participants],
        note_keys=sorted({key for notes in (sess.npc_notes or {}).values() if isinstance(notes, dict) for key in notes}),
        relation_names=list(relation_specs), step_caps=step_caps,
        # 作者写的「这一项影响什么」。**不给的话模型只知道数值的名字**，于是它
        # 只会顺着字面意思单向加：羞耻值被读成「这一轮有没有发生羞耻的事」，
        # 于是次次 +2，从没有一轮让它跌——可作者写的是「撒谎、出轨、羞辱会让
        # 羞耻下降」，方向正好相反。叙事那一侧早就有这份说明（_meaning_block），
        # 记录员这一侧一直没有：它是唯一真正动数字的人
        stat_meanings=stat_meanings,
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
        {
            "id": npc.id, "name": npc.name,
            # 跟着你的人，位置就是他此刻站的地方——结算据此判断她有没有「换地方」
            "location": npc_place(
                npc, sess.slot, sess.npc_places, sess.npc_followers, sess.location,
            ),
        } for npc in participants
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
        model, api_format = llm_client.get_agent_client("memory", module.settlement_model_ref or module.fast_model_ref)
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
            warnings.append("已保留本回合之后更新的状态字段")
        if repair_warning:
            warnings.append(repair_warning)
        if data.get("outcome_consistent") is False:
            # 正文已经吐完了，改不了；能保证的是**账按判定结果记**（上面那道
            # 门禁），所以这句话要说的是「别信这段字，信数值」，而不是从前那句
            # 含糊的「好像没照判定结果写」——玩家读完只会一头雾水
            warnings.append(f"这段剧情没写出「{label}」该有的样子，数值按判定结果记")
        applied, changes = state_changes(report.get("engine_before") or base, after,
                                         npc_names={str(npc.id): npc.name for npc in npcs})
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
            # 建议条收口成和主动路同一份形状，白名单/降级都走 rpg_suggestions。
            # **时序是对的**：上面那圈 setattr 已经把 after 写回 fresh 了，
            # 所以「用止血草」依的是结算之后的背包，不是结算之前的
            #
            # 白名单比提示词宽：模板只教了 free / item（技能栏、地点表、动作表
            # 根本不在渲染参数里），但这里照样把技能和地点一起递进去。这个不对称
            # 是故意的——白名单是**为了点击一定能走通**而存在的，模型没被教过就
            # 不会写；哪天真写了，能被白名单认下来说明那条本来就成立。
            # 动作的 usable 留空：判据 `_action_gate` 在 rpg_turn 里，
            # import 它会成环，于是动作建议在这条路上必然降级成自由文本
            # （见 SuggestSources 的注释：这是安全的那一侧）
            fresh_row.suggestions = clean_suggestions(
                data.get("suggestions"),
                fresh,
                SuggestSources(
                    module=module, npcs=npcs, items=items, skills=skills, locations=places,
                ),
            )
            fresh_row.aux_input_tokens = (fresh_row.aux_input_tokens or 0) + input_tokens
            fresh_row.aux_output_tokens = (fresh_row.aux_output_tokens or 0) + output_tokens
            await store.commit()
            state = {**capture(fresh), "day": clock[0], "slot": clock[1], "time_slots": clock[3],
                     "npc_activities": fresh.npc_activities or {},
                     "npc_activity_log": fresh.npc_activity_log or {}}
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
