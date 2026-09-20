"""建议条的结构化收口。

两条路共用这一份：主动的「帮我想想」（`rpg_turn.suggest_actions`）和每轮结算
顺带产出的建议（`rpg_settlement.settle_turn`）。两边的**模型输出格式不同**——
主动路是一行一条、行首挂 `[技|名字]` 标签（便宜档小模型写字比写 JSON 稳），
被动路本来就是 JSON。但**收口成什么形状必须是同一份**，否则前端要认两套。

依赖方向：只 import models + `rpg_state`。**不 import `rpg_context` / `rpg_turn`**
（`rpg_turn` 反向依赖这里，会成环）。所以动作可用性（`_action_gate`）的过滤由
调用方做完再塞进 `SuggestSources.actions`——这也顺带保证可用性判据仍然只有
`agents/rpg_turn._action_gate` 那一份，不会在这里长出第二份。

**降级永远优先于丢弃**：模型给的名字对不上白名单时，整条降级成自由文本、
正文原样保留。玩家点了一条自由文本建议，等于自己打一句话发出去，GM 照样会写；
丢一条他则完全无从发现。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models.rpg import (
    RpgAction, RpgItem, RpgLocation, RpgModule, RpgNpc, RpgSession, RpgSkill, RpgWorldEntry,
)
from app.services.rpg_state import check_condition, effect_cost_reason, norm_name

# 一条建议的四种意图，外加自由文本。前端按 kind 决定点了走哪个入口
KINDS = ("free", "skill", "item", "move", "action")

# 行首标签：`[技|暗影步]`。半角竖线和全角竖线都收，模型两种都会写
_TAG_KIND = {"技": "skill", "物": "item", "去": "move", "行": "action"}
_TAG_RE = re.compile(r"^\s*\[([技物去行])\s*[|｜]\s*([^\]]*)\]\s*")

# 模型爱加的包装：行首项目符号 / 带分隔符的编号。编号必须带分隔符才剥，
# 否则「3天后再来看看」会被吃掉开头的数字
_LINE_NOISE = re.compile(r"^\s*(?:[-*•]\s*)?(?:\d+\s*[.、)）]\s*)?")
_QUOTES = "\"“”「」『』"

# 最多给几条。被动路（每轮结算顺带产出）就这一个总量上限
MAX_SUGGESTIONS = 3

# 主动路「帮我想想」的两个桶：能点的（技能/道具/前往/动作）3 条 + 纯对白 3 条。
# 两个桶各管各的名额，谁也挤不掉谁。被动路不经过这两个数
MAX_STRUCTURED = 3
MAX_FREE = 3

# 单条建议的正文上限。被动路原先就地写死过 `[:100]`——它落在 JSON 列里，
# 得有个闸；抬到这里是为了两条路同一个数，顺带管住主动路。建议本来就该在
# 20 字以内，正常输出碰不到这个上限
MAX_TEXT_CHARS = 100


@dataclass(frozen=True)
class SuggestSources:
    """这次建议能引用的东西。全部由调用方从库里查好递进来。

    `usable` 里已经是 `(动作, 可用对象名或空串)` 且**已经过 `_action_gate`**，
    这里不再复核——判据只该有一份。它和 `actions`（模组定义的全部动作）分开
    两个字段，是为了让「忘了过判据」的失败方向是**安全**的：`usable` 空 =
    动作全部降级成自由文本，而不是把作者没放的按钮全放进来。
    """

    module: RpgModule | None = None
    npcs: list[RpgNpc] = field(default_factory=list)
    items: list[RpgItem] = field(default_factory=list)
    skills: list[RpgSkill] = field(default_factory=list)
    locations: list[RpgLocation] = field(default_factory=list)
    # 模组定义的全部动作，原样。过完 _action_gate 的那份填进 usable
    actions: list[RpgAction] = field(default_factory=list)
    usable: list[tuple[RpgAction, str]] = field(default_factory=list)
    # 世界书。收口用不到它（它不参与白名单），但注入段要拼
    entries: list[RpgWorldEntry] = field(default_factory=list)


def _qty(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def allow_lists(sess: RpgSession, src: SuggestSources) -> dict[str, dict[str, str]]:
    """四张白名单：`{kind: {归一化名字: 清单里的原名}}`。

    存回去的必须是**原名**——模型抄成「止血草 」或大小写不同时，传给引擎的
    得是模组里写的那一份，否则 `_resolve_engine` 按 `norm_name` 查表虽然查得到，
    但冷却表 `set_cooldown` 是按名字写回 `sess.skills` 的，两边名字不一致会
    压不上冷却。

    每一条都对应一个真实的拦截点：
    - 技能 / 道具**两个源都要命中**。`sess.skills` / `sess.inventory` 里存的是
      剧情里学到的、捡到的名字，模组表里可能根本没有——那种点下去必然弹一句
      黄条（「模组里没有这个技能」）。只判一边不报错，所以最容易写漏
    - `usable` 为假：`_resolve_engine` 会回「并不是能用的东西」/「不是能主动
      施展的本事」，点了白点一次
    - 数量 0 / 冷却中：同样点了白点一次
    """
    defs = getattr(src.module, "stat_defs", None)
    module_items = {norm_name(item.name): item.name for item in src.items
                    if item.usable and not effect_cost_reason(sess, item.effects, defs)}
    module_skills = {norm_name(skill.name): skill.name for skill in src.skills
                     if skill.usable and skill.category != "被动"
                     and check_condition(skill.requires, sess, src.npcs)[0]
                     and not effect_cost_reason(sess, skill.effects, defs)}

    items: dict[str, str] = {}
    for row in sess.inventory or []:
        if not isinstance(row, dict):
            continue
        key = norm_name(str(row.get("name") or ""))
        if key and _qty(row.get("qty")) > 0 and key in module_items:
            items[key] = module_items[key]

    skills: dict[str, str] = {}
    for row in sess.skills or []:
        if not isinstance(row, dict):
            continue
        key = norm_name(str(row.get("name") or ""))
        if key and _qty(row.get("cooldown_left")) <= 1 and key in module_skills:
            skills[key] = module_skills[key]

    # 当前地点不算「能去的地方」：建议了它，`move_by_name` 只会说「你已经在 X 了」，
    # 而且 `_move` 会白记一条大事记
    here = norm_name(sess.location or "")
    places: dict[str, str] = {}
    for loc in src.locations:
        key = norm_name(loc.name)
        if not key or key == here:
            continue
        if not check_condition(loc.enter_requires, sess, src.npcs)[0]:
            continue
        places[key] = loc.name

    actions = {
        norm_name(a.name): a.name for a, _who in src.usable if norm_name(a.name)
    }
    return {"skill": skills, "item": items, "move": places, "action": actions}


def parse_tagged_lines(text: str) -> list[dict]:
    """把模型的分行输出解析成**未校验**的建议。

    顺序不能换：剥行首符号 → 剥引号 → 摘标签 → 正文再剥一次引号。
    先摘标签的话，`「[技|暗影步] 绕过去」` 这种整行带引号的写法会漏；
    摘完标签不补一次，`[技|暗影步]「绕过去」` 的正文会带着引号进引擎。
    """
    parsed: list[dict] = []
    for raw in (text or "").splitlines():
        line = _LINE_NOISE.sub("", raw).strip().strip(_QUOTES).strip()
        if not line:
            continue
        kind, name, body = "free", "", line
        hit = _TAG_RE.match(line)
        if hit:
            kind = _TAG_KIND[hit.group(1)]
            name = hit.group(2).strip()
            body = line[hit.end():].strip().strip(_QUOTES).strip()
        parsed.append({"kind": kind, "name": name, "text": body})
    return parsed


def _coerce(row) -> dict | None:
    """把一条原始输入收成 `{kind, name, text}`。

    字符串是**老覆写和老存档**的形状（用户存的是改动前的模板，输出 `list[str]`），
    对象是新的。两种都得认，认不出就丢这一条、不丢整批。
    """
    if isinstance(row, str):
        text = row.strip()
        return {"kind": "free", "name": "", "text": text} if text else None
    if not isinstance(row, dict):
        return None
    kind = str(row.get("kind") or "free").strip().lower()
    if kind not in KINDS:
        # 模型编了个没听过的类型时降级，而不是丢掉——它可能整条内容都是好的
        kind = "free"
    name = str(row.get("name") or "").strip()
    text = str(row.get("text") or "").strip()
    if not name and not text:
        return None
    return {"kind": kind, "name": name, "text": text}


def _synthesize(kind: str, name: str) -> str:
    """模型只给了标签、没写正文时的兜底文案。

    放在后端而不是前端：两条路都要，一处生成比两处各写一遍好。
    """
    if kind == "skill":
        return f"你施展了「{name}」。"
    if kind == "item":
        return f"你用了「{name}」。"
    if kind == "move":
        return f"你前往{name}。"
    return ""


def clean_suggestions(
    raw, sess: RpgSession, src: SuggestSources, limit: int = MAX_SUGGESTIONS,
) -> list[dict]:
    """收口成 `[{text, kind, name, action_id}]`，对不上白名单的降级成自由文本。

    `raw` 可以是 `list[str]`（老覆写 / 老存档 / 每轮结算的旧格式）、
    `list[dict]`（结算的新 JSON），或 `parse_tagged_lines` 的结果。

    `limit` 是收完最多留几条。默认值就是被动路的行为；主动路自己传个大数先捞
    一个宽候选池，回头交给 `split_quota` 分桶。
    """
    allow = allow_lists(sess, src)
    by_name = {norm_name(a.name): a for a, _who in src.usable}

    out: list[dict] = []
    seen: set[str] = set()
    for row in raw if isinstance(raw, list) else []:
        item = _coerce(row)
        if item is None:
            continue
        kind, name, text = item["kind"], item["name"], item["text"]
        action_id = None

        if kind in ("skill", "item", "move"):
            # 名字对不上就把这条降级，而不是丢掉：正文本身作为自由文本建议依然成立
            original = allow[kind].get(norm_name(name))
            if original:
                name = original
            else:
                kind, name = "free", ""
        elif kind == "action":
            action = by_name.get(norm_name(name))
            if action is not None:
                action_id, name = action.id, ""
            else:
                kind, name = "free", ""

        if not text:
            text = _synthesize(kind, name)
        text = text[:MAX_TEXT_CHARS]
        if not text or text in seen:
            continue
        seen.add(text)
        out.append({"text": text, "kind": kind, "name": name, "action_id": action_id})
        if len(out) >= limit:
            break
    return out


def split_quota(
    rows: list[dict],
    max_structured: int = MAX_STRUCTURED,
    max_free: int = MAX_FREE,
) -> list[dict]:
    """给主动路分名额：能点的最多 3 条、对白最多 3 条，按原顺序各取前几条。

    不直接从头截够数，是因为两类东西抢一个池子时，写得多的那类必然吃掉写得少的：
    模型一口气写满 6 条能做的事，截前 3 条就把后面的对白整段挤没了。

    返回时能点的一律排在对白前面——前端是分两行渲染的，顺序稳定才不会闪。
    被动路不走这里，它的总量上限在 `clean_suggestions` 就收完了。
    """
    structured = [row for row in rows if row["kind"] != "free"][:max_structured]
    free = [row for row in rows if row["kind"] == "free"][:max_free]
    return structured + free
