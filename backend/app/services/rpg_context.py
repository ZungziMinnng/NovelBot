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
    RpgItem, RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgRule, RpgSession,
    RpgSkill, RpgWorldEntry,
)
from app.services.context_budget import estimate_tokens, truncate_to_token_budget
from app.services.rpg_dice import OUTCOME_LABELS
from app.services.rpg_memory import event_memory
from app.services.rpg_play_style import style_block
from app.services.rpg_prompts import render
from app.services.rpg_state import (
    EFFECT_CHARS, TIER_LABEL_CHARS, check_condition, chronicle_lines, def_map,
    norm_name, npc_activity, place_note, tier_list, tier_of,
)

# 跟着 NPC_TOKEN_BUDGET 一起从 8000 抬到 9800、12000，这次到 20000。这是**整段
# system 的总闸**，从尾部切；只把【在场】的额度放大而不动它，多出来的就是从
# 尾巴上抢的，而尾巴正是写作规则、概要、长期记忆和世界设定——等于拆东墙补西墙。
# 定这个数的办法是拿各块额度之和反推：下面八块加起来 18100，留约 8% 余量给
# 抬头话术和写作规则。改任何一块额度都要回来重算这个数，别只改一边
SYSTEM_TOKEN_BUDGET = 20000
WORLD_TOKEN_BUDGET = 3000
SUMMARY_TOKEN_BUDGET = 2000
# 【你】和【在场】是新增的两块。各自先限额再拼，否则总量超标时从尾部切，
# 先切掉的正好是排在后面的叙事样例和此前剧情
STATE_TOKEN_BUDGET = 800
# 全体在场角色分这一份。一个写全了的角色（简介+人设+四栏档案）自己就能吃掉
# 两三千字，所以 3000 token 时**一个人写满就超**，五六个人同框必然走降级链；
# 而降级是**整块砍掉所有人的档案段**、不是按人截短，于是写得越长模型看到的
# 反而越少。10000 约合 6600 字，够五六个人各带一份完整档案——这正是
# _npc_block 的注释一直声称、但 3000 根本兑现不了的目标。
# 抬这个数必须同时抬 SYSTEM_TOKEN_BUDGET，否则多出来的是从尾巴上抢的
NPC_TOKEN_BUDGET = 10000
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
# 【道具与技能】的额度。它是**静态的模组说明书**，每轮一模一样，所以给得紧：
# 一条只占「名字 + 一句话」，700 大约能放五六十条，够绝大多数模组一次列全
CATALOG_TOKEN_BUDGET = 700
# 每条说明留多少字。作者的道具描述可能写了两百字，整段塞进来就是把世界观
# 又抄了一遍——模型这里要的只是「这东西长什么样」
CATALOG_DESC_CHARS = 40

# 【道具与技能】的抬头。这段话挡的是这一块自带的两个风险：一是模型看见清单
# 就默认玩家全都有（于是主角凭空掏出还没拿到的药水），二是它照着 effects 在
# 正文里自己报数字（数值是引擎按 effects 算的，两边一定对不上）
CATALOG_PREAMBLE = (
    "以下是这个模组里定义过的道具和本事，作用是让你知道这世界上到底有哪些东西，"
    "好在剧情里安排它们出现。**背包和技能栏的实况以【你】那一段为准**，"
    "标着「还没到他手里」「还没学会」的，只有剧情真让他拿到或学到才算数，别默认他有。"
    "数值增减一律由引擎结算，你不要在正文里报数字。"
)

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

# 玩家在输入框上方明着选的三个模式。群聊=在场的都参与；私聊=只跟那一个人说话，
# 这段话也只记进她的记忆；独自行动=这一轮不跟人说话，但在场的人看着（见 turn_present）
GROUP_MODE = "group"
PRIVATE_MODE = "private"
SOLO_MODE = "solo"
TURN_MODES = (GROUP_MODE, PRIVATE_MODE, SOLO_MODE)

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
    here = norm_name(location)
    if not here:
        return []
    return [
        npc for npc in world_npcs(npcs)
        if norm_name(npc_place(npc, slot, places)) == here
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


def turn_present(
    npcs: list[RpgNpc], sess: RpgSession, mode: str, private_with: int | None,
) -> list[RpgNpc]:
    """这一轮算「在场」的那几个人。**写消息的 present 列和拼上下文共用这一份。**

    群聊和独自行动都是屋里站着谁就是谁——「独自行动」只是这一轮不跟人说话，
    不是「没人看见」。她眼睁睁看着你从箱底翻出剑谱，判成没人在场的话，下一轮
    她不知道你有剑谱，那是失忆 bug 的镜像版。

    私聊把名单收窄到那一个人，于是这段话只记进她的记忆。要求她**本来就在场**：
    不在跟前的人叫不到一边去，否则会凭空造出一段两人都不在同一个地方的对话。
    """
    ids = set(present_ids(npcs, sess.location, sess.slot, sess.npc_places))
    if mode == PRIVATE_MODE and private_with in ids:
        ids = {private_with}
    return [n for n in npcs if n.id in ids]


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


def _scene_line(here: list[RpgNpc], mode: str) -> str:
    """【你】里的「此刻」那一行：这一轮到底是在干什么。

    三个模式是玩家在输入框上方**明着选的**，不是猜出来的。它必须写进提示词
    而不只是拿去筛在场名单——不写的话，选了「独自行动」模型照样会让旁边那位
    搭话，而那句话是她说的、她自己却不该记得（她这一轮压根没被当成对话方）。

    「独自行动」**不等于「没人看见」**：屋里站着谁就写谁在旁边看着。判成没人的
    话会出上一个失忆 bug 的镜像版——她亲眼看着你翻出剑谱，下一轮却不知道你有。
    """
    names = "、".join((n.name or "").strip() for n in here)
    if mode == PRIVATE_MODE and here:
        return f"此刻：你把{names}叫到一边单独说话，旁人听不见这一段"
    if mode == SOLO_MODE:
        if here:
            return f"此刻：你在做自己的事，没有在跟谁说话；{names}在旁边看着"
        return "此刻：没有别人在场，只有你一个人"
    if len(here) == 1:
        return f"此刻：你正在与{names}单独说话"
    if here:
        return f"此刻：在场的是你与{names}，这是群戏"
    return "此刻：没有别人在场，只有你一个人"


def _compose_state(
    sess: RpgSession, specs: dict[str, dict], items: list[dict], keep: int,
    here: list[RpgNpc] | None = None, mode: str = GROUP_MODE,
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
    # 这一幕是几个人、在干什么。判据取**实际在跟前的人**加玩家选的模式，不再
    # 取「这条线是谁的」——线已经不存在了
    if here is not None:
        lines.append(_scene_line(here, mode))

    shown, rest = items[:keep], len(items) - keep
    rows = [
        f"- {item['name']}×{_qty(item)}"
        + (f"（{str(item.get('note')).strip()}）" if str(item.get("note") or "").strip() else "")
        for item in shown
    ]
    if rest > 0:
        rows.append(f"- 以及其他 {rest} 件杂物")
    lines.append("背包：\n" + "\n".join(rows) if rows else "背包：空")

    # 会哪些招。冷却中的也列出来并标明——GM 知道这一招正歇着，才会写
    # 「你伸手去掐诀，指尖还是麻的」而不是让玩家凭空又来一遍
    skills = [
        s for s in (sess.skills or [])
        if isinstance(s, dict) and str(s.get("name") or "").strip()
    ]
    if skills:
        lines.append("技能：" + "　".join(
            f"{str(s['name']).strip()}"
            + (f"（还要歇 {int(s['cooldown_left'])} 回合）"
               if int(s.get("cooldown_left") or 0) > 0 else "")
            for s in skills
        ))

    # 手上还挂着的事。GM 知道这些，才会让剧情往这几条上靠，而不是每一轮
    # 都开一摊新的。状态块统共只有 800 token，列多了会把别的挤掉，所以封顶 8 条
    todo = [
        str(t.get("name") or "").strip() for t in (sess.tasks or [])
        if isinstance(t, dict) and str(t.get("status") or "open") == "open"
        and str(t.get("name") or "").strip()
    ]
    if todo:
        line = "手上的事：" + "　".join(todo[:8])
        if len(todo) > 8:
            line += f"　以及其他 {len(todo) - 8} 桩事"
        lines.append(line)

    flags = {k: v for k, v in (sess.flags or {}).items() if v is not None}
    if flags:
        lines.append("当前处境：\n" + "\n".join(f"- {k}：{_flag_text(v)}" for k, v in flags.items()))
    return "\n".join(lines)


def _state_block(
    sess: RpgSession, module: RpgModule, here: list[RpgNpc] | None = None,
    mode: str = GROUP_MODE,
) -> str:
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
        block = _compose_state(sess, specs, ordered, keep, here, mode)
        if estimate_tokens(block) <= STATE_TOKEN_BUDGET:
            return block
    # 背包裁空了还超，说明是角色描述太长，这时才允许截断
    return truncate_to_token_budget(block, STATE_TOKEN_BUDGET)


def _owned(rows) -> set[str]:
    """这一局已经在手上 / 已经会了的那些名字。"""
    return {
        norm_name(str(row.get("name") or ""))
        for row in rows or []
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }


def _catalog_group(rows, owned: set[str], label: str, yes: str, no: str,
                   desc_chars: int, keep_rest: bool) -> list[str]:
    """一类东西的行。已经有的排前面：超预算时降级先丢的该是他还没有的那些。"""
    mine: list[str] = []
    rest: list[str] = []
    for row in rows or []:
        name = str(getattr(row, "name", "") or "").strip()
        if not name:
            continue
        has = norm_name(name) in owned
        desc = " ".join(str(getattr(row, "description", "") or "").split())[:desc_chars]
        line = f"- {name}（{yes if has else no}）" + (f"：{desc}" if desc else "")
        (mine if has else rest).append(line)
    if not keep_rest:
        rest = []
    return [f"{label}：", *mine, *rest] if (mine or rest) else []


def catalog_block(items, skills, sess: RpgSession) -> str:
    """【道具与技能】——这个模组定义过的东西的说明书。

    没有这一块的话，没勾「开局就有」/「开局就会」的道具和技能，GM 压根不知道
    它们存在，于是这一局里**永远不会出现**——作者辛苦定义的一摊东西，除非手动
    写进开局背包，否则玩家一辈子见不着。这是它存在的唯一理由。

    只给名字加一句话，**不给 effects**：数值增减是引擎按 effects 算的，把数字
    摆进提示词只会诱导模型在正文里自己报一遍，两边一定对不上。

    超预算时三级降级：先砍掉说明只留名字，再砍掉「他还没有的」那一半，
    最后才真截断——切掉的顺序是从最不要紧的开始。
    """
    owned_items = _owned(getattr(sess, "inventory", None))
    owned_skills = _owned(getattr(sess, "skills", None))
    block = ""
    for desc_chars, keep_rest in ((CATALOG_DESC_CHARS, True), (0, True), (0, False)):
        lines = [
            *_catalog_group(items, owned_items, "道具", "他身上有", "还没到他手里",
                            desc_chars, keep_rest),
            *_catalog_group(skills, owned_skills, "本事", "他已经会", "还没学会",
                            desc_chars, keep_rest),
        ]
        if not lines:
            return ""
        block = "【道具与技能】\n" + CATALOG_PREAMBLE + "\n" + "\n".join(lines)
        if estimate_tokens(block) <= CATALOG_TOKEN_BUDGET:
            return block
    return truncate_to_token_budget(block, CATALOG_TOKEN_BUDGET)


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
    于是那个人的外貌**从此再也不会注入**。预算 NPC_TOKEN_BUDGET，中文按
    1.5 token/字算，全体在场角色加起来约 6600 字——够五六个人各带一份完整
    档案，但再多仍然会走到这条降级链上。

    在场的排前面：onstage_npcs 是按 sort_order 追加的，一个只是被提到名字
    的人能把真正站在跟前的人挤到后面、进而挤出预算。
    """
    specs = def_map(module.relation_stat_defs)
    here = (sess.location or "").strip()
    # 稳定排序：同组内仍按 sort_order。地点为空时全员等价，不重排
    ordered = sorted(
        npcs,
        key=lambda n: (
            norm_name(npc_place(n, sess.slot, sess.npc_places)) != norm_name(here)
            if here else False
        ),
    )

    roster = ""
    if here:
        local = [
            n for n in ordered
            if norm_name(npc_place(n, sess.slot, sess.npc_places)) == norm_name(here)
        ]
        if local:
            roster = (
                f"当前地点：{here}\n"
                "下面列出的是地图中已经登记、此刻就在当前地点的角色。"
                "优先让这些角色出场和互动；不要为同一职位、同一功能或同一场景另造一个有名 NPC。\n"
                "如果玩家刚抵达或只是观察环境，开场先从这份名册中选合适的角色回应；"
                "只有玩家明确避开人群、独处或要求新角色时才不让他们出场。\n"
                "括号里的 ID 只供系统识别，不要写进正文。\n"
                "地点角色名册：" + "、".join(
                    f"{n.name}(ID:{n.id})" for n in local
                ) + "\n\n"
            )

    for examples, profile in ((True, True), (False, True), (False, False)):
        block = "【在场】\n" + roster + "\n\n".join(
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


def current_scene_block(sess: RpgSession, here: list[RpgNpc], mode: str) -> str:
    location = (sess.location or "").strip() or "未登记地点"
    lines = [
        "【本轮当前场景 · 硬事实】",
        f"玩家本轮开始时位于「{location}」。",
        "历史消息中的地点属于过去；除非玩家本轮明确要求移动，不要把当前行动写成刚从其他地点出来。",
    ]
    slot = str(getattr(sess, "slot", "") or "").strip()
    if slot:
        lines.append(f"当前时间：第 {max(1, int(getattr(sess, 'day', 1) or 1))} 天 · {slot}。")
    names = "、".join((npc.name or "").strip() for npc in here if (npc.name or "").strip())
    if names:
        lines.append(f"当前在场角色：{names}。")
    elif mode != SOLO_MODE:
        lines.append("当前没有登记在场角色。")
    return "\n".join(lines)


def _inject_judgement(messages: list[dict], judgement: dict) -> None:
    """判定块夹在玩家那句话的头和尾。必须在 _inject_by_depth 之后调用——
    depth=1 的世界书也落在这条消息上，判定块得排在它前面。

    放这儿而不是 system：离当前对话越近模型越不会忽略，而判定结果是这一轮
    最不能被忽略的事实。
    """
    head, tail = judgement_blocks(judgement)
    last = messages[-1]
    last["content"] = f"{head}\n\n{last['content']}\n\n{tail}"


PLAYER_SLOT = "player"


def message_slots(message: RpgMessage) -> list[str]:
    """这条消息该记在哪几个格子里。

    一个格子就是「一套独立的最近 N 条 + 一份自己的概要」：玩家一个，每个 NPC
    一个。**记忆按格子分，而不是按一条大流水账切**——这是玩家要的那件事：
    「和角色的对话单独存，上下文是她那边单独的最近 N 条外加摘要」。

    - **玩家格永远有份**：发生在你眼前的事，没有你记不得的道理。这一条是
      「走到别处就忘了刚才」那个 bug 的正解——原先 `present` 有人时只记进在场
      那几个 NPC 的格子、玩家格不收，于是主卧那场戏只躺在对方名下；一走到别的
      地点，窗口按**新地点**现算在场名单，对方那一格整个不进，原文和她那份概要
      两头落空，模型转头就从更早的状态重讲。老消息（`present` 为 null / `[]`）
      照旧进玩家格，等于维持「null = 对所有人可见」的老口径。
    - `present` 有人 → **再**记进在场每一个人的格子。一场三个人的戏在三个格子
      里各留一份，散场之后单独再遇见其中任何一个，她都还记得那场戏。

    玩家格装全部，不等于她们互相知道：NPC 格仍然只收她自己在场的那些，压出来
    的那份概要也只在她在跟前时注入。**GM 看得见全貌，她们看不见。**

    群戏在多个格子里各留一份**是有意的**：她们各自记得自己那个角度。代价是
    那一段会被压进好几份概要（各压各的），换来的是散场之后不丢。
    """
    slots = [PLAYER_SLOT]
    if message.present:
        slots.extend(str(i) for i in message.present)
    return slots


def slot_upto(sess: RpgSession, slot: str) -> int:
    """这个格子已经压到第几条了。玩家格用老那两列，NPC 格用按 id 分格的那两列。"""
    if slot == PLAYER_SLOT:
        return int(sess.summarized_upto_id or 0)
    try:
        return int((sess.thread_upto or {}).get(slot, 0) or 0)
    except (TypeError, ValueError):
        return 0


def slot_summary(sess: RpgSession, slot: str) -> str:
    if slot == PLAYER_SLOT:
        return (sess.summary or "").strip()
    return str((sess.thread_summaries or {}).get(slot, "") or "").strip()


def slot_window(
    module: RpgModule, sess: RpgSession, history: list[RpgMessage], slot: str,
) -> list[RpgMessage]:
    """一个格子自己的最近 N 条（已经压进它那份概要的不再发原文）。

    **压缩必须调用这同一个函数来判断溢出**（见 `rpg_turn._maybe_summarize`）。
    两边各写一遍筛选迟早会分叉，而分叉的那一次是静默丢记忆：这边不发原文、
    那边不压进概要，指针却照样往前走。
    """
    limit = max(1, module.context_turns or 20) * 2
    upto = slot_upto(sess, slot)
    return [m for m in history if m.id > upto and slot in message_slots(m)][-limit:]


def summary_block(sess: RpgSession, here: list[RpgNpc]) -> str:
    """【此前剧情】：你自己那一份，加此刻在跟前的每个人各自那一份。

    分段标出来源，不糊成一团：模型看到「（与柳如烟）」这个抬头才知道下面那段
    是她也经历过的，敢直接接话；混在一起它会拿不准哪些能说出口。

    额度按份数均分再拼，而不是拼完再从尾部切：从尾部切先切掉的正是排在后面的
    NPC 那几份——偏偏是你正在跟她说话的那一份。
    """
    slots: list[tuple[str, str]] = [("你的经历", slot_summary(sess, PLAYER_SLOT))]
    for npc in here:
        slots.append((f"与{npc.name}", slot_summary(sess, str(npc.id))))
    parts = [(title, text) for title, text in slots if text]
    if not parts:
        return ""
    share = max(1, SUMMARY_TOKEN_BUDGET // len(parts))
    body = "\n\n".join(
        f"（{title}）\n{truncate_to_token_budget(text, share)}" for title, text in parts
    )
    return "【此前剧情】\n" + body


def history_window(
    module: RpgModule,
    sess: RpgSession,
    history: list[RpgMessage],
    here_ids: set[int] | None,
) -> list[RpgMessage]:
    """发原文的窗口：玩家那一格，加此刻在跟前的每个人那一格，按时间并起来。

    公开而不是私有：「帮我想想」也要按同一套规则取最近发生的事，
    两边各切一次的话，窗口的边界迟早对不上。

    `here_ids` 传 `None` 和传空集合，结果**一样**。原先这两支是不同的行为
    （`None` = 不筛，空集 = 屋里没人所以要筛），区分它们是有意义的；玩家格
    改成装全部消息之后（见 `message_slots`），「筛」这一支本来就不再筛掉
    玩家的东西，两支于是重合。参数留着是因为各调用方各自能拿到什么不一样。

    在场名单是**当场算出来的**，不是玩家在界面上点了谁。这一条是玩家报过的
    那个失忆 bug 的正解：原先按 `focus_npc_id` 走两支，点了人才取她在场的
    那些，没点就只取「人数 > 1 的群戏」。而面包屑上的「看全部」本来就是默认
    态，于是跟她一对一聊十轮（`present=[5]`）之后随口再说一句，模型眼前只剩
    开场白——真实存档里实测，32 条消息只剩 1 条。点谁只是界面上的筛选。

    在场的人那一格是**额外**带进来的：把**她自己的**更早记忆也捞进这一轮，
    这样走进她跟前时不必等她开口就能接上旧事。

    **每格各取各的 N 条，不在合并之后再砍一刀**。砍了就会重演上面那个 bug 的
    另一个版本：你一个人赶路四十轮，她那十几轮对话会被自己的脚步声挤出窗口，
    而她那份概要还没到压缩线——于是又一次谁也不记得。合并只去重和排序。
    """
    slots = [PLAYER_SLOT] + [str(i) for i in sorted(here_ids or ())]
    picked: dict[int, RpgMessage] = {}
    for slot in slots:
        for m in slot_window(module, sess, history, slot):
            picked[m.id] = m
    return [picked[i] for i in sorted(picked)]


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
    - **这个地方现在的样子**（`place_notes` 里那一句）。地点描述是作者写死的
      原样，被玩家改过的部分只在这一句里：门踹坏了、桌子掀了。它不进任何
      记忆格——那是事实，不是叙事，压成梗概只会丢字（见 RpgSession.place_notes）

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
        # 近况跟在描述后面、单独一行：作者写的那段是这地方本来的样子，这一句
        # 是被玩家改过的地方，混成一段模型分不清哪句能改、哪句是设定
        note = place_note(sess, name)
        parts.append(
            f"地点：{name}"
            + (f"\n{text}" if text else "")
            + (f"\n现在：{note}" if note else "")
        )

    # 在场名单。空名单也要写出来——「没有别人」和「没提」对模型是两回事，
    # 不写的话它会照着上下文里的角色自己安排一个站到跟前。
    #
    # 私聊时这份名单已经由调用方收窄成那一个人了：三处（在场名单、人设卡、
    # 记忆归属）必须一起收窄，只收窄记忆那一处的话，模型看见这里还站着别人
    # 就会让他插话，而那句话按私聊记账——他说过的话他自己不记得
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
    mode: str = GROUP_MODE,
    private_with: int | None = None,
) -> tuple[list[dict], dict]:
    """组装发给叙事模型的 messages，返回 (messages, diag)。

    judgement 是本轮的判定结果（roll 列的内容）。need_check 为假或为 None 时
    不注入判定块，这一轮就是纯叙事。

    facts 是引擎已经结算完的事实（用了药水回 20 精力、门锁着进不去）。它和
    judgement 走同一条通道：都是「不可更改的已定结果」，模型只负责落成画面。

    history 是**全部**历史，调用方不再按线切——线已经不存在了。原先那两个参数
    （thread_id、scene_history）一个管「这一轮归哪条线」、一个管「把场面线借给
    角色线」，现在都没得借：所有消息本来就在同一条时间线上。

    mode 是玩家在输入框上方明着选的那三个模式之一（群聊 / 私聊 / 独自行动），
    private_with 只在私聊时有值。**这里和路由写 present 时必须算出同一份在场
    名单**——那边决定这段话记进谁的记忆，这边决定模型看见谁站在跟前，两边差
    一个人就会出「他说过的话他自己不记得」。

    creator_note 永不出现在返回值里。
    """
    npcs = (await session.execute(
        select(RpgNpc)
        .where(RpgNpc.module_id == module.id)
        .order_by(RpgNpc.sort_order, RpgNpc.id)
    )).scalars().all()
    # 真的在跟前的那几个。标记见过面只认这一份：onstage 里还含被提到的人，
    # 他们的外貌这一轮发了，但人并没见到，不能算见过
    here = here_npcs(list(npcs), sess.location, sess.slot, sess.npc_places)
    # 在场名单要在窗口之前算：窗口按它筛（见 history_window）。用 turn_present
    # 而不是上面这份 here，是为了和**写**消息那一刻用的是同一个定义——尤其是
    # 「一个地点都没建的模组 = 所有人都在同一个场面里」那条兜底，两边必须一致，
    # 否则那类模组写进去的 present 全员都有、读出来却按空名单筛，整段历史消失
    present_npcs = turn_present(list(npcs), sess, mode, private_with)
    present_set = {n.id for n in present_npcs}
    # 私聊把**三处一起**收窄：记忆归属（present，路由那边）、人设卡、【场面】
    # 名单。只收窄记忆那一处的话，模型看见屋里还站着别人就会让他插话，而那句
    # 话按私聊记账——他说过的话他自己不记得
    if mode == PRIVATE_MODE:
        here = present_npcs
    window = history_window(module, sess, history, present_set)
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
    # 词条的数值条件里可以写「赫敏的好感≥50」，所以要先拿到 npcs 再筛词条。
    # npcs 和 here 在上面（窗口之前）已经取过，这里不重取
    hits = triggered_entries(list(entries), scan_text, sess, list(npcs))
    onstage = onstage_npcs(
        list(npcs), sess.location, scan_text, sess.slot, sess.npc_places,
    )
    # 当前地点的描述。只按名字查一条——用不上整张表，多查的每一条都会在
    # 每轮上下文里凭空多算一次 token
    # 模组的道具表和技能表。整表取而不是按背包筛——这一块的用处恰恰是告诉 GM
    # 「还有哪些他没拿到的东西」，筛掉就等于又回到了它看不见的老样子
    module_items = (await session.execute(
        select(RpgItem)
        .where(RpgItem.module_id == module.id)
        .order_by(RpgItem.sort_order, RpgItem.id)
    )).scalars().all()
    module_skills = (await session.execute(
        select(RpgSkill)
        .where(RpgSkill.module_id == module.id)
        .order_by(RpgSkill.sort_order, RpgSkill.id)
    )).scalars().all()

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
    state_block = _state_block(sess, module, here, mode)
    sections.append(state_block)

    # 【道具与技能】紧跟【你】：它解释的正是【你】那一段里列出来的那几件东西，
    # 隔开就得让模型自己跨段对名字。也因为靠前，整段超预算从尾部切时它不会先没
    catalog = catalog_block(module_items, module_skills, sess)
    if catalog:
        sections.append(catalog)

    # 私聊只发她一个人的卡；群聊和独自行动发在场的加这一轮被提到的。
    # 原先这里按 focus_npc_id（玩家在面包屑上点了谁）筛，和历史那边按在场筛
    # 是两套口径并存：同屋的另一个人这一轮拿不到自己的设定，模型只能现编他
    if mode == PRIVATE_MODE:
        context_npcs = present_npcs
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

    # 概要按格子注入，名单跟窗口用**同一份** present_npcs 而不是 here：那类
    # 一个地点都没建的模组里 here 是空的，拿 here 拼的话她的原文发了、她那份
    # 长期记忆却不发——正是上下文对不上的那种裂
    # window_ids 让回忆块跳过窗口内的消息：那几条整段正文已经原样发出去了，
    # 再摘一次纯属重复占额度
    memories = event_memory(history, present_set, new_input,
                            window_ids={m.id for m in window})
    if memories:
        sections.append(memories)
    prior = summary_block(sess, present_npcs)
    if prior:
        sections.append(prior)

    # 写作规则放 sections 末尾，同酒馆：它约束的是「怎么写」，最贴近本轮生成，
    # 排最后离叙事最近、模型最不会忽略。空即不注入
    rules_block = await resolve_rules(session, module.user_id, module.enabled_rule_ids or [])
    if rules_block:
        sections.append(rules_block)

    scene_anchor = current_scene_block(sess, here, mode)

    anchor_budget = estimate_tokens(scene_anchor) + 2
    system_content = truncate_to_token_budget(
        "\n\n".join(sections), max(1, SYSTEM_TOKEN_BUDGET - anchor_budget),
    )
    system_content = f"{system_content}\n\n{scene_anchor}"

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
        "catalog_tokens": estimate_tokens(catalog),
        "meaning_tokens": estimate_tokens(meaning_block),
        "npc_tokens": estimate_tokens(npc_block),
        "chronicle_tokens": estimate_tokens(chronicle_block),
        # 【场面】那一段的字数。它不再随「进没进私聊线」跳变——线没了，
        # 它每轮都在，大小只跟地点描述写多长有关
        "scene_tokens": estimate_tokens(scene),
        "history_count": len(window),
        "mode": mode,
        "private_with": private_with if mode == PRIVATE_MODE else None,
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
