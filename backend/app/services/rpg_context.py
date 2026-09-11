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

from app.models.rpg import RpgMessage, RpgModule, RpgNpc, RpgSession, RpgWorldEntry
from app.services.context_budget import estimate_tokens, truncate_to_token_budget
from app.services.rpg_dice import OUTCOME_LABELS
from app.services.rpg_prompts import render
from app.services.rpg_state import check_condition, def_map

SYSTEM_TOKEN_BUDGET = 8000
WORLD_TOKEN_BUDGET = 3000
SUMMARY_TOKEN_BUDGET = 2000
# 【你】和【在场】是新增的两块。各自先限额再拼，否则总量超标时从尾部切，
# 先切掉的正好是排在后面的叙事样例和此前剧情
STATE_TOKEN_BUDGET = 800
NPC_TOKEN_BUDGET = 1200

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


def onstage_npcs(npcs: list[RpgNpc], location: str, scan_text: str) -> list[RpgNpc]:
    """在场的人：常驻地点等于当前地点的，加上被名字或触发词提到的。

    后一半是为了「人不在这儿但这一轮聊到了他」——没有它，玩家问"老兵说过什么"
    时模型手上没有老兵的任何设定，只能现编。
    """
    here = (location or "").strip()
    haystack = (scan_text or "").lower()
    hits = []
    for npc in npcs:
        spot = (npc.location or "").strip()
        name = (npc.name or "").strip().lower()
        if here and spot and spot == here:
            hits.append(npc)
        elif haystack and name and name in haystack:
            hits.append(npc)
        elif haystack and any(kw.lower() in haystack for kw in _split_keywords(npc.keywords)):
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
    """
    top = (specs.get(name) or {}).get("max")
    return f"{name} {value}/{top}" if top is not None else f"{name} {value}"


def _compose_state(
    sess: RpgSession, specs: dict[str, dict], items: list[dict], keep: int
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


def _state_block(sess: RpgSession, module: RpgModule) -> str:
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
        block = _compose_state(sess, specs, ordered, keep)
        if estimate_tokens(block) <= STATE_TOKEN_BUDGET:
            return block
    # 背包裁空了还超，说明是角色描述太长，这时才允许截断
    return truncate_to_token_budget(block, STATE_TOKEN_BUDGET)


def _npc_block(npcs: list[RpgNpc], sess: RpgSession, module: RpgModule) -> str:
    states = sess.npc_states or {}
    specs = def_map(module.relation_stat_defs)
    blocks = []
    for npc in npcs:
        state = states.get(str(npc.id)) or {}
        lines = [npc.name]
        if (npc.description or "").strip():
            lines.append(npc.description.strip())
        if (npc.persona or "").strip():
            lines.append(npc.persona.strip())
        # 外貌只在首次见面时给。见过之后玩家已经知道长什么样，每轮再发一遍
        # 纯属浪费，而且会让模型反复描写同一张脸
        if not state.get("met") and (npc.appearance or "").strip():
            lines.append(npc.appearance.strip())
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
        # 对话示例只作为文字引用，不做真实 few-shot 轮：那会让模型学着
        # 连玩家那一侧一起写
        examples = [
            f"玩家：{str(ex.get('user') or '').strip()}\n{npc.name}：{str(ex.get('assistant') or '').strip()}"
            for ex in (npc.dialogue_examples or [])
            if isinstance(ex, dict) and str(ex.get("assistant") or "").strip()
        ]
        if examples:
            lines.append("说话的样子：\n" + "\n".join(examples))
        blocks.append("\n".join(lines))
    return truncate_to_token_budget(
        "【在场】\n" + "\n\n".join(blocks), NPC_TOKEN_BUDGET
    )


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


def _history_window(
    module: RpgModule, sess: RpgSession, history: list[RpgMessage]
) -> list[RpgMessage]:
    """发原文的窗口：已压缩进 summary 的消息不再重复发。"""
    upto = sess.summarized_upto_id or 0
    limit = max(1, module.context_turns or 20) * 2
    return [m for m in history if m.id > upto][-limit:]


async def build_rpg_messages(
    session: AsyncSession,
    module: RpgModule,
    sess: RpgSession,
    history: list[RpgMessage],
    new_input: str,
    judgement: dict | None = None,
    facts: list[str] | None = None,
) -> tuple[list[dict], dict]:
    """组装发给叙事模型的 messages，返回 (messages, diag)。

    judgement 是本轮的判定结果（roll 列的内容）。need_check 为假或为 None 时
    不注入判定块，这一轮就是纯叙事。

    facts 是引擎已经结算完的事实（用了药水回 20 精力、门锁着进不去）。它和
    judgement 走同一条通道：都是「不可更改的已定结果」，模型只负责落成画面。

    creator_note 永不出现在返回值里。
    """
    window = _history_window(module, sess, history)
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
    onstage = onstage_npcs(list(npcs), sess.location, scan_text)

    sections: list[str] = []
    sections.append(render(
        "rpg_gm.jinja2",
        char_name=(sess.char_name or "").strip() or DEFAULT_CHAR_NAME,
        genre=(module.genre or "").strip(),
        reply_length=max(0, int(module.reply_length or 0)),
    ).strip())

    if (module.system_instruction or "").strip():
        sections.append(module.system_instruction.strip())

    if (module.worldview or "").strip():
        sections.append("【世界观】\n" + module.worldview.strip())

    # 【你】排在【世界设定】之前：状态每轮都在变，世界书是静态背景，
    # 硬事实靠前。整体截断从尾部切，靠前的不会被切掉
    state_block = _state_block(sess, module)
    sections.append(state_block)

    npc_block = _npc_block(onstage, sess, module) if onstage else ""
    if npc_block:
        sections.append(npc_block)

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

    if (sess.summary or "").strip():
        sections.append(
            "【此前剧情】\n"
            + truncate_to_token_budget(sess.summary.strip(), SUMMARY_TOKEN_BUDGET)
        )

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
        "npc_tokens": estimate_tokens(npc_block),
        "history_count": len(window),
        "triggered": [
            {
                "id": e.id,
                "keywords": e.keywords,
                "constant": bool(e.constant),
                "depth": int(e.depth or 0),
            }
            for e in hits
        ],
        "npcs_onstage": [{"id": n.id, "name": n.name} for n in onstage],
        "intent_used": intent,
    }
    return messages, diag
