"""RPG 模式的上下文装配。

安全底线：module.creator_note 是「只给作者看的备注」，本模块的任何返回值里
都不能出现它。test_rpg_context.py 用哨兵串守这一条。

和酒馆 build_tavern_messages 的四处实质差别，都写在各自的位置上：
【你】段排在世界设定之前、不做真实 few-shot 轮、裁决产出的 intent 参与世界书
扫描、判定结果走独立注入通道。
"""
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rpg import (
    RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgRule, RpgSession, RpgWorldEntry,
)
from app.services.context_budget import estimate_tokens, truncate_to_token_budget
from app.services.rpg_dice import OUTCOME_LABELS
from app.services.rpg_play_style import style_block
from app.services.rpg_prompts import render
from app.services.rpg_state import (
    EFFECT_CHARS, TIER_LABEL_CHARS, check_condition, chronicle_lines, def_map,
    npc_activity, tier_list, tier_of,
)

SYSTEM_TOKEN_BUDGET = 8000
WORLD_TOKEN_BUDGET = 3000
SUMMARY_TOKEN_BUDGET = 2000
# 【你】和【在场】是新增的两块。各自先限额再拼，否则总量超标时从尾部切，
# 先切掉的正好是排在后面的叙事样例和此前剧情
STATE_TOKEN_BUDGET = 800
NPC_TOKEN_BUDGET = 1200
# 【外场】是「已经传开的事」，和状态同类：都是已发生的硬事实
CHRONICLE_TOKEN_BUDGET = 800
# 【数值的含义】是作者写死的一小段，每轮一遍。给得紧：它只该是几行钥匙，
# 真要长篇解释数值该写在世界观里
MEANING_TOKEN_BUDGET = 400
# 【场面】的额度。原先这里是给「借场面线的原文」留的三份额度（原文 600 +
# 开场白 600 + 概要 300），历史统一成一条之后没得借了——那些原文本来就在
# 窗口里。现在这一块只放**不在消息里的东西**：地点描述和在场名单，
# 几百 token 足够，额度小是因为它真的只剩这么点内容
SCENE_TOKEN_BUDGET = 400

# 【外场】的抬头。这段固定话术是**口吻的一部分**，不是客套：大事记注入每
# 一条线，等于所有 NPC 全知，所以必须明说「听说」不等于「亲眼见过」，
# 否则玩家在密室里做的事，隔着半个镇子的老兵也会知道
CHRONICLE_PREAMBLE = (
    "以下是这一带已经传开的事。人尽皆知的传闻，不等于每个人亲眼见过——"
    "谁在场、谁只是听说，按各自的位置来。"
)

# 【场面】的抬头。它挡的是一件单独的事：**模型是 GM，知道全场，但在场的
# 角色不是全知**。统一时间线之后它看得见玩家独自做的事、也看得见别人和玩家
# 的私聊，而它写的是面前这几个人的反应——没人愿意看到 NPC 张口就是她不该
# 知道的事。所以「谁知道什么」的判据必须写在这里
SCENE_PREAMBLE = (
    "在场的人只知道**自己也在场**的那些事。你在别处、或在别人不在场时做的事，"
    "他们不知道，除非有人告诉过他们——不要让他们主动提起。"
)

DEFAULT_CHAR_NAME = "冒险者"

# 各档位该怎么写。由后端查表生成而不是让模型自由发挥——
# roll-then-narrate 最常见的翻车就是模型拿到「失败」却写着写着自己救回来了
OUTCOME_GUIDANCE = {
    "crit_success": "做成了，而且比预想的更好。多给一点：一个额外的发现、一个没料到的便利，或是让在场的人对你另眼相看。",
    "success": "做成了，干净利落。不要额外加代价。",
    "narrow": "做成了，但付出了看得见的代价。",
    "fail": "没做成。事情卡在那儿，处境还因此麻烦了一点。",
    "crit_fail": "不但没做成，还引出了新的麻烦。",
}

# 代价要具体。数值名现在是模组作者自己取的，没法按名字查预设提示，
# 所以只留这一条通用的
DEFAULT_COST_HINT = "代价要具体：受伤、丢东西、弄出声响被发现、耽误时间、让某人对你更警惕，挑一个写实的。"

# 夹逼的后半句。头尾各写一遍是对硬事实最有效的做法，代价几十 token
OUTCOME_TAIL = {
    "crit_success": "不要在后面又加上代价。",
    "success": "不要在后面又加上代价。",
    "narrow": "不要把它写成干净利落的成功，代价必须落在纸面上。",
    "fail": "不要写着写着把它救回来。",
    "crit_fail": "不要写着写着把它救回来。",
}

_KEYWORD_SEP = re.compile(r"[,，、;；\n]+")


def _split_keywords(text: str) -> list[str]:
    """顿号和分号也算分隔符，理由同酒馆：中文列举本来就爱用顿号。"""
    return [k.strip() for k in _KEYWORD_SEP.split(text or "") if k.strip()]


def triggered_entries(
    entries: list[RpgWorldEntry],
    scan_text: str,
    sess: RpgSession | None = None,
    npcs: list[RpgNpc] | None = None,
) -> list[RpgWorldEntry]:
    """本轮生效的词条：常驻的全要，其余看关键词是否命中，最后一律过数值条件。

    子串匹配而不是分词：关键词是用户逐条写死的，「出现这个词就触发」才可预测。

    trigger_condition 是附加约束，加在关键词之后而不是替代它——
    「常驻+条件」就是阈值事件（好感过 50 她的态度变了），
    「关键词+条件」是提到了且够格才注入。这一层让世界书兼任事件系统。
    """
    haystack = (scan_text or "").lower()
    hits = []
    for entry in entries:
        if not entry.enabled or not (entry.content or "").strip():
            continue
        if entry.constant:
            matched = True
        else:
            matched = bool(haystack) and any(
                kw.lower() in haystack for kw in _split_keywords(entry.keywords)
            )
        if not matched:
            continue
        # sess 为 None 时跳过条件检查：纯关键词测试和预览都用不到状态
        if sess is not None and not check_condition(entry.trigger_condition, sess, npcs)[0]:
            continue
        hits.append(entry)
    return hits


def world_npcs(npcs: list[RpgNpc]) -> list[RpgNpc]:
    """能当「世界里的角色」用的那些。

    主角模板是开局时预填玩家自己的那张卡，不登场。前端一直按这条过滤
    （condition.ts 的 knownNpcs），后端也不能把它当 NPC 发进提示词。
    """
    return [n for n in npcs if (n.role or "npc") != "protagonist"]


def npc_place(npc: RpgNpc, slot: str = "", places: dict | None = None) -> str:
    """这个人此刻在哪儿：剧情挪过她就听剧情的，否则作息表 → 常驻地点。

    **这不是第二个「在场」判据**，只是把 location 的取值方式换成了按时段查表。
    谁在场仍然只有一种问法（here_npcs），前端 condition.onstage 是它的镜像，
    两边一起改，否则会出现「面板上站在你面前、提示词里没这个人」。

    places 是这一局的 npc_places：玩家在对话框里说「你过来」之后，结算把她的
    位置写在里面。它是**剧情的事实**，优先于作息表这个**设定**；推时段时被
    清空，作息表重新说了算。传 None（读不到会话的场合，比如模组编辑页）就
    当它不存在，行为和加这一列之前逐字一致。
    """
    over = str((places or {}).get(str(npc.id)) or "").strip()
    if over:
        return over
    table = npc.slot_locations if isinstance(npc.slot_locations, dict) else {}
    now = (slot or "").strip()
    if now:
        at = str(table.get(now) or "").strip()
        if at:
            return at
    return (npc.location or "").strip()


def named_npcs(npcs: list[RpgNpc], text: str) -> list[RpgNpc]:
    """名字（或触发词）在这段文字里出现过的人。

    给「位置」那条写入路径当允许名单：只有**刚写出来的正文里真的出现了**
    的人，才准结算改他的位置。比 onstage_npcs 的「被提到」再紧一层——
    玩家嘴上抱怨一句马尔福，不该把马尔福挪到他跟前；正文里写了他推门进来，
    才叫剧情真的动了这个人。

    认名字的口径和小节和 onstage_npcs 一致（真名子串 + 触发词）。
    """
    haystack = (text or "").lower()
    if not haystack:
        return []
    hits = []
    for npc in world_npcs(npcs):
        name = (npc.name or "").strip().lower()
        if (name and name in haystack) or any(
            kw.lower() in haystack for kw in _split_keywords(npc.keywords)
        ):
            hits.append(npc)
    return hits


def here_npcs(
    npcs: list[RpgNpc], location: str, slot: str = "", places: dict | None = None,
) -> list[RpgNpc]:
    """就在玩家当前地点的人。

    「在场」只有这一个定义：注入设定要它，标记见过面也要它。两边各写一遍
    迟早会分叉——分叉的那一次就是「被提到一句的人再也拿不到外貌描写」。

    slot 传空（没设时段、或调用方不关心时间）时作息表不参与，一律按常驻地点算，
    和没有这个功能时逐字一致。
    """
    here = (location or "").strip()
    if not here:
        return []
    return [
        npc for npc in world_npcs(npcs)
        if npc_place(npc, slot, places) == here
    ]


def present_ids(
    npcs: list[RpgNpc], location: str, slot: str = "", places: dict | None = None,
) -> list[int]:
    """这一刻在场的 NPC id 列表。写进消息的 present 列（见 RpgMessage.present）。

    和 here_npcs 同源、不另算一套：「谁在场」全项目只有一个定义。它和
    onstage_npcs 的差别正是这里要的差别——**被提到但不在跟前的人不算在场**。
    算进去的话，你在酒馆提一句老兵，老兵就成了这场戏的见证人。

    **没有地点 = 所有人都在同一个场面里**，这条读法照抄 _settle 里那一份
    （那边管它叫 who）：模组一个地点都没建时 here_npcs 恒为空，不兜底的话
    这类纯对话模组的每条消息都会变成「只有玩家一个人」，每个 NPC 的视图全空。

    调用方必须在**写消息的那一刻**调它：npc_places 会被作息表和剧情改动，
    事后拿 sess 回查算出来的是「现在谁在」，不是「当时谁在」。
    """
    if not (location or "").strip():
        return [n.id for n in world_npcs(npcs)]
    return [n.id for n in here_npcs(npcs, location, slot, places)]


def onstage_npcs(
    npcs: list[RpgNpc], location: str, scan_text: str, slot: str = "",
    places: dict | None = None,
) -> list[RpgNpc]:
    """这一轮要注入设定的人：在场的，加上被名字或触发词提到的。

    后一半是为了「人不在这儿但这一轮聊到了他」——没有它，玩家问"老兵说过什么"
    时模型手上没有老兵的任何设定，只能现编。

    注意「注入」不等于「见过面」：被提到的人这一轮拿到设定，但不能因此算作
    他的外貌已经描写过。标记见过面的只有 here_npcs 那一份。
    """
    spots = {id(npc) for npc in here_npcs(npcs, location, slot, places)}
    haystack = (scan_text or "").lower()
    hits = []
    for npc in world_npcs(npcs):
        if id(npc) in spots:
            hits.append(npc)
            continue
        if not haystack:
            continue
        name = (npc.name or "").strip().lower()
        if (name and name in haystack) or any(
            kw.lower() in haystack for kw in _split_keywords(npc.keywords)
        ):
            hits.append(npc)
    return hits


def _qty(item: dict) -> int:
    try:
        return int(item.get("qty", 1))
    except (TypeError, ValueError):
        return 1


def _flag_text(value) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return str(value)


def _stat_text(specs: dict[str, dict], name: str, value) -> str:
    """一项数值怎么写给模型看。有上限就写成 62/100——
    模型判断「快没了」需要看到分母，只给 62 它不知道这是高还是低。

    作者写了分档就追加当前那一档的短标签：好感 62/100（亲近）。
    **只追加标签，不追加那一档的解释**——解释在【数值的含义】里整轮发一次。
    关系定义是全体 NPC 共用的一份，跟在数字后面等于同一句话按在场人数重复，
    而 NPC 那块的预算只有 800 字上下（见 _npc_block）。
    """
    spec = specs.get(name) or {}
    top = spec.get("max")
    text = f"{name} {value}/{top}" if top is not None else f"{name} {value}"
    tier = tier_of(spec, value)
    label = str((tier or {}).get("label") or "").strip()[:TIER_LABEL_CHARS]
    return f"{text}（{label}）" if label else text


def _meaning_block(module: RpgModule) -> str:
    """【数值的含义】段。作者写的「这个数值影响什么」+ 每一档什么样。

    整轮发一次，排在【你】之前：说明是**静态的定义**，但它是读懂后面所有数字
    的钥匙，被尾部截断切掉的话，模型看到的就又是一串没有意思的数字了。

    隐藏的数值也进这一块，同 _compose_state 的既定理由：隐藏只是不给玩家看，
    GM 得知道怀疑度到 80 了会发生什么。
    """
    groups = (("你的数值", module.stat_defs), ("对你的关系", module.relation_stat_defs))
    lines: list[str] = []
    for title, defs in groups:
        rows = []
        for name, spec in def_map(defs).items():
            effect = str(spec.get("effect") or "").strip()[:EFFECT_CHARS]
            bands = []
            for tier in tier_list(spec):
                label, note = tier["label"], tier["note"]
                if not label and not note:
                    continue
                at = tier["at"]
                bands.append(f"{at} 起 {label}={note}" if label and note else f"{at} 起 {label or note}")
            if not effect and not bands:
                continue
            row = f"- {name}：{effect}" if effect else f"- {name}："
            if bands:
                row = (row + "。" if effect else row) + "；".join(bands)
            rows.append(row)
        if rows:
            lines.append(f"{title}：")
            lines.extend(rows)
    if not lines:
        return ""
    return truncate_to_token_budget("【数值的含义】\n" + "\n".join(lines), MEANING_TOKEN_BUDGET)


def _compose_state(
    sess: RpgSession, specs: dict[str, dict], items: list[dict], keep: int,
    here: list[RpgNpc] | None = None,
) -> str:
    lines = [f"【你】{(sess.char_name or '').strip() or DEFAULT_CHAR_NAME}"]
    if (sess.char_desc or "").strip():
        lines.append(sess.char_desc.strip())
    # 数值表整份给模型，包括 display=隐藏 的——隐藏只是不给玩家看见，
    # GM 得知道怀疑度已经 80 了
    stats = sess.stats or {}
    if stats:
        lines.append("状态：" + "　".join(
            _stat_text(specs, k, v) for k, v in stats.items()
        ))
    if (sess.location or "").strip():
        lines.append(f"所在：{sess.location.strip()}")
    # 时间只在模组设了时段时才出现。模型看得见才会照着写，
    # 看不见它就会自己编「不知不觉天黑了」
    slot = str(getattr(sess, "slot", "") or "").strip()
    if slot:
        lines.append(f"时间：第 {max(1, int(getattr(sess, 'day', 1) or 1))} 天 · {slot}")
    # 这一幕是几个人。判据取**实际在跟前的人**，不再取「这条线是谁的」——线
    # 已经不存在了。原先那条理由（「没有它模型会把在场三个人写成一锅粥」）现在
    # 由人数直接回答，而且答得更准：多人在场时玩家确实是在对大家说话
    if here is not None:
        if len(here) == 1:
            lines.append(f"此刻：你正在与{(here[0].name or '').strip()}单独说话")
        elif here:
            names = "、".join((n.name or "").strip() for n in here)
            lines.append(f"此刻：在场的是你与{names}，这是群戏")
        else:
            lines.append("此刻：没有别人在场，只有你一个人")

    shown, rest = items[:keep], len(items) - keep
    rows = [
        f"- {item['name']}×{_qty(item)}"
        + (f"（{str(item.get('note')).strip()}）" if str(item.get("note") or "").strip() else "")
        for item in shown
    ]
    if rest > 0:
        rows.append(f"- 以及其他 {rest} 件杂物")
    lines.append("背包：\n" + "\n".join(rows) if rows else "背包：空")

    flags = {k: v for k, v in (sess.flags or {}).items() if v is not None}
    if flags:
        lines.append("当前处境：\n" + "\n".join(f"- {k}：{_flag_text(v)}" for k, v in flags.items()))
    return "\n".join(lines)


def _state_block(sess: RpgSession, module: RpgModule, here: list[RpgNpc] | None = None) -> str:
    """【你】段。超预算时先裁背包，不让截断的刀切在数值上。

    背包按数量降序保留——囤了 20 支箭比捡了一块石头更可能被用上。
    """
    specs = def_map(module.stat_defs)
    items = [
        it for it in (sess.inventory or [])
        if isinstance(it, dict) and str(it.get("name") or "").strip()
    ]
    ordered = sorted(items, key=lambda it: -_qty(it))
    block = ""
    for keep in range(len(ordered), -1, -1):
        block = _compose_state(sess, specs, ordered, keep, here)
        if estimate_tokens(block) <= STATE_TOKEN_BUDGET:
            return block
    # 背包裁空了还超，说明是角色描述太长，这时才允许截断
    return truncate_to_token_budget(block, STATE_TOKEN_BUDGET)


def _one_npc(
    npc: RpgNpc, sess: RpgSession, specs: dict, examples: bool, profile: bool,
) -> str:
    """一个人的卡片。examples/profile 是降级开关，见 _npc_block。"""
    state = (sess.npc_states or {}).get(str(npc.id)) or {}
    lines = [npc.name]
    if (npc.description or "").strip():
        lines.append(npc.description.strip())
    if (npc.persona or "").strip():
        lines.append(npc.persona.strip())
    # 外貌只在首次见面时给。见过之后玩家已经知道长什么样，每轮再发一遍
    # 纯属浪费，而且会让模型反复描写同一张脸
    if not state.get("met") and (npc.appearance or "").strip():
        lines.append(npc.appearance.strip())
    if profile:
        for key, text in (npc.profile_sections or {}).items():
            if str(text or "").strip():
                lines.append(f"{key}：{str(text).strip()}")
    # 关系数值是这个模式的核心：模型得知道「好感 62/100」才知道
    # 她现在该用什么态度说话
    relations = [
        _stat_text(specs, k, v) for k, v in state.items() if k != "met"
    ]
    if relations:
        lines.append("对你：" + "　".join(relations))
    # 这一局 GM 记下来的近况：伤在哪、身上带着什么、会什么。作者写的档案是
    # 死的，这一行是活的，所以它和 profile_sections 一起降级也不合适——
    # 「她左肩还在流血」比「她的背景故事」更该留在提示词里，排在示例之前
    notes = (sess.npc_notes or {}).get(str(npc.id)) or {}
    if isinstance(notes, dict) and notes:
        # 不用「此刻：」：_compose_state 已经拿它表示「你在和谁单独说话」，
        # 两块隔着几百字，同一个词两个意思
        lines.append("眼下：" + "；".join(f"{k} {v}" for k, v in notes.items()))
    # AI 调度替她写的「最近在做什么」。她不在场时在别处自己过，玩家下回撞见
    # 她得看得出这段日子没白过——不然调度就只是个后台空转的计数器。
    # 紧跟在「眼下」后面：两行是一类东西（这一局里活着的近况），
    # 排在作者写的档案之后、对话示例之前
    activity = npc_activity(sess, npc.id)
    if activity:
        lines.append(f"最近：{activity}")
    # 对话示例只作为文字引用，不做真实 few-shot 轮：那会让模型学着
    # 连玩家那一侧一起写
    if examples:
        shown = [
            f"玩家：{str(ex.get('user') or '').strip()}\n{npc.name}：{str(ex.get('assistant') or '').strip()}"
            for ex in (npc.dialogue_examples or [])
            if isinstance(ex, dict) and str(ex.get("assistant") or "").strip()
        ]
        if shown:
            lines.append("说话的样子：\n" + "\n".join(shown))
    return "\n".join(lines)


def _npc_block(npcs: list[RpgNpc], sess: RpgSession, module: RpgModule) -> str:
    """【在场】段。超预算时**先把全体的示例和档案段砍掉，最后才截断**。

    同 _state_block 的道理，但这里的后果更重：截断是从尾部切的，切掉的是
    整整一个人——而 mark_met 按「谁在场」标记、不看他的文字有没有活下来，
    于是那个人的外貌**从此再也不会注入**。预算只有 NPC_TOKEN_BUDGET，
    中文按 1.5 token/字算，全体在场角色加起来只有约 800 字，三个人同框
    就已经到崖边了。

    在场的排前面：onstage_npcs 是按 sort_order 追加的，一个只是被提到名字
    的人能把真正站在跟前的人挤到后面、进而挤出预算。
    """
    specs = def_map(module.relation_stat_defs)
    here = (sess.location or "").strip()
    # 稳定排序：同组内仍按 sort_order。地点为空时全员等价，不重排
    ordered = sorted(
        npcs, key=lambda n: (npc_place(n, sess.slot, sess.npc_places) != here) if here else False
    )

    for examples, profile in ((True, True), (False, True), (False, False)):
        block = "【在场】\n" + "\n\n".join(
            _one_npc(n, sess, specs, examples, profile) for n in ordered
        )
        if estimate_tokens(block) <= NPC_TOKEN_BUDGET:
            return block
    # 示例和档案都砍光还超，说明是角色描述本身太长，这时才允许切
    return truncate_to_token_budget(block, NPC_TOKEN_BUDGET)


def judgement_blocks(judgement: dict) -> tuple[str, str]:
    """判定结果的头尾两块。头块插在玩家那句话最前面，尾块追加在最后面。"""
    outcome = judgement.get("outcome") or "success"
    attr = (judgement.get("attr") or "").strip()
    guidance = OUTCOME_GUIDANCE.get(outcome, OUTCOME_GUIDANCE["success"])
    if outcome in ("narrow", "fail", "crit_fail"):
        guidance = f"{guidance}{DEFAULT_COST_HINT}"
    label = OUTCOME_LABELS.get(outcome, outcome)
    head = render(
        "rpg_judgement.jinja2",
        intent=judgement.get("intent") or "这个行动",
        attr=attr or "数值",
        rate=int(judgement.get("rate") or 0),
        dice=int(judgement.get("dice") or 0),
        outcome_label=label,
        guidance=guidance,
    ).strip()
    tail = (
        f"（再次确认：本回合结果是「{label}」。"
        f"{OUTCOME_TAIL.get(outcome, '照这个结果写。')}）"
    )
    return head, tail


def _inject_by_depth(messages: list[dict], entries: list[RpgWorldEntry]) -> None:
    """把词条并进倒数第 depth 条消息的开头，原地改 messages。

    不新增消息行，理由同酒馆：各供应商对 user/assistant 交替有要求。
    """
    if not entries:
        return
    tail = len(messages) - 1  # 0 是 system
    if tail <= 0:
        return
    by_index: dict[int, list[str]] = {}
    for entry in entries:
        depth = max(1, min(int(entry.depth or 1), tail))
        by_index.setdefault(len(messages) - depth, []).append(entry.content.strip())
    for idx, blocks in by_index.items():
        note = "【世界设定】\n" + "\n\n".join(blocks)
        messages[idx]["content"] = f"{note}\n\n{messages[idx]['content']}"


def facts_block(facts: list[str]) -> str:
    """引擎已经算完的事实。道具、移动、动作按钮走的是死数字，模型只负责把它写出来。"""
    rows = "\n".join(f"- {f}" for f in facts)
    return (
        "【本回合已定事实 · 由系统结算，不可更改】\n"
        f"{rows}\n"
        "把这些写进正文，写成读者能看见的画面，不要改动它们，也不要在正文里写出数字本身。"
    )


def _inject_judgement(messages: list[dict], judgement: dict) -> None:
    """判定块夹在玩家那句话的头和尾。必须在 _inject_by_depth 之后调用——
    depth=1 的世界书也落在这条消息上，判定块得排在它前面。

    放这儿而不是 system：离当前对话越近模型越不会忽略，而判定结果是这一轮
    最不能被忽略的事实。
    """
    head, tail = judgement_blocks(judgement)
    last = messages[-1]
    last["content"] = f"{head}\n\n{last['content']}\n\n{tail}"


def history_window(
    module: RpgModule,
    sess: RpgSession,
    history: list[RpgMessage],
    focus_npc_id: int | None = None,
) -> list[RpgMessage]:
    """发原文的窗口：已压缩进概要的消息不再重复发。

    公开而不是私有：「帮我想想」也要按同一套规则取最近发生的事，
    两边各切一次的话，窗口的边界迟早对不上。

    只剩一份概要指针了（历史统一成一条），所以不再按线取。原先那个 thread_id
    参数是「传错线会让窗口按另一条线的进度去切，边界看着还很正常」的来源之一
    """
    if focus_npc_id:
        try:
            upto = int((sess.thread_upto or {}).get(str(focus_npc_id), 0) or 0)
        except (TypeError, ValueError):
            upto = 0
        visible = [
            m for m in history
            if m.present is None or focus_npc_id in (m.present or [])
        ]
    else:
        upto = sess.summarized_upto_id or 0
        # 无目标时是公共场景上下文，只保留公开消息和群戏消息。
        # 单人私聊由对应 NPC 线承接，避免重新回到全量历史泄露问题。
        first_message_id = min((m.id for m in history), default=0)
        visible = [
            m for m in history
            if m.present is None
            or len(m.present or []) > 1
            or (m.id == first_message_id and m.role == "assistant")
        ]
    limit = max(1, module.context_turns or 20) * 2
    return [m for m in visible if m.id > upto][-limit:]


def summary_for_focus(sess: RpgSession, focus_npc_id: int | None = None) -> str:
    """Return the summary visible to the current narration scope."""
    if focus_npc_id:
        return (sess.thread_summaries or {}).get(str(focus_npc_id), "") or ""
    return sess.summary or ""


def scene_block(sess: RpgSession, description: str, here: list[RpgNpc]) -> str:
    """【场面】：当前这一幕不在消息里的那些信息。空串 = 这一轮不拼。

    历史统一成一条之后，这一块**不再是「借历史」**——原先它干的是把场面线的
    原文读时复制给角色线，那是在补「历史被切开了」的窟窿。现在没有窟窿可补：
    所有消息都在同一条时间线上，模型本来就看得见开场白、看见你刚才做了什么、
    看见群戏里谁说了什么。

    剩下的只有**消息里没有的东西**：

    - **地点描述**。`_compose_state` 里只有地点名（「所在：地窖」），描述从来
      没进过上下文——作者写了一整段地窖的样子，模型一个字没见过
    - **在场名单**。`_npc_block` 给了每个人的设定，但那是「这一轮要注入的人」，
      含被提到但不在跟前的人；这一行专门回答「眼前站着谁」

    description 由调用方查好传进来（`build_rpg_messages` 顺手查了 RpgLocation），
    这里保持纯函数：能直接测，也不用把整个 module 塞进来。

    两样都从**活状态**读，不从消息读。这是它和旧 scene_background 的根本差别：
    那个读的是历史，所以必须防「复制进别的线会让同一段戏各演化一遍」；这个读的
    是当前状态，拼多少次都一样，一个字都不写回任何地方。
    """
    name = (sess.location or "").strip()
    parts: list[str] = []
    if name:
        text = (description or "").strip()
        parts.append(f"地点：{name}" + (f"\n{text}" if text else ""))

    # 在场名单。空名单也要写出来——「没有别人」和「没提」对模型是两回事，
    # 不写的话它会照着上下文里的角色自己安排一个站到跟前
    if here:
        parts.append("在场：" + "、".join((n.name or "").strip() for n in here))
    elif name:
        parts.append("在场：只有你一个人")

    if not parts:
        return ""
    return truncate_to_token_budget(
        "【场面】\n" + SCENE_PREAMBLE + "\n\n" + "\n\n".join(parts),
        SCENE_TOKEN_BUDGET,
    )


async def resolve_rules(
    session: AsyncSession, user_id: int | None, ids: list[int]
) -> str:
    """按模组勾选的 id 拼 RPG 写作规则，无兜底——空就是空。

    照酒馆 tavern_context.resolve_rules：RPG 默认不注入规则，没有小说侧那套
    「NULL 回退到内置护栏」的语义。失效 id（规则被删）自然筛掉。
    """
    if not ids:
        return ""
    wanted = {int(i) for i in ids}
    rules = (await session.execute(
        select(RpgRule)
        .where(RpgRule.user_id == user_id, RpgRule.enabled.is_(True))
        .order_by(RpgRule.sort_order, RpgRule.id)
    )).scalars().all()
    return "\n\n".join(
        r.content.strip() for r in rules if r.id in wanted and r.content.strip()
    )


async def build_rpg_messages(
    session: AsyncSession,
    module: RpgModule,
    sess: RpgSession,
    history: list[RpgMessage],
    new_input: str,
    judgement: dict | None = None,
    facts: list[str] | None = None,
    focus_npc_id: int | None = None,
) -> tuple[list[dict], dict]:
    """组装发给叙事模型的 messages，返回 (messages, diag)。

    judgement 是本轮的判定结果（roll 列的内容）。need_check 为假或为 None 时
    不注入判定块，这一轮就是纯叙事。

    facts 是引擎已经结算完的事实（用了药水回 20 精力、门锁着进不去）。它和
    judgement 走同一条通道：都是「不可更改的已定结果」，模型只负责落成画面。

    history 是**全部**历史，调用方不再按线切——线已经不存在了。原先那两个参数
    （thread_id、scene_history）一个管「这一轮归哪条线」、一个管「把场面线借给
    角色线」，现在都没得借：所有消息本来就在同一条时间线上。

    creator_note 永不出现在返回值里。
    """
    window = history_window(module, sess, history, focus_npc_id)
    # scan_depth=1 就只扫玩家刚发的这句。往回扫得越多，GM 自己的旁白越容易
    # 让词条反复命中——它提到了那个词，下一轮扫描又扫到，自己喂自己
    back = max(0, int(module.scan_depth or 3) - 1)
    intent = (judgement or {}).get("intent") or ""
    # intent 一起参与扫描：玩家写「我撬门」、词条关键词是「锁」，子串匹配不上；
    # 裁决归一化出的「用铁丝撬开生锈的铁锁」能命中。
    # 那次调用本来就要发生，检索召回是顺手买到的
    scan_parts = ([m.content for m in window[-back:]] if back else []) + [new_input, intent]
    scan_text = "\n".join(p for p in scan_parts if p)

    entries = (await session.execute(
        select(RpgWorldEntry)
        .where(RpgWorldEntry.module_id == module.id)
        .order_by(RpgWorldEntry.sort_order, RpgWorldEntry.id)
    )).scalars().all()
    npcs = (await session.execute(
        select(RpgNpc)
        .where(RpgNpc.module_id == module.id)
        .order_by(RpgNpc.sort_order, RpgNpc.id)
    )).scalars().all()
    # 词条的数值条件里可以写「赫敏的好感≥50」，所以要先拿到 npcs 再筛词条
    hits = triggered_entries(list(entries), scan_text, sess, list(npcs))
    onstage = onstage_npcs(
        list(npcs), sess.location, scan_text, sess.slot, sess.npc_places,
    )
    # 真的在跟前的那几个。标记见过面只认这一份：npcs_onstage 里还含被提到的
    # 人，他们的外貌这一轮发了，但人并没见到，不能算见过
    here = here_npcs(list(npcs), sess.location, sess.slot, sess.npc_places)
    # 当前地点的描述。只按名字查一条——用不上整张表，多查的每一条都会在
    # 每轮上下文里凭空多算一次 token
    place_description = ""
    if (sess.location or "").strip():
        place_description = (await session.execute(
            select(RpgLocation.description)
            .where(
                RpgLocation.module_id == module.id,
                RpgLocation.name == (sess.location or "").strip(),
            )
            .limit(1)
        )).scalars().first() or ""

    sections: list[str] = []
    sections.append(render(
        "rpg_gm.jinja2",
        char_name=(sess.char_name or "").strip() or DEFAULT_CHAR_NAME,
        genre=(module.genre or "").strip(),
        reply_length=max(0, int(module.reply_length or 0)),
    ).strip())

    # 玩法规则紧跟在 GM 指令后面，作为独立的一段而不是模板里的一个变量：
    # 改过 rpg_gm.jinja2 的用户存的是旧版本，往模板里塞占位符对他们就是静默失效。
    # 排在 system_instruction 之前，作者自己写的规则仍然能压过类别的通用规则
    sections.append(style_block(module.play_style))

    if (module.system_instruction or "").strip():
        sections.append(module.system_instruction.strip())

    if (module.worldview or "").strip():
        sections.append("【世界观】\n" + module.worldview.strip())

    # 【数值的含义】紧贴在数值前面：它是读懂下面所有数字的钥匙，而被尾部
    # 截断切掉的话，模型看到的就又是一串没有意思的数字了
    meaning_block = _meaning_block(module)
    if meaning_block:
        sections.append(meaning_block)

    # 【你】排在【世界设定】之前：状态每轮都在变，世界书是静态背景，
    # 硬事实靠前。整体截断从尾部切，靠前的不会被切掉
    state_block = _state_block(sess, module, here)
    sections.append(state_block)

    if focus_npc_id:
        context_npcs = [n for n in npcs if n.id == focus_npc_id]
    else:
        context_npcs = onstage
    npc_block = _npc_block(context_npcs, sess, module) if context_npcs else ""
    if npc_block:
        sections.append(npc_block)

    # 【外场】排在【在场】之后、【世界设定】之前：整体截断从尾部切，
    # 大事记是「已经发生过的硬事实」，和状态同类；放最后的话一旦超预算，
    # 被切掉的正好是跨线记忆——那恰恰是它存在的理由。
    # keep_end=True 保新弃旧：最近传开的事更可能是这一轮用得上的
    chronicle = chronicle_lines(sess)
    chronicle_block = ""
    if chronicle:
        chronicle_block = truncate_to_token_budget(
            "【外场】\n" + CHRONICLE_PREAMBLE + "\n"
            + "\n".join(f"- {line}" for line in chronicle),
            CHRONICLE_TOKEN_BUDGET, keep_end=True,
        )
        sections.append(chronicle_block)

    # 【场面】紧跟在【外场】后面：两块都是「不在消息里的背景」，位置的理由也
    # 一样（整体截断从尾部切，背景要排前面）。差别是【外场】讲的是传开的传闻，
    # 这一块讲的是眼前这一幕——地点长什么样、谁站在这里
    #
    # **必须在扫完 scan_text 之后**才拼：地点描述扫进关键词的话，写地窖的模组
    # 每进一次地窖就命中那条词条；而模型自己写的旁白又会让它下一轮再命中，
    # 自己喂自己。旧的 scene_background 有同一条规矩，理由照旧
    scene = scene_block(sess, place_description or "", here)
    if scene:
        sections.append(scene)

    # depth=0 拼进 system，depth>0 留到下面按深度插进对话流
    system_hits = [e for e in hits if (e.depth or 0) <= 0]
    depth_hits = [e for e in hits if (e.depth or 0) > 0]
    if system_hits:
        sections.append(truncate_to_token_budget(
            "【世界设定】\n" + "\n\n".join(e.content.strip() for e in system_hits),
            WORLD_TOKEN_BUDGET,
        ))

    # 叙事样例只作为文字引用，不做真实 few-shot 轮：那会让模型学着
    # 连玩家那一侧一起写，正是酒馆群聊给对话示例降级的同一个理由
    if (module.narration_sample or "").strip():
        sections.append("【叙事样例】\n" + module.narration_sample.strip())

    # 取这条线自己那一份。**不能用一份全局概要**：概要注入的是 system，
    # 一份全局概要注入每一条线，等于把你在密室里跟 A 说的话原样告诉 B
    prior = summary_for_focus(sess, focus_npc_id).strip()
    if prior:
        sections.append(
            "【此前剧情】\n" + truncate_to_token_budget(prior, SUMMARY_TOKEN_BUDGET)
        )

    # 写作规则放 sections 末尾，同酒馆：它约束的是「怎么写」，最贴近本轮生成，
    # 排最后离叙事最近、模型最不会忽略。空即不注入
    rules_block = await resolve_rules(session, module.user_id, module.enabled_rule_ids or [])
    if rules_block:
        sections.append(rules_block)

    system_content = truncate_to_token_budget("\n\n".join(sections), SYSTEM_TOKEN_BUDGET)

    messages = [{"role": "system", "content": system_content}]
    for m in window:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": new_input})

    _inject_by_depth(messages, depth_hits)
    # 事实块在判定块之后注入，于是排在更靠前的位置：引擎算出的死数字比
    # 概率判定更硬，冲突时以它为准
    if judgement and judgement.get("need_check") and judgement.get("outcome"):
        _inject_judgement(messages, judgement)
    if facts:
        messages[-1]["content"] = f"{facts_block(facts)}\n\n{messages[-1]['content']}"

    diag = {
        "system_tokens": estimate_tokens(system_content),
        "state_tokens": estimate_tokens(state_block),
        "meaning_tokens": estimate_tokens(meaning_block),
        "npc_tokens": estimate_tokens(npc_block),
        "chronicle_tokens": estimate_tokens(chronicle_block),
        # 【场面】那一段的字数。它不再随「进没进私聊线」跳变——线没了，
        # 它每轮都在，大小只跟地点描述写多长有关
        "scene_tokens": estimate_tokens(scene),
        "history_count": len(window),
        "focus_npc_id": focus_npc_id,
        # 时钟走到哪了。前端那一行诊断读这几个字段
        "slot": str(getattr(sess, "slot", "") or ""),
        "day": max(1, int(getattr(sess, "day", 1) or 1)),
        "triggered": [
            {
                "id": e.id,
                "keywords": e.keywords,
                "constant": bool(e.constant),
                "depth": int(e.depth or 0),
            }
            for e in hits
        ],
        "npcs_onstage": [{"id": n.id, "name": n.name} for n in context_npcs],
        "npcs_here": [{"id": n.id, "name": n.name} for n in here],
        "intent_used": intent,
        # 这一轮实际注入了写作规则没有，方便核对勾选是否生效
        "rules_used": bool(rules_block),
    }
    return messages, diag
