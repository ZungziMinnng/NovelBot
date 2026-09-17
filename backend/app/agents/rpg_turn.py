"""RPG 一轮的编排：引擎结算 → （可选）判定 → 叙事 → AI 结算。

铁律：SQLite 的写锁绝不跨 LLM 调用。每一段都是「开 session 读 → 关掉 →
调 LLM → 开 session 写 → 关掉」，这是 memory_pipeline 已经立下的规矩。

混合结算的分界线就在这个文件里：道具、移动、动作按钮是模组作者定义过的东西，
数字由 _resolve_engine 精确算完再进模型，AI 只负责把它写成画面；自由打字没有
定义可查，才让 AI 在事后提议改动（_settle），而且一律经过 rpg_state 夹紧。

判定默认是关着的（check_mode 默认 never）。推动游戏的是数值在动、跨过某条线
解锁新内容，骰子只是冒险题材的一种调味。
"""
import asyncio
import logging
import re
from datetime import datetime
from typing import AsyncIterator

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.rpg import (
    RpgAction,
    RpgItem,
    RpgLocation,
    RpgMessage,
    RpgModule,
    RpgNpc,
    RpgSession,
    RpgSkill,
)
from app.services import llm_client, rpg_settlement
from app.services.context_budget import truncate_to_token_budget
from app.services.llm_json import call_json
from app.services.rpg_context import (
    DEFAULT_CHAR_NAME,
    GROUP_MODE,
    PLAYER_SLOT,
    SUMMARY_TOKEN_BUDGET,
    build_rpg_messages,
    history_window,
    message_slots,
    npc_place,
    slot_summary,
    slot_upto,
    slot_window,
    turn_present,
    world_npcs,
)
from app.services.rpg_dice import DEFAULT_BAND, OUTCOME_LABELS, normalize_band, resolve_rate, roll
from app.services.rpg_prompts import render
from app.services.rpg_state import (
    OFFSCREEN_CHARS,
    OFFSCREEN_TAG,
    advance_slot,
    apply_inventory,
    apply_npc_activity,
    apply_relations,
    apply_stats,
    check_condition,
    check_full,
    check_zero,
    chronicle_lines,
    for_check_stats,
    mark_met,
    match_npc,
    norm_name,
    note_move,
    note_slot_chat,
    note_visited,
    npc_activity,
    push_chronicle,
    set_cooldown,
    skill_cooldown_left,
    spend_slot_action,
    tick_cooldowns,
)

logger = logging.getLogger(__name__)

# 强引用池：asyncio 只弱引用 task，不留着可能在跑完前被 GC 掉
_detached_tasks: set[asyncio.Task] = set()

# 台账保留多少条判定记录
LEDGER_LIMIT = 20
# 归一化键取 intent 的前几个字。不完美，但成本近零
LEDGER_KEY_CHARS = 6
# 裁决时给模型看的上一段剧情长度。只要够判断语境，不用给全文
RECENT_CHARS = 400
# 结算时给模型看的大事记条数。只为防它把同一件事反复写进去，
# 不是让它接着往下编，所以只看最近几条
CHRONICLE_PROMPT_LINES = 10


# 这里原先有一整段线的东西：find_thread_npc / resolve_thread_id / thread_blocker
# / _thread_clause / _in_thread / split_lines。现在没了——线没了。
#
# 一个 thread_id 曾经同时是历史分区键、隐私边界和界面视图，三件事绑在一个值上，
# 于是每次让一件对了另两件就错（§29 修视图、§30 修历史，而隐私从 §30 起其实已经
# 只剩话术在撑）。现在历史只有一条，隐私改由消息上的 present 承担（写入时快照的
# 在场名单），界面那点筛选在读取端做。**别再把「这一段归谁看」写成一个存储字段**


def _spawn_detached(coro) -> None:
    """把收尾工作丢到独立 task 上跑，不受当前请求取消的影响。"""
    task = asyncio.create_task(coro)
    _detached_tasks.add(task)
    task.add_done_callback(_detached_tasks.discard)
    task.add_done_callback(
        lambda t: t.cancelled() or (
            t.exception() and logger.exception("RPG 收尾任务失败", exc_info=t.exception())
        )
    )


def _state_payload(sess: RpgSession) -> dict:
    """发给前端的一份状态快照。面板、背包、地图都读这个。"""
    return {
        "stats": sess.stats or {},
        "inventory": sess.inventory or [],
        # 会哪些招、还剩几回合冷却。不带的话点完技能要等整页重新拉一次才灰
        "skills": sess.skills or [],
        # 手上还挂着哪几桩事。同理，不带的话任务格要整页重拉才更新
        "tasks": sess.tasks or [],
        "flags": sess.flags or {},
        # flag 的立起日期。前端 checkCondition 拿它算「某事之后 N 天」，
        # 不带的话那种按钮要等整页重拉才解锁
        "flag_days": sess.flag_days or {},
        "location": sess.location or "",
        "npc_states": sess.npc_states or {},
        # GM 这一局记下的 NPC 近况：角色卡上那一块要跟着这一轮就更新
        "npc_notes": sess.npc_notes or {},
        # AI 调度给不在场的人记的「最近在做什么」，同理
        "npc_activities": sess.npc_activities or {},
        # 剧情把谁挪到哪儿了：带回去面板才认得出「她此刻就在你面前」，
        # 不带的话要等整页重新拉一次才动
        "npc_places": sess.npc_places or {},
        # 这一轮把屋子弄成了什么样：地点页上那一行要跟着这一轮就更新，
        # 理由同 npc_notes
        "place_notes": sess.place_notes or {},
        "status": sess.status,
        # 去过哪儿：地图的迷雾按它散开，不带的话要等整页重新拉一次才亮
        "visited": sess.visited or [],
        # 时钟也跟着走。不带的话按完「结束这个时段」要等整页重新拉一次才动
        "time_slots": sess.time_slots or [],
        "slot": sess.slot or "",
        "day": sess.day or 1,
        # 这一格用掉了几格行动、聊了几条。按钮的提醒读它，不带的话
        # 「还剩一格」这件事要等整页重新拉一次才显示
        "slot_actions": sess.slot_actions or 0,
        "slot_chats": sess.slot_chats or 0,
    }


def _delta_text(delta: dict) -> str:
    """{"精力": -5} → "精力-5"。给模型看的事实句和给玩家看的提示共用。"""
    return "、".join(
        f"{name}{'+' if int(amount) > 0 else ''}{int(amount)}"
        for name, amount in (delta or {}).items()
        if int(amount or 0) != 0
    )


# ── ② 引擎结算：有定义的东西，数字是死的 ──────────────────────────────────

def _use_item(module: RpgModule, sess: RpgSession, item: RpgItem) -> tuple[list[str], list[str]]:
    facts, warnings = [], []
    changed = _delta_text(item.effects)
    if item.effects:
        warnings.extend(apply_stats(module, sess, item.effects))
    if item.consumable:
        warnings.extend(apply_inventory(sess, [{"name": item.name, "qty": -1}]))
    facts.append(
        f"你用掉了「{item.name}」" if item.consumable else f"你用了「{item.name}」"
    )
    if changed:
        facts.append(f"因此 {changed}")
    return facts, warnings


def _skill_gate(sess: RpgSession, skill: RpgSkill, npcs: list[RpgNpc]) -> str:
    """这一招发不发得出来。空串 = 发得出来。理由同 _action_gate：行动预算
    要问同一句，而两处各判一遍迟早会漂移。"""
    ok, why = check_condition(skill.requires, sess, npcs)
    return "" if ok else f"{why}，没能发出来"


def _use_skill(
    module: RpgModule, sess: RpgSession, skill: RpgSkill, npcs: list[RpgNpc]
) -> tuple[list[str], list[str]]:
    """施展一招。条件不过就只留一句事实，数值不动、冷却也不压上。"""
    blocked = _skill_gate(sess, skill, npcs)
    if blocked:
        return [f"你想施展「{skill.name}」，但{blocked}"], []
    facts, warnings = [], []
    changed = _delta_text(skill.effects)
    if skill.effects:
        warnings.extend(apply_stats(module, sess, skill.effects))
    if skill.cooldown > 0:
        # +1 是因为冷却在**每回合开头**统一递减（见 run_turn），包括紧接着的
        # 下一回合。直接存 cooldown 的话「冷却 1」下一回合就减没了，等于没歇
        set_cooldown(sess, skill.name, skill.cooldown + 1)
    facts.append(f"你施展了「{skill.name}」")
    if changed:
        facts.append(f"因此 {changed}")
    return facts, warnings


def _move(sess: RpgSession, target: RpgLocation, npcs: list[RpgNpc]) -> list[str]:
    """走过去，或者说明为什么进不去。返回事实句。

    **不看连接**：connections 只用来画地图和散迷雾（挨着去过的地方才显形），
    不再是一道关卡。拦路的只剩 enter_requires——「没有路」拦下来的多半是
    作者忘了连一条边，而玩家看到的却是一句莫名其妙的拒绝。
    """
    from_name = (sess.location or "").strip()
    ok, why = check_condition(target.enter_requires, sess, npcs)
    if not ok:
        return [f"你想进{target.name}，但{why}，被挡在外面"]
    sess.location = target.name
    # 移动是确定性的、跨线该知道的事，顺手记进大事记（和上一条移动合并）
    note_move(sess, target.name)
    note_visited(sess, target.name)
    return [f"你离开{from_name}，来到了{target.name}" if from_name else f"你来到了{target.name}"]


def _action_gate(sess: RpgSession, action: RpgAction, target: RpgNpc | None) -> str:
    """这个动作做不做得成。空串 = 做得成，否则是给玩家看的那半句原因。

    从 _run_action 里抽出来的，因为行动预算也要问同一句：被拦下的动作只留
    一句解释、一个数值都不动，不该吃掉作者给这个时段安排的行动位。抽出来
    而不是各判一遍，是为了两边不会各自漂移。
    """
    ok, why = check_condition(action.requires, sess, [target] if target else None)
    if not ok:
        return f"{why}，没能做成"
    # 地点限定和 requires 一样是「做不做得成」，所以也在动数值之前拦。
    # 按名字比，理由见 RpgAction.at_location 的注释
    need_place = (action.at_location or "").strip()
    if need_place and norm_name(sess.location or "") != norm_name(need_place):
        return f"这得在{need_place}才行"
    return ""


def _run_action(
    module: RpgModule, sess: RpgSession, action: RpgAction, target: RpgNpc | None
) -> tuple[list[str], list[str]]:
    facts, warnings = [], []
    blocked = _action_gate(sess, action, target)
    if blocked:
        return [f"你本想{action.name}，但{blocked}"], []
    if action.effects:
        warnings.extend(apply_stats(module, sess, action.effects))
    if action.relation_effects and target is not None:
        warnings.extend(apply_relations(module, sess, target.id, action.relation_effects))
    facts.append((action.prompt_hint or "").strip() or f"你{action.name}")
    mine = _delta_text(action.effects)
    if mine:
        facts.append(f"因此 {mine}")
    theirs = _delta_text(action.relation_effects) if target is not None else ""
    if theirs:
        facts.append(f"{target.name}对你的 {theirs}")
    # 推时段放在最后：advance_slot 跨天时会触发 reset_daily 把数值refill 回上限，
    # 排在 apply_stats 之前的话这个动作自己的消耗会被当天的重置抹掉
    if action.cost_slot:
        facts += advance_slot(module, sess)
    return facts, warnings


async def _resolve_engine(
    session_id: int, action_id: int | None, item_name: str, move_to: str, target_npc: str,
    skill_name: str = "",
) -> tuple[list[str], list[str], dict]:
    """把有定义的那部分算完并落库。返回 (事实句, warnings, 状态快照)。

    在叙事之前落库而不是攒到最后：装配上下文时读到的必须是改完之后的数值，
    否则模型一边被告知「精力 -5」，一边在【你】段里看到没扣的旧值。
    """
    facts: list[str] = []
    warnings: list[str] = []
    # 这一轮世界是不是真的动了。**不能拿 facts 非空当判据**：被 requires 拦下的
    # 动作、进不去的地点、还在冷却的技能、不能用的道具，全都会留下一句解释性的
    # 事实句（「你本想…没能做成」），而它们一个数值都没动。拿 facts 判会让
    # 「撞在门上」也吃掉作者给这个时段安排的一个行动位
    moved = False
    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        module = await store.get(RpgModule, sess.module_id)
        npcs = list((await store.execute(
            select(RpgNpc).where(RpgNpc.module_id == module.id)
        )).scalars().all())

        if item_name:
            item = next(
                (i for i in (await store.execute(
                    select(RpgItem).where(RpgItem.module_id == module.id)
                )).scalars().all() if norm_name(i.name) == norm_name(item_name)),
                None,
            )
            if item is None:
                warnings.append(f"模组里没有「{item_name}」这件道具")
            elif not item.usable:
                facts.append(f"你摆弄了一下「{item.name}」，但它并不是能用的东西")
            else:
                got, warn = _use_item(module, sess, item)
                facts += got
                warnings += warn
                moved = True

        if skill_name:
            skill = next(
                (s for s in (await store.execute(
                    select(RpgSkill).where(RpgSkill.module_id == module.id)
                )).scalars().all() if norm_name(s.name) == norm_name(skill_name)),
                None,
            )
            left = skill_cooldown_left(sess, skill_name)
            if skill is None:
                warnings.append(f"模组里没有「{skill_name}」这个技能")
            elif not skill.usable:
                facts.append(f"「{skill.name}」不是能主动施展的本事")
            elif left > 0:
                facts.append(f"「{skill.name}」还得歇 {left} 回合才能再用")
            else:
                # 先问一遍拦不拦：拦下来的那一句「没能发出来」也是事实句，
                # 但一个数值都没动。_use_skill 里同一个判据说了算，这里只是
                # 拿它决定要不要吃掉一格行动
                allowed = not _skill_gate(sess, skill, npcs)
                got, warn = _use_skill(module, sess, skill, npcs)
                facts += got
                warnings += warn
                moved = moved or allowed

        if move_to:
            locs = list((await store.execute(
                select(RpgLocation).where(RpgLocation.module_id == module.id)
            )).scalars().all())
            target = next((l for l in locs if norm_name(l.name) == norm_name(move_to)), None)
            if target is None:
                warnings.append(f"模组里没有「{move_to}」这个地点")
            else:
                # 同技能那一路：enter_requires 拦下来时 _move 只留一句
                # 「被挡在外面」，人还在原地，不该吃掉一格行动
                allowed, _why = check_condition(target.enter_requires, sess, npcs)
                facts += _move(sess, target, npcs)
                moved = moved or allowed

        if action_id:
            action = await store.get(RpgAction, action_id)
            if action is None or action.module_id != module.id:
                warnings.append("这个动作已经被删掉了")
            else:
                who = next((n for n in npcs if norm_name(n.name) == norm_name(target_npc)), None)
                if action.needs_target and who is None:
                    warnings.append(f"「{action.name}」得先选一个对象")
                else:
                    allowed = not _action_gate(sess, action, who)
                    got, warn = _run_action(module, sess, action, who)
                    facts += got
                    warnings += warn
                    moved = moved or allowed

        if facts:
            if moved:
                # 记一格行动。位置是硬约束，三条理由：
                # ① 必须在 apply_stats 之后（同 _run_action 末尾那条注释：跨天
                #    恢复会把这一格自己的消耗抬掉）
                # ② 必须在 seed_settlement 之前。那边把 [day, slot, turn_count]
                #    存成 clock 基线、并用它判「此后时间已推进」，而这个函数在
                #    更早就 commit 完了，所以这一推对基线不可见——和 cost_slot
                #    完全同构
                # ③ 不能放到结算之后：rpg_settlement 会用 clock 覆写返回 state
                #    里的 day/slot，放后面推的那一格会被擦掉，前端看不到
                #
                # cost_slot 的动作已经在 _run_action 里推过一格了，这里再记一格
                # 是对的：它确实占掉了作者给这个时段安排的一个行动位
                facts += spend_slot_action(module, sess)
            warnings += check_zero(module, sess)
            warnings += check_full(module, sess)
            sess.updated_at = datetime.utcnow()
            await store.commit()
        return facts, warnings, _state_payload(sess)


def move_by_name(
    sess: RpgSession, locs: list[RpgLocation], npcs: list[RpgNpc], target_name: str
) -> str:
    """瞬移：从地点总览点一个地方就直接过去，零 LLM 调用。返回给玩家看的一句话。

    纯函数：不开会话、不落库。地点表和角色表由调用方（/move 路由）读好传进来，
    改动跟着路由那一条连接一起提交。**这里绝不能自己再开一条连接**——SQLite
    只允许一个写事务，路由那边已经拍了存档（写事务开着），在里面再开一条连接
    改 rpg_sessions 必然互锁，卡满 busy_timeout 再报 database is locked。

    进不去时 sess 一个字段都不动，把那句拒绝话原样返回（进入条件没满足）。
    """
    target = next((l for l in locs if norm_name(l.name) == norm_name(target_name)), None)
    if target is None:
        return f"模组里没有「{target_name}」这个地点"
    # 已经在的地方不该走一遍 _move：那会白白往大事记里刷一条「你去了 X」
    if norm_name(sess.location or "") == norm_name(target.name):
        return f"你已经在{target.name}了"

    facts = _move(sess, target, npcs)
    return facts[0] if facts else ""


_MOVE_VERBS = "前往|前去|去往|走到|走向|走进|进入|回到|返回|移动到|赶往|来到|去"
# 动词**前面**出现这些字，这句就不是「我现在就动身」：否定、推迟、主语不是玩家、
# 一句话里串了第二个目的地
_MOVE_DENY = re.compile(r"[不别莫没未他她它你并再等]|懒得|然后")
# 地点名**后面**还允许跟什么：到了那儿要干的事。不在这张表里的一律当成
# 「这其实是个更长的地名」而不认——「去灵药园后院」里并没有灵药园后院这个登记地点，
# 认成灵药园就是把人送错地方
_MOVE_TAIL = re.compile(
    r"^(?:看看|看一看|看一眼|瞧瞧|瞧一眼|转转|转一圈|逛逛|走走|歇歇|歇会儿|休息|歇息|"
    r"睡觉|睡一觉|吃饭|喝酒|打听|找|待着|等着|一趟|一下|吧|了)")


def movement_target(content: str, locations: list[RpgLocation]) -> str:
    """自由输入里那句「我要去 XX」。命中才走引擎移动，否则整句交给 AI 结算。

    从前这里是 `re.fullmatch`：整句必须**恰好**是「去XX」，多一个「看看」就
    失配，于是玩家写「我要去酒馆看看」地点根本不会变。现在改成在句子里找移动
    动词，再拿动词后面那截来对登记地点名。

    宽的只是前后文，**地名本身仍要求完整命中**：动词后面那截要么正好是一个登记
    地点名，要么是「地点名 + 一件到了那儿要干的事」（_MOVE_TAIL）。不敢猜的一律
    返回空串，回到原来那条 AI 结算的路上——猜错的代价是把人凭空挪走，比不猜大。
    """
    text = content.strip().rstrip("。！!").strip()
    # 问句是在打听，不是在动身
    if re.search(r"[?？]|吗$", text):
        return ""
    names = {norm_name(location.name): location.name for location in locations if location.name}
    direct = names.get(norm_name(text))
    if direct:
        return direct
    hits = set()
    for match in re.finditer(_MOVE_VERBS, text):
        if _MOVE_DENY.search(text[:match.start()]):
            continue
        rest = text[match.end():].strip().lstrip("了向到往").strip().strip('「」『』“”"')
        head = norm_name(rest)
        for key, name in names.items():
            if key and head.startswith(key) and (head == key or _MOVE_TAIL.search(head[len(key):])):
                hits.add(name)
    # 一句话指了两个地方就别替玩家挑，交给 AI 去读
    return hits.pop() if len(hits) == 1 else ""


# ── ③ 判定：可选，默认关着 ────────────────────────────────────────────────

def _fallback_attr(module: RpgModule, stats: dict) -> str:
    """模型给了表里没有的数值名时回落到哪一项。

    优先第一个标了 for_check 的：资金和声望能拿来判定没有任何意义。
    """
    usable = [n for n in for_check_stats(module.stat_defs) if n in (stats or {})]
    if usable:
        return usable[0]
    keys = list(stats or {})
    return keys[0] if keys else ""


async def adjudicate(module: RpgModule, sess: RpgSession, action: str, recent: str):
    """判断这一轮要不要判定、看哪一项数值、有多难。返回 (judgement, in_tok, out_tok)。

    模型只能从五个难度档位里挑，成功率由模组的 rate_table 定死。「这算困难吗」比
    「这是 63% 还是 55%」稳定一个数量级，这是治难度漂移最有效的一招。
    """
    stats = sess.stats or {}
    prompt = render(
        "rpg_adjudicate.jinja2",
        action=action,
        stats=stats,
        location=sess.location or "",
        recent=recent,
        ledger=(sess.dc_ledger or [])[-LEDGER_LIMIT:],
    )
    model, api_format = llm_client.get_agent_client("memory", module.fast_model_ref)
    data, in_tok, out_tok = await call_json(
        [{"role": "user", "content": prompt}], model, api_format, max_tokens=500,
    )

    attr = str(data.get("attr") or "").strip()
    if attr not in stats:
        attr = _fallback_attr(module, stats)
    return {
        "need_check": bool(data.get("need_check")),
        "attr": attr,
        # normalize_band 兜住拼错和自创档位，不抛错
        "band": normalize_band(data.get("band")),
        "intent": str(data.get("intent") or "").strip() or action,
        "reason": str(data.get("reason") or "").strip(),
    }, in_tok, out_tok


def apply_roll(module: RpgModule, sess: RpgSession, judgement: dict) -> dict:
    """把档位换成成功率并判一次。纯 Python，没有 LLM 插手的余地。"""
    rate = resolve_rate(
        module.rate_table, judgement["band"],
        (sess.stats or {}).get(judgement["attr"]), module.difficulty_bias,
    )
    return {**judgement, **roll(rate, module.random_check)}


async def _store_roll(
    session_id: int, message_id: int, judgement: dict, in_tok: int, out_tok: int
) -> None:
    """判定结果落在 user 行上，顺手记一笔台账。

    挂 user 行是为了中断语义：assistant 行要等叙事跑完才创建，叙事中途崩了
    判定就丢了，可玩家明明已经看过结果。
    """
    async with AsyncSessionLocal() as store:
        row = await store.get(RpgMessage, message_id)
        if row is None:
            return
        row.roll = judgement
        # 裁决的开销记在它自己产出的那一行上，结算的记在 assistant 行上，
        # token 面板把两边加起来就是「判定结算」那一栏
        row.aux_input_tokens = in_tok
        row.aux_output_tokens = out_tok
        if judgement.get("need_check"):
            sess = await store.get(RpgSession, session_id)
            ledger = list(sess.dc_ledger or [])
            ledger.append({
                "key": (judgement.get("intent") or "")[:LEDGER_KEY_CHARS],
                "attr": judgement.get("attr", ""),
                "band": judgement.get("band", DEFAULT_BAND),
            })
            # 整个赋回去才会被标脏，原地 append JSON 列不会触发更新
            sess.dc_ledger = ledger[-LEDGER_LIMIT:]
        await store.commit()


async def _store_reply(
    session_id: int, reply: str, in_tok: int, out_tok: int,
    present: list[int] | None = None, place: str = "", settlement: dict | None = None,
) -> int:
    """落 assistant 行。必须另开 session：路由里那个在 handler 返回时就关了，
    而 handler 早于生成器结束返回。

    present / place 要和玩家那条 user 行一致：对不上的话一问一答分进两拨在场
    名单，各个视图里各缺一半。所以由路由快照一次、原样传下来，这里不重算——
    重算会拿到结算挪过人之后的状态，那是「这一轮结束后谁在」。
    """
    async with AsyncSessionLocal() as store:
        row = RpgMessage(
            session_id=session_id, role="assistant", content=reply,
            input_tokens=in_tok, output_tokens=out_tok,
            location=place, present=present,
            settlement=settlement,
        )
        store.add(row)
        sess = await store.get(RpgSession, session_id)
        # 显式改一个字段才会触发 onupdate，存档列表靠 updated_at 排序
        sess.updated_at = datetime.utcnow()
        await store.commit()
        await store.refresh(row)
        return row.id


# ── ⑥⑦ AI 结算：只管自由行动那部分的后果 ─────────────────────────────────

def _place_block(movable: list[RpgNpc], locations: list[str], sess: RpgSession) -> str:
    """结算提示词末尾追加的「人物位置」段。没人可动就是空串。

    附在 rpg_settle.jinja2 之后而不是改进模板：那个模板用户可以自定义，
    往里加变量会让他们的旧版本静默失效（同 style_block 的理由）。

    得**把这几个人现在的位置写给模型看**：不写的话它只知道「赫敏推门进来」，
    不知道她原本在宿舍，也就写不出「她回去了」那种清空。

    locations 是模组地点表里的地名。npc_places 的值原样存原样显示，模型凭空
    造一个「教室」而模组里没有这个地点时，侧栏看得见、地点总览里找不到，
    玩家照提示「去她所在的地方」就走不过去。给一份真名单让它优先用。模组
    一个地点都没建时是空表，这一句不拼，行为和加它之前逐字一致。
    """
    if not movable:
        return ""
    rows = "".join(
        f"{n.name} 现在在 {npc_place(n, sess.slot, sess.npc_places) or '行踪不明'}\n"
        for n in movable
    )
    # 放在示例那行之前：名单紧挨着要填的值，模型挑一个照抄就是了
    known = (
        "只能填这些已有的地名：" + "、".join(locations) + "\n" if locations else ""
    )
    return (
        "\n\n=== 人物位置 ===\n"
        "这段剧情里**真的换了地方**的人（被叫来、跟着走、被带走、回自己屋），"
        "在输出里加一个 npc_places：\n"
        + rows
        + known
        + '{"npc_places": {"赫敏": "校长办公室"}}\n'
        '她只是回到自己平时待的地方，就写空串 ""，系统会按作息表替她算。\n'
        "没换地方的人不要写。这个字段里只准出现上面这几位，别人一律不要写。\n"
        "它只影响「她在不在你跟前」，不改任何数值。\n"
    )


async def _settle(
    session_id: int, message_id: int, narration: str, outcome_label: str,
    engine_note: str,
    fixed_location: str | None = None,
) -> dict:
    return await rpg_settlement.settle_turn(
        session_id, message_id, narration, outcome_label, engine_note, fixed_location,
        AsyncSessionLocal, call_json, _place_block,
    )


# ── ⑧ 压缩旧剧情：一个格子一份概要 ────────────────────────────────────────

# 摘要给模型看的一句话前缀。和 suggest 那边保持一致
SUMMARY_MAX_TOKENS = 1200


async def _maybe_summarize(session_id: int) -> bool:
    """哪个格子的窗口满了，就把它自己溢出的那一段折成它自己的概要。

    格子 = 玩家一个 + 每个 NPC 一个（见 rpg_context.message_slots）。玩家那格
    用老的 summary / summarized_upto_id 两列，NPC 用按 id 分格的
    thread_summaries / thread_upto。这样「与柳如烟的长期记忆」跟「你亲身经历
    过的全部」各压各的，注入时也各注各的（见 rpg_context.summary_block）。

    **溢出的判据直接从 slot_window 反推**：那边发原文、这边压概要，两边各写
    一遍筛选迟早会分叉，而分叉的那一次是静默丢记忆——被这边跳过的消息既没进
    概要、又因为指针越过了它而不再发原文。

    一场群戏会落进在场每个人的格子，因而被压进好几份概要（各压各的）。这是
    有意的：散场之后单独再遇见其中任何一个，她那份里还留着那场戏。

    不能照抄酒馆的写法（同一个 session 里读 → 调 LLM → commit）：这个文件有
    「写锁绝不跨 LLM 调用」的铁律，所以拆成读、调、写三段，结构同 _settle。

    整个函数不抛：概要没生成只是停在旧位置，上下文退化成纯截断，下一轮照玩。
    """
    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        if sess is None:
            return False
        module = await store.get(RpgModule, sess.module_id)
        if module is None:
            return False
        history = list((await store.execute(
            select(RpgMessage)
            .where(RpgMessage.session_id == session_id)
            .order_by(RpgMessage.id)
        )).scalars().all())
        names = {
            str(npc.id): npc.name
            for npc in (await store.execute(
                select(RpgNpc).where(RpgNpc.module_id == module.id)
            )).scalars().all()
        }
        who = (sess.char_name or "").strip() or DEFAULT_CHAR_NAME

        jobs: list[dict] = []
        for slot in sorted({s for m in history for s in message_slots(m)}):
            pending = [
                m for m in history
                if m.id > slot_upto(sess, slot) and slot in message_slots(m)
            ]
            # 留下的那几条**就是** slot_window 会发原文的那几条，一条不多一条
            # 不少。这里不重写一遍 `[-limit:]`，是为了不给分叉留缝
            fresh = slot_window(module, sess, history, slot)
            overflow = pending[: len(pending) - len(fresh)]
            # 一次最多压掉两个窗口那么多条。玩家格装的是**全部**消息，老存档第一次
            # 触发时 overflow 可能是几百条：一次全塞进一个 prompt 又贵又容易糊成一句
            # 笼统的概要，中途失败还会每回合原样重试一遍。分批压、指针逐次往前推，
            # 几回合内追平；没压到的那些仍是 pending，不会被指针越过，所以丢不了。
            # 新局每轮只多两条，这一刀砍不着
            overflow = overflow[: len(fresh) * 2]
            if not overflow:
                continue
            transcript = "\n".join(
                f"{who if m.role == 'user' else 'GM'}：{m.content}" for m in overflow
            )
            jobs.append({
                "slot": slot,
                "last_id": overflow[-1].id,
                "prompt": render(
                    "rpg_summary.jinja2",
                    previous_summary=slot_summary(sess, slot),
                    transcript=transcript,
                    scope=(
                        "你亲身经历过的那些事（你自己记得，别人未必知道）"
                        if slot == PLAYER_SLOT
                        else f"你和{names.get(slot) or '某人'}之间发生的事"
                    ),
                ),
            })
        if not jobs:
            return False
        # 摘要单独一个字段：它的输出会喂给下一次摘要，错一次会一路带到局终，
        # 和「快且便宜就行」的裁决不是一类活。空 = 跟着裁决模型走
        model, api_format = llm_client.get_agent_client(
            "memory", module.summary_model_ref or module.fast_model_ref
        )

    async def _fold(prompt: str) -> str:
        text = await llm_client.dispatch_chat_complete(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            api_format=api_format,
            temperature=0.3,
            max_tokens=SUMMARY_MAX_TOKENS,
        )
        return (text or "").strip()

    # 并发而不是排队：一场群戏散场时可能几个格子同时满，串着调的话玩家要等
    # 好几次摘要才看得到这一轮结束。谁失败谁不动，不连累别人
    texts = await asyncio.gather(
        *(_fold(job["prompt"]) for job in jobs), return_exceptions=True
    )

    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        if sess is None:
            return False
        summaries = dict(sess.thread_summaries or {})
        pointers = dict(sess.thread_upto or {})
        wrote = False
        for job, text in zip(jobs, texts):
            if isinstance(text, BaseException):
                logger.warning(
                    "RPG 局 %s 的 %s 格概要失败：%s", session_id, job["slot"], text
                )
                continue
            # 空回复不推指针：推了的话被压掉的那几条从此谁也看不到
            if not text:
                continue
            if job["slot"] == PLAYER_SLOT:
                sess.summary = text
                sess.summarized_upto_id = job["last_id"]
            else:
                summaries[job["slot"]] = text
                pointers[job["slot"]] = job["last_id"]
            wrote = True
        if not wrote:
            return False
        # JSON 列要整份换掉才算脏数据，原地改 key 不会落库
        sess.thread_summaries = summaries
        sess.thread_upto = pointers
        await store.commit()
    return True


# ── ⑨ 外场简报：推时段时给大事记补一句「别处在发生什么」──────────────────

# 模型的输出上限。一两句话而已，给多了它就会开始编长篇
OFFSCREEN_MAX_TOKENS = 200
OFFSCREEN_LINES = 2

# 模型被要求「没什么可写就输出无」时可能给出的各种写法
_OFFSCREEN_NONE = {"无", "無", "none", "无。", "（无）", "(无)", "没有", "-"}


async def offscreen_brief(session_id: int, from_slot: str = "") -> list[str]:
    """推时段时补一条外场简报进大事记。返回写进去的那几行（已经带标签）。

    **这是整个 RPG 玩法里唯一一次「玩家没说话却调模型」**，所以它由模组上的
    offscreen_brief 开关管着，默认关：老模组按一下时钟仍然是零模型调用，
    文档和界面上那句承诺不会因为加了这个功能变成假话。

    只写玩家已经见过、此刻不在他身边的那些人——没见过的人进了大事记，等于
    让所有对话线都能随口提起一个玩家还不该知道的名字。名单为空时直接返回，
    连模型都不叫。

    整个函数不抛：简报没生成只是少一条传闻，时钟该走还是走。
    """
    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        if sess is None:
            return []
        module = await store.get(RpgModule, sess.module_id)
        if module is None or not module.offscreen_brief:
            return []
        npcs = list((await store.execute(
            select(RpgNpc).where(RpgNpc.module_id == module.id)
        )).scalars().all())
        met = {
            int(key) for key, state in (sess.npc_states or {}).items()
            if isinstance(state, dict) and state.get("met") and str(key).isdigit()
        }
        here = (sess.location or "").strip()
        others = [
            n for n in world_npcs(npcs)
            if n.id in met and npc_place(n, sess.slot, sess.npc_places) != here
        ]
        if not others:
            return []
        prompt = render(
            "rpg_offscreen.jinja2",
            day=max(1, sess.day or 1),
            from_slot=(from_slot or "").strip(),
            slot=(sess.slot or "").strip(),
            location=here,
            others=[
                {
                    "name": n.name,
                    "place": npc_place(n, sess.slot, sess.npc_places) or "行踪不明",
                    "persona": (n.persona or n.description or "").strip()[:60],
                    "notes": "；".join(
                        f"{k} {v}" for k, v in ((sess.npc_notes or {}).get(str(n.id)) or {}).items()
                    )[:60],
                }
                for n in others
            ],
            chronicle=chronicle_lines(sess)[-CHRONICLE_PROMPT_LINES:],
        )
        model, api_format = llm_client.get_agent_client("memory", module.fast_model_ref)
        stamp = f"第 {max(1, sess.day or 1)} 天" + (
            f"·{sess.slot}" if (sess.slot or "").strip() else ""
        )

    try:
        text = await llm_client.dispatch_chat_complete(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            api_format=api_format,
            temperature=0.8,
            max_tokens=OFFSCREEN_MAX_TOKENS,
        )
    except Exception:
        logger.exception("RPG 局 %s 外场简报生成失败", session_id)
        return []

    lines: list[str] = []
    for raw in (text or "").splitlines():
        # 去掉模型爱加的编号、项目符号和引号，同 suggest_actions
        line = re.sub(r"^\s*(?:[-*•]\s*)?(?:\d+\s*[.、)）]\s*)?", "", raw)
        line = line.strip().strip('"“”「」『』')
        if not line or line.lower() in _OFFSCREEN_NONE:
            continue
        # 单行硬夹一下：大事记是一行一条的硬事实，一条长文会常驻吃掉外场预算
        lines.append(f"{OFFSCREEN_TAG}{stamp} {line[:OFFSCREEN_CHARS]}")
        if len(lines) >= OFFSCREEN_LINES:
            break
    if not lines:
        return []

    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        if sess is None:
            return []
        push_chronicle(sess, lines)
        await store.commit()
    return lines


# ── ⑩ AI 调度：没被提到的角色自己过日子 ───────────────────────────────────

# 一次调用写完所有闲着的角色，所以上限比外场简报宽
ACTIVITY_MAX_TOKENS = 500
# 给模型看的「最近一段剧情」长度。只为对齐时间轴，不给它全文
ACTIVITY_RECENT_CHARS = 300


async def idle_npc_activities(
    session_id: int, engaged_ids: set[int],
) -> dict[str, str]:
    """给这一轮没被提到的、勾了「AI 调度」的角色各记一句「最近在做什么」。

    engaged_ids 是这一轮注入过设定的那批人（在场 + 被提到的），由调用方从
    build_rpg_messages 的 diag 里取。他们这一轮归叙事模型管，不该再被调度器
    另写一份——两边各写一遍，玩家下回见面时听到的会和自己刚经历的对不上。

    **一次调用写完所有人**，不是一人一次：勾了调度的角色可能有一屋子，
    一人一次的话玩家每轮要为 N 次调用付钱、等 N 次往返。

    有三件事是刻意不做的，写在这里免得后来改的人顺手加上：
    - **不改 location**。她在哪儿仍然只由作息表和常驻地点说了算。让模型顺手
      挪窝，玩家照着面板上的地点找过去就会扑空，地图的迷雾也无从跟着走。
    - **不写大事记**。这是「她一个人干了什么」，不是「已经传开的事」；写进去
      等于每条对话线上的所有人都知道了，chronicle 那条规矩禁的正是这个。
    - **不碰任何数值**。数值归引擎，模型只能提议改动，这条是全模式的地基。

    整个函数不抛：调度失败只是这一次没记上，下一轮照旧。
    """
    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        if sess is None:
            return {}
        module = await store.get(RpgModule, sess.module_id)
        if module is None:
            return {}
        npcs = list((await store.execute(
            select(RpgNpc).where(RpgNpc.module_id == module.id)
        )).scalars().all())
        # 主角模板不登场，没有「她最近在做什么」这回事
        idle = [n for n in world_npcs(npcs) if n.ai_scheduled and n.id not in engaged_ids]
        if not idle:
            return {}
        last = (await store.execute(
            select(RpgMessage)
            .where(RpgMessage.session_id == session_id, RpgMessage.role == "assistant")
            .order_by(RpgMessage.id.desc())
            .limit(1)
        )).scalars().first()
        prompt = render(
            "rpg_activity.jinja2",
            day=max(1, sess.day or 1),
            slot=(sess.slot or "").strip(),
            location=(sess.location or "").strip(),
            recent=((last.content or "")[-ACTIVITY_RECENT_CHARS:] if last else "") or "（故事刚开始）",
            npcs=[
                {
                    "name": n.name,
                    "place": npc_place(n, sess.slot, sess.npc_places) or "行踪不明",
                    "persona": (n.persona or n.description or "").strip()[:60],
                    "activity": npc_activity(sess, n.id),
                }
                for n in idle
            ],
        )
        model, api_format = llm_client.get_agent_client("memory", module.fast_model_ref)

    try:
        text = await llm_client.dispatch_chat_complete(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            api_format=api_format,
            temperature=0.9,
            max_tokens=ACTIVITY_MAX_TOKENS,
        )
    except Exception:
        logger.exception("RPG 局 %s 角色调度失败", session_id)
        return {}

    # 模型写的是名字，落库要的是 id。名字对不上就整行丢掉——**不报 warning**：
    # 这是玩家没要求过的后台动作，为它的瑕疵打断他一轮剧情不划算
    updates: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = re.sub(r"^\s*(?:[-*•]\s*)?(?:\d+\s*[.、)）]\s*)?", "", raw).strip()
        if not line:
            continue
        # 全角冒号是模板要求的写法，半角是模型自己换的，两种都收
        parts = re.split(r"[：:]", line, maxsplit=1)
        if len(parts) != 2:
            continue
        who = match_npc(parts[0].strip().strip('"“”「」『』'), idle)
        says = parts[1].strip().strip('"“”「」『』')
        if who is None or not says:
            continue
        # 「赫敏：无」也算没写。不挡住的话角色卡上会挂一行「最近：无」，
        # 而且它会一直留在那儿，模型下一轮还照着它编
        if says.lower() in _OFFSCREEN_NONE:
            continue
        updates[str(who.id)] = says
    if not updates:
        return {}

    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        if sess is None:
            return {}
        for npc_id, says in updates.items():
            apply_npc_activity(sess, int(npc_id), says)
        await store.commit()
    return updates


# ── 帮我想想：玩家主动要三条建议 ──────────────────────────────────────────

# 给模型的最近剧情条数。RPG 一轮就是一整段叙事，比酒馆的单条回复长得多，
# 所以条数比酒馆的 6 条略多一点，约合 4 个回合
SUGGEST_WINDOW = 8


async def suggest_actions(
    module: RpgModule, sess: RpgSession, history: list[RpgMessage],
    here_ids: set[int] | None,
) -> list[str]:
    """「帮我想想」：给出 3 条玩家接下来可以做的事。

    和每轮结算顺带产出的 suggestions 是两条独立的路：那条是被动等来的，
    这条是玩家按按钮要的。返回空列表表示没能生成，前端提示一下就好。

    history 是全部历史，同 build_rpg_messages——两个调用点必须看同一份东西，
    否则建议会提「问问她后山的事」这种和眼前无关的选项（那正是 §30 当初把
    scene_history 一起接进来的理由）。`here_ids` 同理：那边按在场名单筛窗口，
    这边不筛的话，会提「接着问她二十年前那件事」——而她根本不在这间屋里。
    """
    recent = history_window(module, sess, history, here_ids)[-SUGGEST_WINDOW:]
    if not recent:
        return []

    transcript = "\n".join(
        f"{'你' if m.role == 'user' else 'GM'}：{m.content}" for m in recent
    )
    prompt = render(
        "rpg_suggest.jinja2",
        char_name=(sess.char_name or "").strip() or DEFAULT_CHAR_NAME,
        location=sess.location or "",
        summary=truncate_to_token_budget(sess.summary or "", SUMMARY_TOKEN_BUDGET),
        transcript=transcript,
    )
    model, api_format = llm_client.get_agent_client("memory", module.fast_model_ref)
    text = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.95,
        max_tokens=600,
    )

    lines = []
    for raw in (text or "").splitlines():
        # 模型时常自作主张加编号或引号，去掉再用
        # 编号必须带分隔符才剥，否则 "3天后再来" 会被吃掉开头的数字
        line = re.sub(
            r"^\s*(?:[-*•]\s*)?(?:\d+\s*[.、)）]\s*)?", "", raw
        ).strip().strip('"“”「」')
        if line:
            lines.append(line)
    return lines[:3]


# ── 一整轮 ────────────────────────────────────────────────────────────────

async def run_turn(
    session_id: int,
    user_message_id: int,
    content: str,
    attr_override: str = "",
    action_id: int | None = None,
    item_name: str = "",
    skill_name: str = "",
    move_to: str = "",
    target_npc: str = "",
    present: list[int] | None = None,
    place: str = "",
    mode: str = GROUP_MODE,
    private_with: int | None = None,
) -> AsyncIterator[tuple[str, object]]:
    """跑完一轮，yield (事件名, 数据)，由路由编码成 SSE。

    玩家那条消息已经由路由落库了（网络断了也得留下）。action_id / item_name /
    move_to 包括按钮移动和自由输入中明确的移动指令；其余自由打字走 AI 结算。

    present / place 是路由在写玩家那条消息时快照下来的在场名单和地点，原样
    转给 assistant 那条。引擎移动后会在叙事前同步更新两行的地点和名单，
    叙事之后的 AI 结算不会再改变这份快照。

    mode / private_with 是玩家选的对话模式，原样转给 build_rpg_messages。路由
    那边已经用同一个 turn_present 把 present 算过一遍了，两处必须同源。
    """
    facts: list[str] = []
    engine_note = ""
    fixed_location = None
    async with AsyncSessionLocal() as store:
        sess0 = await store.get(RpgSession, session_id)
        engine_before = rpg_settlement.capture(sess0)
        # 冷却在这里统一递减：每一轮都要减，自由打字那几轮也算时间过去了。
        # 放在引擎结算之前，这一轮刚压上的冷却不会被自己减掉
        tick_cooldowns(sess0)
        # 纯对话记一条。判据和下面那个 if 互为反面：点了动作/道具/技能/移动的
        # 那几轮走 spend_slot_action 记「行动」，剩下的才是「聊天」。
        # 记在这里而不是 _resolve_engine 里，因为那个函数只在引擎路径被调用
        if not (action_id or item_name or skill_name or move_to):
            note_slot_chat(sess0)
        await store.commit()
    if action_id or item_name or skill_name or move_to:
        try:
            facts, warns, state = await _resolve_engine(
                session_id, action_id, item_name, move_to, target_npc, skill_name
            )
            for warn in warns:
                yield "warning", warn
            if facts:
                engine_note = "；".join(facts)
                if move_to:
                    fixed_location = state["location"]
                yield "state", state
        except Exception:
            logger.exception("RPG 局 %s 引擎结算失败", session_id)
            yield "warning", "这个动作没能结算，本轮按自由行动处理了"

    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        module = await store.get(RpgModule, sess.module_id)
        # 出发时站在你身边的那份名单。下面那个 if 会用**移动之后**重算的一份
        # 把 present 覆盖掉（那是对的：两条消息行要记的是你落脚之后谁在跟前），
        # 但结算要的是这一份。它的用处是问模型「谁真的跟着换了地方」——
        # 拿移动后那份去问，跟着你出门的人已经从名单里消失了，模型连给他写个
        # 新位置的机会都没有，人就此永远停在作息表/常驻地点上
        origin_present = list(present or [])
        if fixed_location is not None and sess.location != place:
            npcs = list((await store.execute(
                select(RpgNpc).where(RpgNpc.module_id == module.id)
            )).scalars().all())
            present = [npc.id for npc in turn_present(npcs, sess, mode, private_with)]
            place = sess.location or ""
            user_row = await store.get(RpgMessage, user_message_id)
            if user_row is not None:
                user_row.location = place
                user_row.present = present
            await store.commit()
        last = (await store.execute(
            select(RpgMessage)
            .where(
                RpgMessage.session_id == session_id,
                RpgMessage.role == "assistant",
            )
            .order_by(RpgMessage.id.desc())
            .limit(1)
        )).scalars().first()
        recent = (last.content or "")[-RECENT_CHARS:] if last else ""

    # 先发一次 meta 把 user_message_id 送出去：模型没配好时也得让前端拿到它，
    # 否则那条消息已经落库却编辑不了。诊断信息等上下文拼完再补发一次
    yield "meta", {"user_message_id": user_message_id}

    judgement = None
    aux_in = aux_out = 0
    # 引擎已经算准了的行动不再判定：点「奖励」按钮不该有失手的余地，
    # 数字都是作者写死的
    if module.check_mode != "never" and not facts:
        # 前端据此显示「裁决中…」。玩家自己指定数值那条是零延迟的，也发，
        # 一闪而过没关系，反正下一条 stage 会立刻盖掉
        yield "stage", "adjudicating"
        stats = sess.stats or {}
        if attr_override and attr_override in stats:
            # 玩家自己指定了数值：零延迟零成本，还给了掌控感
            judgement = {
                "need_check": True, "attr": attr_override, "band": DEFAULT_BAND,
                "intent": content, "reason": "玩家指定",
            }
        else:
            try:
                judgement, aux_in, aux_out = await adjudicate(module, sess, content, recent)
            except Exception as e:
                # 降级为「无需判定」，绝不阻断——聊天本来就不用判定，
                # 为一次裁决失败让整轮发不出去才是真的坏
                logger.warning("RPG 局 %s 裁决失败，本轮按纯叙事处理: %s", session_id, e)
                yield "warning", "这一轮没能判定，先按纯叙事写了"

        if module.check_mode == "always" and judgement and not judgement["need_check"]:
            judgement["need_check"] = True
            judgement["attr"] = judgement["attr"] or _fallback_attr(module, stats)

    if judgement:
        if judgement["need_check"] and judgement["attr"]:
            judgement = apply_roll(module, sess, judgement)
        else:
            # 没有一项数值可判（模组还没定义），退回纯叙事
            judgement["need_check"] = False
        yield "adjudicate", {
            "need_check": judgement["need_check"],
            "attr": judgement["attr"],
            "band": judgement["band"],
            "intent": judgement["intent"],
            "reason": judgement["reason"],
        }
        if judgement["need_check"]:
            yield "roll", {
                "rate": judgement["rate"], "dice": judgement["dice"],
                "outcome": judgement["outcome"], "attr": judgement["attr"],
            }
        try:
            await _store_roll(session_id, user_message_id, judgement, aux_in, aux_out)
        except Exception:
            # 判定没存下不该拦住叙事：玩家已经看到结果了，这一轮照常写完
            logger.exception("RPG 局 %s 判定落库失败", session_id)

    async with AsyncSessionLocal() as store:
        fresh_sess = await store.get(RpgSession, session_id)
        fresh_module = await store.get(RpgModule, fresh_sess.module_id)
        history = list((await store.execute(
            select(RpgMessage)
            .where(
                RpgMessage.session_id == session_id,
                # 只排掉刚落库的这句玩家输入，它由 new_input 单独传
                RpgMessage.id != user_message_id,
            )
            .order_by(RpgMessage.id)
        )).scalars().all())
        # 整份历史原样交给上下文，不切。原先这里切两半（这一条线的 + 场面线的），
        # 那是为了「角色的历史里不该有别人的私聊」——而她同时也就看不到开场白
        # 和你刚才做过什么，§30 又得把场面线借回去。线拆了之后这一段没有分支
        messages, diag = await build_rpg_messages(
            store, fresh_module, fresh_sess, history, content, judgement, facts,
            mode, private_with,
        )
        # 外貌已经随这次上下文发出去了，就地记一笔，下一轮不再重复发。
        # 放在开流之前而不是之后：叙事失败也算见过，模型确实已经拿到过那段描写。
        # 只认 npcs_here：被提到一句的人这一轮也拿到了设定，但玩家并没见到他，
        # 记成见过会让他的外貌永远等不到该出现的那一次
        mark_met(fresh_sess, [n["id"] for n in diag["npcs_here"]])
        settlement_seed = rpg_settlement.seed_settlement(
            fresh_sess, user_message_id, engine_before, engine_note, fixed_location,
            mode, private_with, origin_present,
        )
        settlement_seed["outcome_label"] = OUTCOME_LABELS.get((judgement or {}).get("outcome") or "", "")
        await store.commit()
    # 出了 with 块才开流：写锁不跨 LLM 调用
    yield "meta", diag
    # 上下文已经拼好，正要调叙述模型。这一条发出去之后到第一个 token 之间
    # 就是最后一段静默期，前端据此显示「组织线索中…」
    yield "stage", "building"

    # 模型解析放这里：模型配错时 resolve_model_ref 抛 ValueError，
    # 在生成器内抛才能变成一条 error 事件，放外面会变成 500 白屏
    model, api_format = llm_client.get_agent_client("writer", fresh_module.model_ref)

    buf: list[str] = []
    in_tok = out_tok = 0
    try:
        async for chunk in llm_client.dispatch_chat_stream_with_usage(
            messages=messages,
            model=model,
            api_format=api_format,
            temperature=fresh_module.temperature,
            max_tokens=fresh_module.max_tokens,
        ):
            if isinstance(chunk, tuple):
                _, in_tok, out_tok = chunk
            elif isinstance(chunk, dict):
                if "warning" in chunk:
                    yield "warning", chunk["warning"]
            else:
                buf.append(chunk)
                yield "token", chunk
    except (asyncio.CancelledError, GeneratorExit):
        # 玩家按了停止：吐出来的半段也要留下，否则刷新页面就没了。
        # 这里不能 await 落库——本 task 已被取消，下一个 await 会再次抛出。
        # state_delta 留 null，前端给「补结算」按钮
        reply = "".join(buf).strip()
        if reply:
            _spawn_detached(_store_reply(
                session_id, reply, in_tok, out_tok, present, place, settlement_seed
            ))
        raise

    reply = "".join(buf).strip()
    message_id = await _store_reply(
        session_id, reply, in_tok, out_tok, present, place, settlement_seed
    )

    if reply:
        # 字已经吐完了，接下来是一次静默的结算调用。不发这条的话，前端会在
        # 正文写完到数值跳变之间干等一段，看着像卡住了
        yield "stage", "settling"
        label = OUTCOME_LABELS.get((judgement or {}).get("outcome") or "", "")
        try:
            settlement_task = asyncio.create_task(_settle(
                session_id, message_id, reply, label, engine_note, fixed_location
            ))
            _detached_tasks.add(settlement_task)
            settlement_task.add_done_callback(_detached_tasks.discard)
            result = await asyncio.shield(settlement_task)
            for warn in result["warnings"]:
                yield "warning", warn
            yield "state", result["state"]
            yield "settlement", {"message_id": message_id, "report": result["settlement"]}
            if result["suggestions"]:
                yield "suggestions", result["suggestions"]
            if result["discoveries"]:
                yield "discoveries", result["discoveries"]
            if result.get("task_proposals"):
                yield "task_proposals", result["task_proposals"]
            # 待确认的新道具。同 discoveries 单独一条：它不在 state 里（不是游戏
            # 状态），不发的话玩家要等整页重新拉一次才看到「新获取」那一块
            if result.get("item_claims"):
                yield "item_claims", result["item_claims"]
            # outcome_consistent 为假时的那句话已经在 result["warnings"] 里了
            # （settle_turn 自己 append 的），上面那圈 yield 已经发过一遍。这里
            # 原先又发一条，玩家会连着看到两个意思相同的 toast
            #
            # 单独一个事件而不是复用 warning：warning 在前端是 toast，一闪而过，
            # 而这一条要留在界面上把「结束这个时段」那颗按钮点亮
            if result.get("scene_wrapped"):
                hint = "这一幕看着收尾了"
                # free_costs_slot 打开时这条提示不再只是提示：一幕演完就吃掉
                # 一格行动，攒满 slot_budget 由 spend_slot_action 自己翻页。
                # 只算自由打字那几轮——点了动作/道具/技能/移动的那几轮
                # _resolve_engine 已经记过一格了，这里再记就是一轮扣两格。
                #
                # **必须放在结算之后**，因为 scene_wrapped 就是结算算出来的，
                # 这就撞上了 :362 那条「推格子不能在结算之后」的约束：结算
                # 返回的 state 会把 day/slot 钉回结算开始时的快照
                # （rpg_settlement.py:1271）。所以不去改那份 state，而是自己
                # 开个事务推完、再单独 yield 一条新的 state 盖掉它——前端的
                # state 处理就是 setQueryData，后发的赢。
                is_free = not (action_id or item_name or skill_name or move_to)
                if is_free and fresh_module.free_costs_slot:
                    try:
                        # 从路由那边借的。放函数里 import 是因为 routes.rpg
                        # 自己就 import 了本模块，模块级会成环
                        from app.api.routes.rpg import _prune_auto_saves, _take_save
                        async with AsyncSessionLocal() as store:
                            sess2 = await store.get(RpgSession, session_id)
                            module2 = await store.get(RpgModule, sess2.module_id)
                            # 推完时钟这条剧情就重结算不了了（:1059 的冲突
                            # 守卫），所以先留一张能倒回来的档。它读回去只
                            # 回滚状态、不删消息，正文还在
                            await _take_save(store, sess2, "auto", "")
                            await _prune_auto_saves(store, session_id)
                            slot_facts = spend_slot_action(module2, sess2)
                            warns2 = check_zero(module2, sess2) + check_full(module2, sess2)
                            sess2.updated_at = datetime.utcnow()
                            await store.commit()
                            for warn in warns2:
                                yield "warning", warn
                            yield "state", _state_payload(sess2)
                        if slot_facts:
                            hint = "；".join([hint] + slot_facts)
                    except Exception:
                        logger.exception("RPG 局 %s 收尾推时段失败", session_id)
                yield "slot_hint", hint
            aux_in += result["aux_input_tokens"]
            aux_out += result["aux_output_tokens"]
        except Exception:
            # 结算失败只是数值没动，剧情已经写好了。前端据 state_delta 为 null
            # 给「补结算」按钮
            logger.exception("RPG 局 %s 结算失败", session_id)
            yield "warning", "这一轮的状态变化没能结算，可以稍后手动补"
            async with AsyncSessionLocal() as store:
                failed_row = await store.get(RpgMessage, message_id)
                failed_report = rpg_settlement.public_report(failed_row.settlement) if failed_row else None
            yield "settlement", {"message_id": message_id, "report": failed_report}

    # 压缩排在结算之后：这一轮的消息已经落库，它也该参与计数。
    # 失败不吭声——玩家没要求过这件事，报错只会让他以为这一轮出了问题
    try:
        await _maybe_summarize(session_id)
    except Exception:
        logger.exception("RPG 局 %s 概要生成失败，上下文退化为纯截断", session_id)

    # AI 调度排在最后：它要知道这一轮提到了谁，那是 build_rpg_messages 算的。
    # **这是唯一一次「玩家说完话了还在调模型」**，而且是每轮都调，所以它必须
    # 排在 done 之前——done 之后前端就不再收了，玩家的侧栏会一直停在旧状态。
    # 没勾任何角色、或者勾了的都在场，这一次调用根本不发生
    try:
        # diag 是这一轮注入过设定的人（在场 + 被提到的）。他们归叙事模型管，
        # 调度器另写一份会和玩家刚经历的剧情对不上
        # npcs_onstage 是「在场 + 被提到」，比 npcs_here 宽：被提到的人这一轮
        # 也拿到了设定，调度器再替他们编一份「今天在干什么」会和刚写的对不上。
        # 原先这里还要单独补一个 thread_id（线主），线没了——线主的定义本来就是
        # 「你正在跟她说话的那个」，而她已经在这份名单里了
        engaged = {int(n["id"]) for n in diag.get("npcs_onstage") or []}
        await idle_npc_activities(session_id, engaged)
    except Exception:
        logger.exception("RPG 局 %s 角色调度失败", session_id)

    yield "done", {
        "message_id": message_id,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "aux_input_tokens": aux_in,
        "aux_output_tokens": aux_out,
    }
