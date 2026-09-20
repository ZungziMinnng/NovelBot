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
import random
import re
from dataclasses import replace
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
from app.services.context_budget import estimate_tokens, truncate_to_token_budget
from app.services.llm_json import call_json
from app.services.rpg_context import (
    DEFAULT_CHAR_NAME,
    GROUP_MODE,
    PLAYER_SLOT,
    PRIVATE_MODE,
    SUMMARY_TOKEN_BUDGET,
    build_rpg_messages,
    history_window,
    message_slots,
    named_npcs,
    npc_place,
    present_ids,
    ref_roster,
    resolve_refs,
    slot_summary,
    slot_upto,
    slot_window,
    suggest_blocks,
    turn_present,
    world_npcs,
)
from app.services.rpg_dice import DEFAULT_BAND, OUTCOME_LABELS, normalize_band, resolve_rate, roll
from app.services.rpg_prompts import render
from app.services.rpg_operation import retain_task
from app.services.rpg_state import (
    OFFSCREEN_CHARS,
    OFFSCREEN_TAG,
    advance_slot,
    apply_inventory,
    apply_npc_activity,
    apply_npc_followers,
    apply_npc_place,
    apply_relations,
    apply_stats,
    check_condition,
    check_full,
    check_zero,
    effect_cost_reason,
    chronicle_lines,
    for_check_stats,
    mark_met,
    match_npc,
    match_place,
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
from app.services.rpg_suggestions import (
    MAX_FREE,
    MAX_STRUCTURED,
    SuggestSources,
    clean_suggestions,
    parse_tagged_lines,
    split_quota,
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
    task = retain_task(asyncio.create_task(coro))
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
        # 被改写的外貌，同理：这一轮结算把它改掉了，角色卡上那一段要当场变
        "npc_appearance": sess.npc_appearance or {},
        # AI 调度给不在场的人记的「最近在做什么」，同理
        "npc_activities": sess.npc_activities or {},
        # 这一轮记下的经历和关系转折：角色档案的「经历」那一页要当场长出来，
        # 不带的话玩家点进去看到的还是上一轮的样子
        "npc_history": sess.npc_history or {},
        "npc_milestones": sess.npc_milestones or [],
        # 剧情把谁挪到哪儿了：带回去面板才认得出「她此刻就在你面前」，
        # 不带的话要等整页重新拉一次才动
        "npc_places": sess.npc_places or {},
        # 跟着你走的人：带回去侧栏才显示得出「跟着你」那个标记，
        # 不带的话要等整页重新拉一次才动
        "npc_followers": sess.npc_followers or [],
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


def _effect_facts(label: str, effects: dict, before: dict, after: dict) -> list[str]:
    facts = []
    for name in dict.fromkeys(str(key).strip() for key in (effects or {})):
        if name not in after:
            facts.append(f"{label}：{name}未生效（未定义此数值）")
            continue
        previous = int(before.get(name, 0))
        current = int(after[name])
        amount = current - previous
        change = f"{amount:+d}" if amount else "未变化"
        facts.append(f"{label}：{name}{change}（{previous} → {current}）")
    return facts


# ── ② 引擎结算：有定义的东西，数字是死的 ──────────────────────────────────

def _use_item(module: RpgModule, sess: RpgSession, item: RpgItem, quantity: int = 1) -> tuple[list[str], list[str]]:
    facts, warnings = [], []
    quantity = max(1, int(quantity or 1))
    effects = {name: int(amount) * quantity for name, amount in (item.effects or {}).items()}
    before = dict(sess.stats or {})
    if item.effects:
        warnings.extend(apply_stats(module, sess, effects))
    if item.consumable:
        warnings.extend(apply_inventory(sess, [{"name": item.name, "qty": -quantity}]))
    facts.append(
        f"你用掉了「{item.name}」" if item.consumable else f"你用了「{item.name}」"
    )
    facts.extend(_effect_facts("道具效果", effects, before, sess.stats or {}))
    return facts, warnings


def _skill_gate(sess: RpgSession, skill: RpgSkill, npcs: list[RpgNpc], module=None) -> str:
    """这一招发不发得出来。空串 = 发得出来。理由同 _action_gate：行动预算
    要问同一句，而两处各判一遍迟早会漂移。"""
    ok, why = check_condition(skill.requires, sess, npcs)
    if not ok:
        return f"{why}，没能发出来"
    return effect_cost_reason(sess, skill.effects, getattr(module, "stat_defs", None))


def _use_skill(
    module: RpgModule, sess: RpgSession, skill: RpgSkill, npcs: list[RpgNpc]
) -> tuple[list[str], list[str]]:
    """施展一招。条件不过就只留一句事实，数值不动、冷却也不压上。"""
    blocked = _skill_gate(sess, skill, npcs, module)
    if blocked:
        return [f"你想施展「{skill.name}」，但{blocked}"], []
    facts, warnings = [], []
    before = dict(sess.stats or {})
    if skill.effects:
        warnings.extend(apply_stats(module, sess, skill.effects))
    if skill.cooldown > 0:
        # +1 是因为冷却在**每回合开头**统一递减（见 run_turn），包括紧接着的
        # 下一回合。直接存 cooldown 的话「冷却 1」下一回合就减没了，等于没歇
        set_cooldown(sess, skill.name, skill.cooldown + 1)
    facts.append(f"你施展了「{skill.name}」")
    facts.extend(_effect_facts("技能效果", skill.effects, before, sess.stats or {}))
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


def _action_gate(sess: RpgSession, action: RpgAction, target: RpgNpc | None, npcs=(), module=None) -> str:
    """这个动作做不做得成。空串 = 做得成，否则是给玩家看的那半句原因。

    从 _run_action 里抽出来的，因为行动预算也要问同一句：被拦下的动作只留
    一句解释、一个数值都不动，不该吃掉作者给这个时段安排的行动位。抽出来
    而不是各判一遍，是为了两边不会各自漂移。
    """
    candidates = ([target] if target else []) if action.needs_target else npcs
    ok, why = check_condition(action.requires, sess, candidates)
    if not ok:
        return f"{why}，没能做成"
    # 地点限定和 requires 一样是「做不做得成」，所以也在动数值之前拦。
    # 按名字比，理由见 RpgAction.at_location 的注释
    need_place = (action.at_location or "").strip()
    if need_place and norm_name(sess.location or "") != norm_name(need_place):
        return f"这得在{need_place}才行"
    return effect_cost_reason(sess, action.effects, getattr(module, "stat_defs", None))


def _run_action(
    module: RpgModule, sess: RpgSession, action: RpgAction, target: RpgNpc | None, npcs=(),
) -> tuple[list[str], list[str]]:
    facts, warnings = [], []
    blocked = _action_gate(sess, action, target, npcs, module)
    if blocked:
        return [f"你本想{action.name}，但{blocked}"], []
    stats_before = dict(sess.stats or {})
    relations_before = dict((sess.npc_states or {}).get(str(target.id)) or {}) if target else {}
    if action.effects:
        warnings.extend(apply_stats(module, sess, action.effects))
    if action.relation_effects and target is not None:
        warnings.extend(apply_relations(module, sess, target.id, action.relation_effects))
    facts.append((action.prompt_hint or "").strip() or f"你{action.name}")
    if action.summons_target and target is not None:
        here = (sess.location or "").strip()
        # 跟随名单要一起传：已经在跟着你的人本来就站在你面前，不传的话
        # 这里会按作息表算出「她还在别处」，白写一条 npc_places 加一句
        # 「她赶到了X」——而画面里她一直就在
        if here and norm_name(npc_place(
            target, sess.slot, sess.npc_places, sess.npc_followers, here,
        )) != norm_name(here):
            apply_npc_place(sess, target.id, here)
            facts.append(f"{target.name}赶到了{here}")
    facts.extend(_effect_facts("行动效果", action.effects, stats_before, sess.stats or {}))
    if target is not None:
        relations_after = (sess.npc_states or {}).get(str(target.id)) or {}
        facts.extend(_effect_facts(
            f"{target.name}对你的关系", action.relation_effects, relations_before, relations_after,
        ))
    # 推时段放在最后：advance_slot 跨天时会触发 reset_daily 把数值refill 回上限，
    # 排在 apply_stats 之前的话这个动作自己的消耗会被当天的重置抹掉
    if action.cost_slot:
        facts += advance_slot(module, sess, npcs)
    return facts, warnings


async def _resolve_engine(
    session_id: int, action_id: int | None, item_name: str, move_to: str, target_npc: str,
    # 注解写成字符串：Company 和它的识别规则住在下面「带谁走 / 派谁去」那一段，
    # 这里只是收一个已经算好的结果
    skill_name: str = "", company: "Company | None" = None, item_qty: int = 1,
    engine_effects: dict | None = None,
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
    spent_slot = False
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
                quantity = max(1, int(item_qty or 1)) if item.consumable else 1
                owned = next((row for row in (sess.inventory or [])
                              if norm_name(row.get("name")) == norm_name(item.name)), None)
                available = max(0, int((owned or {}).get("qty", 0) or 0))
                cost_reason = effect_cost_reason(sess, {
                    name: int(amount) * quantity for name, amount in (item.effects or {}).items()
                }, module.stat_defs)
                if available < (quantity if item.consumable else 1):
                    facts.append(f"背包里的「{item.name}」数量不足，未使用")
                elif cost_reason:
                    facts.append(f"未使用「{item.name}」：{cost_reason}")
                else:
                    if engine_effects is not None:
                        engine_effects.setdefault("stats", []).extend(str(name).strip() for name in (item.effects or {}))
                    got, warn = _use_item(module, sess, item, quantity)
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
            learned = any(norm_name(row.get("name")) == norm_name(skill_name)
                          for row in (sess.skills or []) if isinstance(row, dict))
            if skill is None:
                warnings.append(f"模组里没有「{skill_name}」这个技能")
            elif not learned:
                facts.append(f"你尚未学会「{skill.name}」，不能施展")
            elif not skill.usable or skill.category == "被动":
                facts.append(f"「{skill.name}」不是能主动施展的本事")
            elif left > 0:
                facts.append(f"「{skill.name}」还得歇 {left} 回合才能再用")
            else:
                # 先问一遍拦不拦：拦下来的那一句「没能发出来」也是事实句，
                # 但一个数值都没动。_use_skill 里同一个判据说了算，这里只是
                # 拿它决定要不要吃掉一格行动
                allowed = not _skill_gate(sess, skill, npcs, module)
                if allowed and engine_effects is not None:
                    engine_effects.setdefault("stats", []).extend(str(name).strip() for name in (skill.effects or {}))
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
            elif norm_name(sess.location or "") == norm_name(target.name):
                # 已经在的地方不该再走一遍 _move：那会写下「你离开灵药园柴房，
                # 来到了灵药园柴房」，还顺手把大事记上一条移动覆盖掉（note_move
                # 是合并写的）。同 move_by_name 里那道闸，从前只有按钮那条路有，
                # 自由输入这条路（尤其认出简称之后，「人在柴房说回柴房」）没有
                pass
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
                elif action.needs_target and not action.target_anywhere and who.id not in present_ids(
                    npcs, sess.location, sess.slot, sess.npc_places, sess.npc_followers,
                ):
                    facts.append(f"{who.name}不在跟前，未执行「{action.name}」")
                else:
                    allowed = not _action_gate(sess, action, who, npcs, module)
                    if allowed and engine_effects is not None:
                        engine_effects.setdefault("stats", []).extend(str(name).strip() for name in (action.effects or {}))
                        if who is not None:
                            engine_effects.setdefault("relations", {})[str(who.id)] = [
                                str(name).strip() for name in (action.relation_effects or {})
                            ]
                    got, warn = _run_action(module, sess, action, who, npcs)
                    facts += got
                    warnings += warn
                    moved = moved or allowed
                    spent_slot = allowed and action.cost_slot

        if company:
            facts += _apply_company(sess, npcs, company)
            # 派遣吃一格行动：真的在这个世界里支走了一个人，和「召见」
            # 「走过去」同级。跟随和解除不吃——跟着走或散开不占这个时段的时间
            moved = moved or bool(company.dispatch)

        if facts:
            if moved and not spent_slot:
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
                facts += spend_slot_action(module, sess, npcs)
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

    before = (sess.location or "").strip()
    facts = _move(sess, target, npcs)
    # 记一笔「上一幕在哪」留给下一轮的 prompt。这条路零 LLM、不产生任何消息，
    # 不记的话这次离开在历史里一个字都不留，模型接着离开时那一幕往下写
    # （见 rpg_context.scene_break_block）。**只有这条路记**：走一整轮的移动
    # 自己就产出了「你走过去」那段正文，不需要再贴一块提示
    #
    # 按「地点真的变了」判，不能拿 facts 非空当判据：被 enter_requires 拦下时
    # _move 同样返回一句话，人却还在原地
    if (
        # 开局还没落地时没有「上一幕在哪」，编不出来就别编（同 advance_slot
        # 在没有时钟时一个字都不留）
        before
        and norm_name(sess.location or "") != norm_name(before)
        # 已经有断场点就不覆盖：连着瞬移 A→B→C 中间一句话都没说，上一幕仍是 A。
        # 同 advance_slot 里那道守卫
        and not (sess.scene_break_from or "").strip()
    ):
        sess.scene_break_from = before
    return facts[0] if facts else ""


_MOVE_VERBS = "前往|前去|去往|走到|走向|走进|进入|回到|返回|回|移动到|赶往|来到|去"
_MOVE_VERB_RE = re.compile(_MOVE_VERBS)
# 动词**前面**出现这些字，这句就不是「我现在就动身」：否定、推迟、主语不是玩家。
# **只看动词紧邻的那几个字**（_DENY_WINDOW），不是整句前缀——从前拿整句前缀按
# 单字拦，「我想再去酒馆」的「再」、「我不累，去酒馆」的「不」隔得老远也误伤。
# 「再」已从表里拿掉：它本来是想拦「一句话串了两个目的地」，那件事现在由
# movement_target 里「前面已经出现过移动动词」那条判据接管，比按字拦准得多
# 「看见 / 听说 / 知道」这类感知和转述也并进这张表，**不**另起一张并列的：
# 它们判的是同一件事——动词紧邻这几个字，这句就不是玩家在动身，两处各写一份
# 迟早会漂成「这张拦、那张不拦」。「我看见赫敏去客栈」里赫敏是个具名角色，
# 不在上面那串代词里，不拦这句就会被认成玩家要去客栈——人被平白挪走。
# 表里最长的词两个字，_DENY_WINDOW 的 4 个字够把它们整个包进来。
# **刻意不收裸「说」**：单字太常见，「跟掌柜说一声再去酒馆」这种真移动会被误杀
_MOVE_DENY = re.compile(
    r"[不别莫没未他她它你并等]|懒得|然后|"
    r"看见|看到|瞧见|听说|听见|得知|知道|告诉|提到|以为|觉得"
)
_DENY_WINDOW = 4
# 书面腔的移动动词。真人支使人说的是「你去客栈」，不会说「你前往客栈」——
# 「你前往织云阁。」恰恰是移动按钮替玩家写进正文的那句引擎文案（前端 moveByTurn）。
# 玩家手打或重发这一句，说的是**自己**要走，所以这个形状两头都要管：
# ① movement_target 里认成玩家移动。句首那个「你」本来会被 _MOVE_DENY 当成
#    「在跟别人说话」而整句作废，于是人留在原地，GM 却照着写了一段已经到了的
#    剧情，结算只能报「剧情地点与引擎地点冲突」
# ② _parse_send 里**不**认成命令。私聊里跟前只有对面那一个人，代词主语必然
#    解析成功，不拦的话这句会把正在对话的那个人支使走，看着就像 NPC 自己跟了过去
_ENGINE_MOVE_VERBS = ("前往", "前去", "去往", "移动到", "赶往")
# 只认最干净的那个形状：句首、书面动词、后面干干净净一个地名，别的什么都没有。
# 多一个尾巴（「你前往客栈等我」「你前往客栈吧」）就是在支使人，归 _parse_send
_ENGINE_MOVE = re.compile(r"^你(?:" + "|".join(_ENGINE_MOVE_VERBS) + r")(.{1,12})$")
# 「要不…吧 / 不如… / 要么… / 还是…」是**提议**，不是否定。先把这个头剥掉再判
# 否定，否则「要不我们去酒馆吧」这句最常见的提议句式永远命不中。**必须带上要/
# 那才剥**：裸「不」一剥，「我不去酒馆」就变成「我去酒馆」了
_SUGGEST = re.compile(r"^(?:要不|不然|不如|要么|还是)")
# 地点名**后面**还允许跟什么：到了那儿要干的事。不在这张表里的一律当成
# 「这其实是个更长的地名」而不认——「去灵药园后院」里并没有灵药园后院这个登记地点，
# 认成灵药园就是把人送错地方。
#
# 这张表是**白名单不是黑名单**，所以漏的错法是「不认」（原地不动，交给 AI），
# 不是「认错」。往表里加词的风险全在于**方位/建筑类的续名**（前后左右、楼院房厅
# 堂间）——只要加进去的都是动词，那些续名就永远撞不上
_MOVE_TAIL = re.compile(
    r"^(?:看看|看一看|看一眼|瞧瞧|瞧一眼|转转|转一圈|逛逛|走走|"
    r"歇歇|歇会儿|休息|歇息|睡觉|睡一觉|吃饭|喝酒|打听|找|待着|等着|"
    r"上班|工作|办公|开会|值班|打卡|"
    r"买|购|采购|卖|采|摘|挖|钓|砍|淘|换|还|借|取|拿|领|交|送|要|"
    r"吃|喝|聊|谈|问|说|见|探|玩|练|学|读|写|查|调|修|做|办|帮|"
    r"坐|住|洗|泡|看|听|"
    r"一趟|一下|吧|了)")


# 地点简称至少要有两个字才敢认。同 rpg_state.match_npc 的 _MIN_PARTIAL：
# 一个字的「园」「房」能撞上一堆地方
_MIN_PLACE_PART = 2


def _place_hits(head: str, names: dict[str, str]) -> set[str]:
    """`head`（动词后面那截，或玩家光打的那句）能对上哪些登记地点。

    全名优先，全名对不上才认**尾段简称**——模组里登记的是「灵药园柴房」，
    玩家嘴上说的是「柴房」。地名没有间隔号，所以对齐**只认后缀一头**：
    前缀那头正是 _MOVE_TAIL 要防的「去灵药园后院」，认成「灵药园」就把人送错。

    和 match_npc 同一条纪律：认不出、或者对上两个（模组里有两个「柴房」）
    都当没对上，由调用方整句交回 AI。
    """
    hits = set()
    for key, name in names.items():
        if not key:
            continue
        if head.startswith(key) and (head == key or _MOVE_TAIL.search(head[len(key):])):
            hits.add(name)
            continue
        for cut in range(1, len(key) - _MIN_PLACE_PART + 1):
            part = key[cut:]
            if head.startswith(part) and (head == part or _MOVE_TAIL.search(head[len(part):])):
                hits.add(name)
                break
    return hits


def movement_target(content: str, locations: list[RpgLocation]) -> str:
    """自由输入里那句「我要去 XX」。命中才走引擎移动，否则整句交给 AI 结算。

    从前这里是 `re.fullmatch`：整句必须**恰好**是「去XX」，多一个「看看」就
    失配，于是玩家写「我要去酒馆看看」地点根本不会变。现在改成在句子里找移动
    动词，再拿动词后面那截来对登记地点名。

    宽的只是前后文。动词后面那截要么正好是一个登记地点名，要么是「地点名 +
    一件到了那儿要干的事」（_MOVE_TAIL）；地点名本身可以是**尾段简称**
    （登记的是「灵药园柴房」，玩家说「柴房」，见 _place_hits）。不敢猜的一律
    返回空串，回到原来那条 AI 结算的路上——猜错的代价是把人凭空挪走，比不猜大。

    前面那截（谁在说、否定没有）只看**动词紧邻的几个字**，见 _MOVE_DENY。
    而「一句里两个目的地」不再按「再」这个字拦，改成认**这句里前面已经出现过
    移动动词**：这样「先回客栈，再去酒馆」照样整句交回 AI，但「我想再去酒馆」
    这种只有一个目的地的说法能正常动身。
    """
    text = content.strip().rstrip("。！!").strip()
    # 问句是在打听，不是在动身
    if re.search(r"[?？]|吗$", text):
        return ""
    names = {norm_name(location.name): location.name for location in locations if location.name}
    # 移动按钮替玩家写进正文的那句文案（见 _ENGINE_MOVE）。整句必须**恰好**是
    # 一个登记地点名才认，尾段简称也算（登记「灵药园柴房」，玩家打「你前往柴房」）
    engine = _ENGINE_MOVE.match(text)
    if engine:
        where = norm_name(engine.group(1))
        hits = {
            name for key, name in names.items()
            if key and (where == key
                        or (len(where) >= _MIN_PLACE_PART and key.endswith(where)))
        }
        if len(hits) == 1:
            return hits.pop()
    clauses = re.split(r"[，,。；;！!\n]+", text)
    if len(clauses) > 1:
        # 逐个分句往下找第一个说得出目的地的那一句。**动身不一定打头**：
        # 「走吧，去密室，让她们……」里前面那句只是个语气词，从前只试第一个
        # 分句，这句就整个认不出来——人留在原地，GM 却照着写了一段已经到了的
        # 剧情。按分句判还比拿整句判准：「她说要去酒馆」这种第三人称的否定
        # 依据（_MOVE_DENY）正好落在自己那一句里，不会被前面的字挤出窗口
        for index, clause in enumerate(clauses):
            destination = movement_target(clause, locations)
            if not destination:
                continue
            # 后面再冒出第二个目的地照旧整句交回 AI（「先回客栈，再去酒馆」）
            for later in clauses[index + 1:]:
                for match in re.finditer(_MOVE_VERB_RE, later):
                    rest = later[match.end():].strip().lstrip("了向到往").strip().strip('「」『』“”"')
                    if _place_hits(norm_name(rest), names):
                        return ""
            return destination
    direct = _place_hits(norm_name(text), names)
    if direct:
        # 光打一个地名：唯一点名才算数，两个「柴房」交回 AI（同下面那条）
        return direct.pop() if len(direct) == 1 else ""
    hits = set()
    for match in re.finditer(_MOVE_VERB_RE, text):
        head_text = text[:match.start()]
        # 前面已经有一个移动动词 = 这是第二个目的地（「先回客栈，再去酒馆」「前往
        # 灵药园并回到柴房」）。这一段本身认不出地名时尤其危险：只认后半句就等于
        # 替玩家把前一段路吞了
        if _MOVE_VERB_RE.search(head_text):
            continue
        # 提议语气先剥掉，剩下的按紧邻几字判否定
        window = _SUGGEST.sub("", head_text)[-_DENY_WINDOW:]
        if _MOVE_DENY.search(window):
            continue
        rest = text[match.end():].strip().lstrip("了向到往").strip().strip('「」『』“”"')
        hits |= _place_hits(norm_name(rest), names)
    # 一句话指了两个地方就别替玩家挑，交给 AI 去读
    return hits.pop() if len(hits) == 1 else ""


# ── 自由输入里的「带谁走 / 派谁去 / 打发谁」 ────────────────────────────────
#
# 引擎只在**无歧义**时出手，认不出就整句交回 AI——同 movement_target 那条纪律：
# 猜错的代价是把人凭空挪走，比不认大。
#
# 这一段和 movement_target 共用 _MOVE_VERBS / _MOVE_DENY / _MOVE_TAIL。_MOVE_OR_BACK
# 从前是 `_MOVE_VERBS + "|回"`，裸「回」进 _MOVE_VERBS 之后直接取 _MOVE_VERBS——
# 这一支的语义（「回」算不算移动动词）一个字没变，变的是移动识别那边。
# _MOVE_DENY 拦的是「他去后山了」这类**说别人**的句子，它的价值恰恰在于字符级、
# 零上下文、绝不误伤。要处理「我带她去后山」，走的是下面这套「先把携带短语剥掉、
# 再拿剩下的跑原来那套」。

_WHO = r"[^，,。、！!？?；;：「」『』]"

# 带 / 领 / 拉 / 牵 / 扶 这一类是**明确**的「我带谁」——有没有「一起」都算。
# 刻意**不含裸「跟」**：「我跟他去客栈」是玩家随他走，不是他跟着玩家，
# 登记成跟随正好是反的。要认「跟着我」那种得靠「你跟着我」这个说法。
_CARRY_VERB_TAKE = (
    "带上|带着|带了|领上|领着|领了|拉上|"
    "叫上|喊上|抱上|约上|带|领"
)
# 贴身动作，不等于要动身：「扶她起来」「拉她的手」「牵着她坐下」一个都没在走路。
# 这一组只有在这句**真的在动身**时才算携带（见 _parse_carry 里的 going）——从前
# 一律算，于是一句原地的搀扶就把人写进了跟随名单，往后你走到哪儿她都在
_CARRY_VERB_TOUCH = "拉着|牵着|扶着|拽着|拉|牵|扶"
_CARRY_VERB = _CARRY_VERB_TAKE + "|" + _CARRY_VERB_TOUCH
_TOUCH_VERBS = frozenset(_CARRY_VERB_TOUCH.split("|"))
_CARRY_TAIL_TEXT = "一起|一同|一块|一齐|俩|两个|两人"
_CARRY_TAIL = re.compile(r"(?:" + _CARRY_TAIL_TEXT + r")")
# 「谁」那一段最多认这么多字，和下面正则里的 {1,10} 同一口径
_CARRY_WHO_MAX = 10
# 复数指代：认成**此刻在跟前的所有人**（口径同「我们走吧」把屋里的人都带上）。
# 跟前只有一个人时不认——说「她们」而屋里只站着一个，指的是不在场的那些人，
# 认了就是把不在场的人凭空挪过来，按纪律宁可漏认。
# **刻意不收「俩 / 两人 / 仨」这类数量词**：它们和 _CARRY_TAIL_TEXT 里的尾巴词
# 重叠，收进来会让「带上俩人一起走」的 who 和尾巴互相抢字，而它们本来就说不清
# 是哪几个。「大家 / 你们」在 _ALL_WORDS 里另有口径，只有「你们」两头都要认
_PLURALS = ("她们", "他们", "它们", "你们")
_CARRY = re.compile(
    # 复数代词必须排在 who 那个非贪婪通配**前面**：通配只会吃一个「她」，
    # 而单字那半边过不了「跟前恰好一个人」的唯一性判据，整条携带就永远认不出来
    r"(?P<verb>" + _CARRY_VERB + r")(?P<who>(?:" + "|".join(_PLURALS) + r")|" + _WHO + r"{1,10}?)"
    r"(?:" + _CARRY_TAIL_TEXT + r")?"
)
# 「和 / 与 / 同」只是连词，光看它认不出「我和他不一样」——**必须**跟出
# 「一起 / 俩」才算携带（「我和赫敏一起去后山」）。有了这个尾巴，误命中
# 后面还撞一次人名解析，两次都中才会出事
_CARRY_WITH = re.compile(
    r"(?:和|与|同)(?P<who>" + _WHO + r"{1,10}?)"
    r"(?:" + _CARRY_TAIL_TEXT + r")"
)
# 「我们 / 咱们」这类群体说法：屋里的人都带上（产品口径定的）。
# **不吃「我俩 / 咱俩」**——跟前站着三个人时它指的是哪两个无从判断，
# 宁可整句交回 AI
_GROUP = re.compile(r"我们|咱们")
# 不点名去哪儿的「动身」说法。它是「这句在不在动身」的第二个判据，第一个是
# movement_target 认得出地名。两个都不中的「我们」是在说话不是在走路——
# 「我们聊聊」「我们之间的事还没完」从前会把在场所有人登记成跟随
_SET_OFF = re.compile(r"走吧|该走|出发|动身|启程|上路")
# 「你跟着我」「赫敏跟着我」——跟着**我**走。
#
# 裸「跟」进不了 _CARRY_VERB：「我跟他去客栈」是玩家随他走，方向正好反着，
# 登记成跟随就错了。所以单独认这一支，判据是**跟的对象必须是「我 / 我们」**：
# 有这条，「我跟他去客栈」那种句子结构上就命不中。
#
# 主语空着（光说「跟着我」）算屋里全员，和「我们走吧」同一条口径
_FOLLOW_ME = re.compile(
    r"(?P<who>" + _WHO + r"{0,10}?)(?:，|,)?(?:跟着我|跟着我们|跟我走|跟我来)"
)
_MOVE_OR_BACK = _MOVE_VERBS
_SEND_TAIL = "等我|等着我|等我回来|候着|待着|呆着|别乱跑|去|来|吧|了"
_SEND_VERB = "派|打发|使唤|吩咐|安排|命令|让|叫"
# 「这句是不是在支使别人」的单用判据。_SEND 那条整句正则够不着的时候
# （被支使的人不在跟前），_moves_by_someone_else 要问的是同一批词
_SEND_WORDS = re.compile(_SEND_VERB)
# 「派赫敏去客栈」「让赫敏回宿舍」。who 允许为空 = 「你去客栈等我」那种
# 二身指代，由 _resolve_who 按「跟前恰好一个人」去判
_SEND = re.compile(
    r"(?:" + _SEND_VERB + r")(?P<who>" + _WHO + r"{0,10}?)"
    r"(?:" + _MOVE_OR_BACK + r")(?P<where>" + _WHO + r"{1,12}?)"
    r"(?:" + _SEND_TAIL + r")?$"
)
# 没有使役动词，主语就是她：「赫敏去客栈」「赫敏，你回宿舍去」。
# **只认句首**——不然「我看见赫敏去客栈」里那句陈述也会被当成命令
_SEND_SUBJ = re.compile(
    r"^(?P<who>" + _WHO + r"{1,10}?)(?:，|,)?(?:你)?"
    r"(?P<verb>" + _MOVE_OR_BACK + r")(?P<where>" + _WHO + r"{1,12}?)"
    r"(?:" + _SEND_TAIL + r")?$"
)
# 解除：「别跟着了」「不用跟着我」。否定词必须在「跟」**前面**，否则
# 「跟着我」那种携带会被它吃掉
_UNFOLLOW = re.compile(r"(?:别|不用|不必|不要|甭|莫)(?:再)?跟(?:着|踪)?")
# 无目的地的打发式：「你回去吧」「走吧」。和「你回宿舍去」只差一个字，
# 判据是**「回」后面跟的是不是一个登记地名**——地名那头归派遣，这头归解除
# （见 parse_company 的分支顺序：派遣认不出地名才轮到它）
_UNFOLLOW_GO = re.compile(r"回去|回去了|回去吧|走吧|散了|去忙|自己玩")
_PRONOUNS = ("你", "您", "她", "他", "它")
_PLAYER_WORDS = ("我", "我们", "咱", "咱们", "自己", "本人")
_ALL_WORDS = ("你们", "大家", "都", "全都", "所有人")
# 回顾和被动不是命令：「我带她去过那儿」不该把人登记成跟随，
# 「她被带走了」也不是玩家在带人
_PAST = re.compile(r"过|昨天|刚才|上次|之前|当时|曾经")


class Company:
    """这一句话里认出来的「带谁走 / 派谁去 / 打发谁」，外加玩家自己的去向。

    整份为空 = 这句话交给 AI 结算。**落库必须等自动存档拍完**：在存档之前写，
    读了档也回不到「她跟着你之前」。
    """

    __slots__ = ("move_to", "follow", "unfollow", "dispatch")

    def __init__(self, move_to="", follow=(), unfollow=(), dispatch=()):
        self.move_to = move_to
        self.follow = tuple(follow)
        self.unfollow = tuple(unfollow)
        self.dispatch = tuple(dispatch)

    def __bool__(self) -> bool:
        # 显式写出：不定义的话对象恒为真，调用方那两个 `if company` 就永远成立
        return bool(self.move_to or self.follow or self.unfollow or self.dispatch)


EMPTY_COMPANY = Company()


def _prep_company(content: str) -> str:
    """识别前的一遍清洗：去空格、去礼貌前缀、去句末标点。

    **只给这套识别用**，movement_target 一个字都不改——它那几条测试的语义是
    既有行为，不该被新功能顺手改动。
    """
    text = re.sub(r"[ \t　]+", "", (content or "").strip())
    # 前缀里**不能有「麻烦你」**：那个「你」是下一句的主语，一起剥掉之后
    # 「麻烦你去客栈等我」就剩「去客栈等我」，谁去没人知道，整句认不出来
    text = re.sub(r"^(?:请|麻烦|劳驾|喂|那|那么|来)+", "", text)
    return text.strip().rstrip("。！!…~～")


def _here_candidates(
    npcs: list[RpgNpc], sess: RpgSession,
    private_with: int | None = None, mode: str = GROUP_MODE,
) -> list[RpgNpc]:
    """这一刻能认的人：跟前站着的那些。

    私聊收窄到对面那一个人——玩家刚刚亲手点开了和谁的私聊，这是这套识别里
    最硬的一个锚点，零猜测。

    用 present_ids 而不是裸的 here_npcs：它有一条既有兜底——**一个地点都没建的
    模组 = 所有人都在同一个场面里**（见 rpg_context.present_ids）。纯对话模组里
    here_npcs 恒为空，拿它当候选集的话，人名解析会跟着一起失效。
    """
    ids = set(present_ids(
        npcs, sess.location, sess.slot, sess.npc_places, sess.npc_followers,
    ))
    if mode == PRIVATE_MODE and private_with in ids:
        ids = {private_with}
    me = norm_name(sess.char_name)
    return [
        n for n in world_npcs(npcs)
        if n.id in ids and norm_name(n.name) != me
    ]


def _plural_who(text: str, candidates: list[RpgNpc]) -> list[RpgNpc] | None:
    """复数指代落在「此刻在跟前的所有人」上；不是复数就返回 None。

    跟前只有一个人时返回**空列表**（= 认出来了，但不认）：说「她们」而屋里只有
    一个人，指的是不在场的那些人。认了就是把不在场的人凭空挪过来，是这套识别里
    最贵的一类错——同 _resolve_who_one 里单数代词那条唯一性判据，宁可漏认。
    """
    if text not in _PLURALS:
        return None
    return list(candidates) if len(candidates) >= 2 else []


def _resolve_who_one(text: str, candidates: list[RpgNpc]) -> RpgNpc | None:
    if text in _ALL_WORDS:
        return None
    if text in _PRONOUNS:
        # 代词只在跟前**恰好一个人**时才认：「带她走」而屋里一男一女，
        # 指谁不明——交回 AI。角色卡上没有性别这一栏，猜不了也不该猜
        return candidates[0] if len(candidates) == 1 else None
    return match_npc(text, candidates)


def _resolve_who(span: str, candidates: list[RpgNpc]) -> list[RpgNpc]:
    """把「她 / 赫敏 / 你和赫敏」这段解析成具体的人。认不准就返回空列表。

    只认**此刻在跟前**的人。不在场的人被登记成跟随，等于凭空把她挪过来——
    这是这套识别里最贵的一类错，比不认贵得多。

    名字走 match_npc（自带三级放宽和「对上两个就当没对上」）；代词走上面那条
    唯一性判据。两条口径一致，所以「带赫敏一起走」而她在别的屋，和不点名的
    「带她走」，行为是同一个：不认。
    """
    text = (span or "").strip().strip("，,、和与同跟")
    if not text or text in _PLAYER_WORDS:
        return []
    parts = [p for p in re.split(r"[，,、]|和|与", text) if p.strip()]
    if not parts or any(p in _PLAYER_WORDS for p in parts):
        return []
    out = []
    for part in parts:
        # 复数指代先摊开成「在场的全部」。摊不开（跟前不够两个人）同样是整句
        # 不认，理由和下面那条一样
        plural = _plural_who(part.strip(), candidates)
        if plural is not None:
            if not plural:
                return []
            out.extend(plural)
            continue
        # 多目标（「你和赫敏」）里有一个认不出就整句不认：认一半的代价是
        # 「这个人跟着你了」而另一个人没有，玩家看不出差别在哪
        got = _resolve_who_one(part.strip(), candidates)
        if got is None:
            return []
        out.append(got)
    return out


def _registered_place(span: str, locations: list[RpgLocation]) -> str:
    """把「客栈 / 客栈后院」这段对回模组登记过的地名。对不上返回空串。

    现编的地名一律不认：写一个不存在的地名进 npc_places，here_npcs 是按地名
    **全等**比的，她的在场判定会从此恒为假——人就在你旁边，侧栏却说这儿没别人，
    而且没有任何入口能纠正。走 match_place 是为了「外门藏经阁 → 藏经阁」那种
    修饰（同一个函数，结算是同一条口径）。
    """
    text = (span or "").strip().strip("，,。、！!？?")
    if not text:
        return ""
    names = {norm_name(l.name): l.name for l in locations if l.name}
    return names.get(norm_name(match_place(text, list(names.values()))), "")


def _parse_unfollow(text: str, here: list[RpgNpc]) -> list[int]:
    """要解除跟随的人。空列表 = 没认出来。"""
    for pattern in (_UNFOLLOW, _UNFOLLOW_GO):
        match = pattern.search(text)
        if not match:
            continue
        head = text[:match.start()].strip().strip("，,、")
        # 没点名就是全体（「都别跟着了」）。点名前但认不出（跟前站着两个，
        # 只说「你回去吧」）——不认，交回 AI：把人打发走也是改状态
        if not head or head in _ALL_WORDS:
            return [n.id for n in here]
        return [n.id for n in _resolve_who(head, here)]
    return []


def _carry_who_by_growth(
    text: str, match: re.Match, here: list[RpgNpc],
) -> tuple[list[RpgNpc], int]:
    """携带正则的 who 认不出人时，从「谁」那个位置逐字加长再认一次。

    返回 (人, 剥到哪儿为止)，一直认不出就是 ([], 0)。

    从短往长的理由见 _parse_carry 里那段注释：match_npc 认「前后缀」，从长往短
    会把后面的地名一起吞掉。
    """
    start = match.start("who")
    for size in range(1, _CARRY_WHO_MAX + 1):
        if start + size > len(text):
            break
        got = _resolve_who_one(text[start:start + size], here)
        if got is None:
            continue
        # 名字后面紧跟的「一起 / 俩」也算携带短语的一部分，一起剥掉，
        # 剩下的才是玩家自己的去向
        tail = _CARRY_TAIL.match(text, start + size)
        return [got], tail.end() if tail else start + size
    return [], 0


def _parse_carry(
    text: str, here: list[RpgNpc], locations: list[RpgLocation],
) -> tuple[list[int], str]:
    """返回 (要跟着你走的人, 玩家自己的去向)。

    「先剥再跑」：把「带她一起」这一整段从句子去掉，剩下的「我去后山」再丢给
    原来那套 movement_target。

    **认不出谁就不许剥**——剥了会改动玩家自己的移动解析，那比不认更糟。
    剥完 movement_target 认不出目的地时退回原文再跑一遍，理由同上。
    """
    hits: list[RpgNpc] = []
    spans: list[tuple[int, int]] = []
    # 这句到底在不在动身：认得出地名，或者明说了「走吧」。贴身动作那一组
    # （_CARRY_VERB_TOUCH）只有动身时才算携带——「扶她起来」「拉她的手」是
    # 原地的动作，认成携带就是给人加了一条永久跟随，而她本人一步都没挪
    whole = movement_target(text, locations)
    going = bool(whole) or _SET_OFF.search(text) is not None
    for match in (*_CARRY.finditer(text), *_CARRY_WITH.finditer(text)):
        if not going and match.groupdict().get("verb") in _TOUCH_VERBS:
            continue
        who = _resolve_who(match.group("who"), here)
        if who:
            end = match.end()
        else:
            # 正则里那个 who 是**非贪婪**的，后面没有「一起」这种必须出现的尾巴
            # 时它只吃一个字——「带上赫敏去后山」抓到的是「带上赫」，而一个字
            # 过不了 match_npc 的两字门槛，于是整条携带永远认不出来，句子掉到
            # 派遣那支去，变成「她把赫敏派走了、玩家自己没动」。
            #
            # 这里从动词后面**逐字加长**再认一次。必须从短往长试：match_npc 的
            # 放宽是「一方是另一方的前后缀」，反过来第一个试的就是「赫敏去后山」，
            # 它 startswith「赫敏」照样命中——人物是认对了，地名却被一起啃掉。
            who, end = _carry_who_by_growth(text, match, here)
            if not who:
                continue
        # 同一段被两张正则各命中一次时只算一次：两个 span 叠着剥会把文本切坏
        if any(not (end <= s or start >= e) for start, e in spans):
            continue
        hits.extend(who)
        spans.append((match.start(), end))
    if not hits:
        return [], whole

    seen: set[int] = set()
    ids: list[int] = []
    for npc in hits:
        if npc.id not in seen:
            seen.add(npc.id)
            ids.append(npc.id)

    stripped = text
    for start, end in reversed(spans):
        stripped = stripped[:start] + stripped[end:]
    dest = movement_target(stripped, locations) or whole
    return ids, dest


def _named_exactly(span: str, candidates: list[RpgNpc]) -> RpgNpc | None:
    """主语必须是**正好**这个人名，不享受 match_npc 那三级放宽。

    裸句式（「赫敏去客栈」）没有「派 / 让」那种使役动词托底，那三级放宽在这里
    是有毒的：`_SEND_SUBJ` 允许 who 吃到十个字，而放宽里有一条「一方是另一方的
    后缀」——「我看见赫敏」endswith「赫敏」，于是玩家一句**陈述**就把跟前的人
    派走了。有使役动词的那支放宽是安全的：动词本身已经说明这是命令。
    """
    key = norm_name(span)
    if not key:
        return None
    hits = [n for n in candidates if norm_name(n.name) == key]
    return hits[0] if len(hits) == 1 else None


# 裸句式遇上代词主语（「你回宿舍去」）时要有一个祈使的尾巴才算命令。光说
# 「你去后山」跟前又站着人，那既可能是支使也可能是在讲别人的事，宁可交回 AI
_IMPERATIVE_TAIL = ("等我", "等着我", "等我回来", "候着", "待着", "呆着", "别乱跑", "吧", "去")


def _parse_send(
    text: str, here: list[RpgNpc], locations: list[RpgLocation], private: bool = False,
) -> list[tuple[int, str]]:
    """返回 [(npc_id, 地名)]。认不出就是空列表。

    「你」指谁：跟前恰好一个人就认，私聊时就是对面那个人；跟前站着两个就说的是
    谁不明——不出手（同 movement_target 的 len(hits) == 1）。宁可漏认：派遣猜错
    的代价也是把人挪到错的地方，和移动同级。
    """
    # 句末的「了」是完成态：「他去后山了」说的是已经发生的事，不是支使人。
    # _SEND_TAIL 里有「了」，不拦的话这句会把跟前那个人**派到后山去**——
    # 玩家在讲别人的事，引擎却动了手
    if text.endswith("了"):
        return []
    for pattern in (_SEND, _SEND_SUBJ):
        match = pattern.search(text)
        if not match:
            continue
        if pattern is _SEND_SUBJ:
            subject = match.group("who").strip()
            if subject in _PRONOUNS:
                # 私聊里不要那个尾巴：玩家刚亲手点开和她的对话，「你」指的是谁
                # 是这套识别里唯一零猜测的场合，不必再拿「等我」证明是命令。
                #
                # **但「你」指谁零猜测，不等于「这句是不是命令」也零猜测**——
                # 后一件事私聊一点忙都帮不上。书面腔的动词（_ENGINE_MOVE_VERBS）
                # 就是分界：那是引擎文案的说法，玩家照着打说的是自己要走，
                # 得照常拿祈使尾巴证明它是命令
                trusted = private and match.group("verb") not in _ENGINE_MOVE_VERBS
                if not trusted and not text.endswith(_IMPERATIVE_TAIL):
                    continue
                who = _resolve_who(subject, here)
            else:
                got = _named_exactly(subject, here)
                who = [got] if got else []
        else:
            who = _resolve_who(match.group("who"), here)
        if not who:
            continue
        place = _registered_place(match.group("where"), locations)
        if not place:
            continue
        return [(npc.id, place) for npc in who]
    return []


def _fallback(raw: str, locations: list[RpgLocation]) -> Company:
    """认不出任何命令时的退路：去向照旧交给 movement_target 单独跑一遍。

    这不是「顺手也试一下移动」——路由那边是 `move_target = company.move_to`
    **无条件覆盖**的，返回一个空对象等于替玩家把这一句里的移动一起取消掉。
    被取消的不只是「我去后山」：屋里空无一人的时候，`_here_candidates` 是空的，
    从前那种「没有别人在场就什么都认不出」会让玩家在空屋里走不动路。

    收的是**原文**不是清洗过的那份：这一支要和改动之前路由里那一行
    `movement_target(content, locations)` 逐字一致，`_prep_company` 剥掉的
    礼貌前缀和尾部标点不该顺手改掉移动识别的口径。
    """
    return Company(move_to=movement_target(raw, locations))


def _moves_by_someone_else(text: str, npcs: list[RpgNpc]) -> bool:
    """这句里要动身的是不是**别人**。

    两种形状都是错认的重灾区，落到 movement_target 上被挪走的会是**玩家**：
    「派赫敏去客栈」玩家自己没动，「赫敏去客栈」动的也不是玩家。错认的代价是
    下一轮正文里玩家已经站在别处了，比漏认大得多，所以一律拦下、整句交回 AI。

    ① 派遣动词 + 具名对象（「派赫敏去客栈」）。跟前有她的时候归 _parse_send，
       这一条管的正是她不在跟前、那边够不着的情况。
    ② 移动动词前面**整个就是**一个登记角色的名字（「赫敏去客栈」）。要全等而
       不是「结尾对上就算」：「带赫敏去客栈」那种前面挂着携带动词的，说的还是
       玩家自己要走，吞掉就成了该走的时候留在原地。

    **按分句判，不按整句前缀判**：「我让赫敏先走，我去客栈」里那个派遣短语在
    前一句，拿整句前缀去搜会把后一句玩家自己的移动一起拦掉。
    """
    previous = ""
    for clause in re.split(r"[，,。；;！!？?\n]+", text):
        match = _MOVE_VERB_RE.search(clause)
        if not match:
            previous = clause
            continue
        lead = clause[:match.start()]
        if _SEND_WORDS.search(lead) and named_npcs(npcs, lead):
            return True
        # 动词打头的分句（「赫敏，去客栈」），主语在上一句里——_SEND_SUBJ 那条
        # 正则本来就认这个形式（who 后面跟一个可选的逗号），这里的口径得和它一致
        head = norm_name((lead or previous).strip())
        if head and any(head == norm_name(npc.name) for npc in world_npcs(npcs)):
            return True
        previous = clause
    return False


def parse_company(
    content: str, locations: list[RpgLocation], npcs: list[RpgNpc],
    sess: RpgSession, private_with: int | None = None, mode: str = GROUP_MODE,
) -> Company:
    """从玩家那句话里认出「带谁走 / 派谁去 / 打发谁」，以及玩家自己的去向。

    纯函数：不开会话、不落库，全部依赖调用方读好的对象（同 movement_target）。
    **落库必须等自动存档拍完**——在存档之前写，读了档也回不到「她跟着你之前」。

    三条意图互斥，命中即返回；一条都认不出就交回 AI 结算：

        解除 → 携带 → 派遣 → 回落 movement_target

    解除排最前：它是唯一一条反向的，被别的规则先吃掉就成了「越说越跟得紧」。

    **「一条都没认出来」不等于「去向也是空」**：调用方（路由）拿到的 move_to 是
    **无条件**覆盖原来那一次 movement_target 的，所以这里的每条退路都得把去向
    原样交出去——「屋里一个人都没有」的时候玩家说「我去后山」，去向不能跟着
    一起丢掉。只有那三条**认出命令**的分支才自己说了算（「派赫敏去客栈」里那个
    「去」的主语是她，不是玩家）。

    唯一的例外是 _moves_by_someone_else 拦下的那几句：它们明说了动身的是**别人**，
    交回 AI 结算时宁可一个字都不动，也不许让玩家替她走这一趟。
    """
    text = _prep_company(content)
    if not text:
        return EMPTY_COMPANY
    # 问句、回顾、被动：这三个字段一个都不许动，但**去向照旧要给**
    if re.search(r"[?？]|吗$", text):
        return _fallback(content, locations)
    if _PAST.search(text) or re.search(r"^" + _WHO + r"{0,4}被", text):
        return _fallback(content, locations)

    here = _here_candidates(npcs, sess, private_with, mode)
    if not here:
        # 跟前一个人都没有，「带谁走 / 派谁去」本来无从谈起——但「派赫敏去客栈」
        # 这类替**不在场**的人动身的句子照样不能落到 movement_target 上：
        # 那个「去」的主语是她，落下去就是把玩家平白挪走
        if _moves_by_someone_else(text, npcs):
            return EMPTY_COMPANY
        return _fallback(content, locations)

    gone = _parse_unfollow(text, here)
    if gone:
        # 打发式的「走吧 / 回去吧」（_UNFOLLOW_GO）只在**没说去哪儿**时算打发人。
        # 「走吧，去密室」是招呼着一起动身，不是叫人散了——判据和 _UNFOLLOW_GO
        # 那条注释一致：句子里认得出地名，就轮不到解除。不然这句会连人带去向
        # 一起吞掉：人被解散、玩家留在原地，GM 却照着写一段已经到了的剧情。
        #
        # 两道闸都得关严：① 明说「别跟着」（_UNFOLLOW）的，带不带地名都是要人
        # 别跟；② 点了名的（「你们走吧，回宿舍」）是在支使人回去，只有打发语
        # **打头**、前面一个字都没有时，那才是招呼自己人动身
        bare = _UNFOLLOW_GO.match(text) is not None and not _UNFOLLOW.search(text)
        dest = movement_target(text, locations) if bare else ""
        if not dest:
            return Company(unfollow=gone)
        # 招呼同行，口径同下面那条「我们走吧」：屋里的人都带上
        return Company(move_to=dest, follow=[n.id for n in here])

    # 群体说法：「我们走吧」。**不改文本**——「我们」本来就不挡 _MOVE_DENY，
    # 「我们回宿舍」照原文跑。带否定词的不认：「我们别去了」不是要带人走。
    #
    # 光有「我们」不算：这两个字在对话里太常见，「我们聊聊」「我们之间的事还
    # 没完」一个人都没要带，从前却把在场所有人登记成了永久跟随。要么认得出
    # 去向，要么明说了动身，否则这句让给后面几条分支（去向照旧由退路交出）
    if _GROUP.search(text) and not re.search(r"[别不莫甭]", text):
        dest = movement_target(text, locations)
        if dest or _SET_OFF.search(text):
            return Company(move_to=dest, follow=[n.id for n in here])

    # 「你跟着我」：跟着**我**走。剥掉这一段再跑移动识别，理由同携带——
    # 「你跟着我去后山」里的「去后山」也得照常认出来
    match = _FOLLOW_ME.search(text)
    if match:
        span = match.group("who").strip()
        who = here if not span else _resolve_who(span, here)
        if who:
            rest = text[:match.start()] + text[match.end():]
            dest = movement_target(rest, locations) or movement_target(text, locations)
            return Company(move_to=dest, follow=[n.id for n in who])

    ids, dest = _parse_carry(text, here, locations)
    if ids:
        return Company(move_to=dest, follow=ids)

    sent = _parse_send(text, here, locations, mode == PRIVATE_MODE)
    if sent:
        return Company(dispatch=sent)

    # 走到这儿说明三条命令一条都没认出来。但**认不出命令不等于这句是玩家在动身**：
    # 「派赫敏去客栈」而赫敏不在跟前时 _parse_send 够不着（它只支使得动跟前的人），
    # 这句里的「去客栈」再落到 movement_target 上，被挪走的就成了玩家——而被支使
    # 的是她。错认的代价比漏认大得多，宁可整句交回 AI
    if _moves_by_someone_else(text, npcs):
        return EMPTY_COMPANY

    return _fallback(content, locations)


def _apply_company(
    sess: RpgSession, npcs: list[RpgNpc], company: Company,
) -> list[str]:
    """把认出来的「带谁走 / 派谁去 / 打发谁」落到库上。返回事实句。

    这是这三件事**唯一**的落地点：路由那边只做识别、不写库（写库必须等自动存档
    拍完，否则读了档也回不到「她跟着你之前」）。

    跟随和解除只动 npc_followers，**位置一个字都不写**——她跟到哪儿由 npc_place
    的取值链当场算出来，所以这里不需要任何「移动之后同步一遍」的收口。派走则写
    npc_places，离场者在下一格回到跟随或作息安排，在场者保留当前地点。
    """
    by_id = {n.id: n for n in npcs}
    facts: list[str] = []
    for npc_id in company.follow:
        npc = by_id.get(npc_id)
        if npc is not None and apply_npc_followers(sess, npc_id, True):
            facts.append(f"{npc.name}跟上了你")
    for npc_id in company.unfollow:
        npc = by_id.get(npc_id)
        if npc is not None and apply_npc_followers(sess, npc_id, False):
            facts.append(f"{npc.name}不再跟着你")
    for npc_id, place in company.dispatch:
        npc = by_id.get(npc_id)
        if npc is None:
            continue
        # 派走一个正跟着你的人，顺手解除跟随：她人都被你支使走了，名单上还
        # 留着她，下一个时段就会把她拽回你身边
        apply_npc_followers(sess, npc_id, False)
        apply_npc_place(sess, npc_id, place)
        facts.append(f"{npc.name}去了{place}")
    return facts


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


async def adjudicate(
    module: RpgModule, sess: RpgSession, action: str, recent: str, npcs=(),
):
    """判断这一轮要不要判定、看哪一项数值、有多难。返回 (judgement, in_tok, out_tok)。

    模型只能从五个难度档位里挑，成功率由模组的 rate_table 定死。「这算困难吗」比
    「这是 63% 还是 55%」稳定一个数量级，这是治难度漂移最有效的一招。

    npcs 是模组的全部角色，只用来给裁决认人（见 ref_roster）。裁决本来就要读
    玩家这句话，顺手让它把「这句话说的是谁」也报出来，比事后再猜一遍便宜——
    而且它手上还有最近剧情和判定台账，比字面匹配懂得多。**这是本地对象，
    判完就没人再碰它**，LLM 那一跳不占着数据库连接。
    """
    stats = sess.stats or {}
    prompt = render(
        "rpg_adjudicate.jinja2",
        action=action,
        stats=stats,
        location=sess.location or "",
        recent=recent,
        ledger=(sess.dc_ledger or [])[-LEDGER_LIMIT:],
        roster=ref_roster(list(npcs)),
    )
    model, api_format = llm_client.get_agent_client("memory", module.adjudication_model_ref or module.fast_model_ref)
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
        # 模型认出来的人，按模组名单收敛（它编出来的名字进不来）。
        # 这几个名字会被并进扫描文本，让那几张卡这一轮就发出去
        "refs": resolve_refs(data.get("refs"), list(npcs)),
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
        f"{n.name} 现在在 "
        f"{npc_place(n, sess.slot, sess.npc_places, sess.npc_followers, sess.location) or '行踪不明'}\n"
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
            if n.id in met and npc_place(
                n, sess.slot, sess.npc_places, sess.npc_followers, here,
            ) != here
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
                    "place": npc_place(
                        n, sess.slot, sess.npc_places, sess.npc_followers, here,
                    ) or "行踪不明",
                    "persona": (n.persona or n.description or "").strip()[:60],
                    "notes": "；".join(
                        f"{k} {v}" for k, v in ((sess.npc_notes or {}).get(str(n.id)) or {}).items()
                    )[:60],
                }
                for n in others
            ],
            chronicle=chronicle_lines(sess)[-CHRONICLE_PROMPT_LINES:],
        )
        model, api_format = llm_client.get_agent_client("memory", module.offscreen_model_ref or module.fast_model_ref)
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
    - **不让模型改位置**。启用随机移动时，引擎先从模组地点中选好去处，
      写入本局 npc_places，再把确定的地点交给模型描述活动。
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
        protected_ids = set(sess.npc_followers or []) | {
            npc.id for npc in named_npcs(npcs, last.content if last else "")
        }
        slot = (sess.slot or "").strip()
        places = dict(sess.npc_places or {})
        random_places = dict(getattr(sess, "npc_random_places", None) or {})
        location_changed = False
        # 随机移动只在配置的时段生效；离开这些时段后撤销随机覆盖，
        # npc_place() 才能重新使用作息表或常驻地点。只处理调度器自己写入的覆盖。
        for npc in idle:
            key = str(npc.id)
            marked = random_places.get(key)
            if marked is None:
                continue
            current = places.get(key)
            if current is None or norm_name(current) != norm_name(marked):
                random_places.pop(key, None)
                location_changed = True
                continue
            slots = {str(value).strip() for value in (npc.random_movement_slots or []) if str(value).strip()}
            if not npc.random_movement or (slots and slot not in slots):
                places.pop(key, None)
                random_places.pop(key, None)
                location_changed = True
        sess.npc_places = places
        sess.npc_random_places = random_places
        movable = [
            npc for npc in idle
            if npc.random_movement and npc.id not in protected_ids
            and (
                not (npc.random_movement_slots or [])
                or slot in {
                    str(slot).strip() for slot in (npc.random_movement_slots or [])
                    if str(slot).strip()
                }
            )
            and (
                not norm_name(sess.location or "")
                or norm_name(npc_place(npc, sess.slot, sess.npc_places))
                != norm_name(sess.location)
            )
        ]
        if movable:
            locations = list((await store.execute(
                select(RpgLocation).where(RpgLocation.module_id == module.id)
            )).scalars().all())
            names = list(dict.fromkeys(
                place.name.strip() for place in locations if (place.name or "").strip()
            ))
            for npc in movable:
                current = npc_place(npc, sess.slot, sess.npc_places)
                choices = [name for name in names if norm_name(name) != norm_name(current)] or names
                if choices:
                    apply_npc_place(sess, npc.id, random.choice(choices), source="random")
                    location_changed = True
        if location_changed:
            await store.commit()
        prompt = render(
            "rpg_activity.jinja2",
            day=max(1, sess.day or 1),
            slot=(sess.slot or "").strip(),
            location=(sess.location or "").strip(),
            recent=((last.content or "")[-ACTIVITY_RECENT_CHARS:] if last else "") or "（故事刚开始）",
            npcs=[
                {
                    "name": n.name,
                    "place": npc_place(
                        n, sess.slot, sess.npc_places, sess.npc_followers,
                        (sess.location or "").strip(),
                    ) or "行踪不明",
                    "persona": (n.persona or n.description or "").strip()[:60],
                    "activity": npc_activity(sess, n.id),
                }
                for n in idle
            ],
        )
        model_ref = module.activity_model_ref or module.fast_model_ref

    try:
        model, api_format = llm_client.get_agent_client("memory", model_ref)
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


def _usable_actions(
    sess: RpgSession, sources: SuggestSources, here: list[RpgNpc], module=None,
) -> list[tuple[RpgAction, str]]:
    """这次建议能列出来的动作：(动作, 一个合格的对象名，或空串)。

    `needs_target` 的按 **∃** 搜：只要名册里有**一个人**能让这个动作过判据，
    它就该进清单——点下去会弹窗挑人，挑谁由玩家定，这里只是替引擎先答一句
    「这个按钮此刻是不是死的」。判据仍然只有 `_action_gate` 那一份，这里只改
    量化方式：带对象的动作拿 `None` 判一次是必错的（关系条件全都不成立）。

    候选池分两种，同前端 `condition.targetChoices`：远程动作（手机、传讯）
    挑整份名册，其余只能挑此刻站在跟前的人。

    结果**同时**喂注入段和白名单。分头算两遍的话，两处迟早漂成
    「建议里有这一条、点下去却被拦」。
    """
    usable: list[tuple[RpgAction, str]] = []
    for action in sources.actions:
        if action.needs_target:
            pool = world_npcs(sources.npcs) if action.target_anywhere else here
            who = next((n for n in pool if not _action_gate(sess, action, n, sources.npcs, module)), None)
            if who is not None:
                usable.append((action, who.name))
            continue
        if not _action_gate(sess, action, None, sources.npcs, module):
            usable.append((action, ""))
    return usable


async def suggest_actions(
    module: RpgModule, sess: RpgSession, history: list[RpgMessage],
    here_ids: set[int] | None, sources: SuggestSources,
) -> tuple[list[dict], dict]:
    """「帮我想想」：给出 3 条能点的事 + 3 句能说的话，附各块 token 的诊断。

    和每轮结算顺带产出的 suggestions 是两条独立的路：那条是被动等来的，
    这条是玩家按按钮要的。返回空列表表示没能生成，前端提示一下就好。

    history 是全部历史，同 build_rpg_messages——两个调用点必须看同一份东西，
    否则建议会提「问问她后山的事」这种和眼前无关的选项（那正是 §30 当初把
    scene_history 一起接进来的理由）。`here_ids` 同理：那边按在场名单筛窗口，
    这边不筛的话，会提「接着问她二十年前那件事」——而她根本不在这间屋里。

    `sources` 是这一刻能引用的全部东西（背包、技能、地点、动作、世界书），
    由调用方查好；动作那部分这里再过一遍 `_action_gate` 填进 `usable`。
    """
    recent = history_window(module, sess, history, here_ids)[-SUGGEST_WINDOW:]
    if not recent:
        return [], {}

    here = [n for n in world_npcs(sources.npcs) if here_ids is None or n.id in here_ids]
    sources = replace(sources, module=module, usable=_usable_actions(sess, sources, here, module))

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
    # 资料段**拼在渲染结果之后**，不往模板里加变量。理由见 suggest_blocks：
    # 模板用户可覆写，加占位符对他们的旧版本是静默失效。scan_text 只取最近
    # 两条，同 build_rpg_messages：扫全文会让 GM 自己的旁白反复命中同一条词条
    scan_text = "\n".join(m.content for m in recent[-2:])
    extra, diag = suggest_blocks(module, sess, sources, here, scan_text)
    prompt += extra

    model, api_format = llm_client.get_agent_client("memory", module.suggestion_model_ref or module.fast_model_ref)
    text = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.95,
        max_tokens=900,
    )

    # 先收一个宽池子再分桶。直接按 3+3 的总量收口的话，模型先写满 6 条带标签的
    # 就把后面的对白全挤掉了——名额得在收完之后按类型分，不能在收的时候截
    rows = split_quota(clean_suggestions(
        parse_tagged_lines(text or ""), sess, sources,
        limit=2 * (MAX_STRUCTURED + MAX_FREE),
    ))
    # dispatch_chat_complete 不回传用量，所以**输出侧 token 拿不到**，这里只有
    # 输入和分成因。别以为漏了——想知道模型写了多少字得换 call_json，而那个
    # 强制 JSON 输出会毁掉标签协议的退化安全
    diag["prompt_tokens"] = estimate_tokens(prompt)
    diag["count"] = len(rows)
    diag["structured"] = sum(1 for r in rows if r["kind"] != "free")
    diag["free"] = sum(1 for r in rows if r["kind"] == "free")
    return rows, diag


# ── 一整轮 ────────────────────────────────────────────────────────────────

async def run_turn(
    session_id: int,
    user_message_id: int,
    content: str,
    attr_override: str = "",
    action_id: int | None = None,
    item_name: str = "",
    item_qty: int = 1,
    skill_name: str = "",
    move_to: str = "",
    target_npc: str = "",
    present: list[int] | None = None,
    place: str = "",
    mode: str = GROUP_MODE,
    private_with: int | None = None,
    company: Company | None = None,
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
    action_time = None
    engine_effects = {}
    fixed_location = None
    async with AsyncSessionLocal() as store:
        sess0 = await store.get(RpgSession, session_id)
        # 普通叙事默认发生在本轮开始地点；只有明确的移动引擎动作才能改变它。
        fixed_location = (sess0.location or "").strip() or None
        engine_before = rpg_settlement.capture(sess0)
        clock_before = (sess0.day or 1, sess0.slot or "")
        # 冷却在这里统一递减：每一轮都要减，自由打字那几轮也算时间过去了。
        # 放在引擎结算之前，这一轮刚压上的冷却不会被自己减掉
        tick_cooldowns(sess0)
        # 纯对话记一条。判据和下面那个 if 互为反面：点了动作/道具/技能/移动的
        # 那几轮走 spend_slot_action 记「行动」，剩下的才是「聊天」。
        # 记在这里而不是 _resolve_engine 里，因为那个函数只在引擎路径被调用
        # company 也算「引擎认领了这一轮」：不带上它，「带她一起走」会被记成
        # 一条纯聊天，而这个时段的行动位就白花了
        if not (action_id or item_name or skill_name or move_to or company):
            note_slot_chat(sess0)
        await store.commit()
    if action_id or item_name or skill_name or move_to or company:
        try:
            facts, warns, state = await _resolve_engine(
                session_id, action_id, item_name, move_to, target_npc, skill_name,
                company, item_qty, engine_effects=engine_effects,
            )
            for warn in warns:
                yield "warning", warn
            if facts:
                clock_after = (state["day"], state["slot"])
                if clock_before != clock_after:
                    action_time = tuple(
                        f"第 {day} 天 · {slot}" for day, slot in (clock_before, clock_after)
                    )
                    facts.append(f"行动时间：{action_time[0]} → {action_time[1]}")
                engine_note = "；".join(facts)
                if move_to:
                    fixed_location = state["location"]
                yield "state", state
                yield "engine_result", {"facts": facts}
        except Exception:
            logger.exception("RPG 局 %s 引擎结算失败", session_id)
            engine_effects.clear()
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
        # 裁决那一步也得认人（见 ref_roster），名单就这一次取好。下面那个 if
        # 本来就要查同一张表，提到这里只是把它挪到分支外面。
        # **必须在 LLM 调用之前**：裁决发请求那会儿手上拿的是本地对象，
        # 数据库连接早就还了（写锁不跨 LLM 调用）
        npcs = list((await store.execute(
            select(RpgNpc).where(RpgNpc.module_id == module.id)
        )).scalars().all())
        next_present = [npc.id for npc in turn_present(npcs, sess, mode, private_with)]
        if sess.location != place or next_present != present:
            present = next_present
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
                # 代词优先解析到本轮在场角色；只有玩家明确写出场外角色姓名时才补入候选。
                ref_npcs = list(turn_present(npcs, sess, mode, private_with))
                known_ids = {npc.id for npc in ref_npcs}
                for npc in named_npcs(npcs, content):
                    if npc.id not in known_ids:
                        ref_npcs.append(npc)
                judgement, aux_in, aux_out = await adjudicate(
                    module, sess, content, recent, ref_npcs,
                )
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
            mode, private_with, action_time=action_time,
        )
        # 外貌已经随这次上下文发出去了，就地记一笔，下一轮不再重复发。
        # 放在开流之前而不是之后：叙事失败也算见过，模型确实已经拿到过那段描写。
        # 只认 npcs_here：被提到一句的人这一轮也拿到了设定，但玩家并没见到他，
        # 记成见过会让他的外貌永远等不到该出现的那一次
        mark_met(fresh_sess, [n["id"] for n in diag["npcs_here"]])
        # 时间跳跃那句话已经随这次上下文发出去了，就地清掉，只在推过时段之后的那
        # 一轮出现。同样放在开流之前：叙事失败也算发过，模型确实已经拿到那句话了
        fresh_sess.time_jump_from = ""
        # 断场那句话同理：只在瞬移之后的那一轮出现，不清的话此后每一轮都会说一遍
        # 「你离开过那儿」，模型会把每一幕都当成刚进门
        fresh_sess.scene_break_from = ""
        settlement_seed = rpg_settlement.seed_settlement(
            fresh_sess, user_message_id, engine_before, engine_note, fixed_location,
            mode, private_with, origin_present,
        )
        settlement_seed["outcome_label"] = OUTCOME_LABELS.get((judgement or {}).get("outcome") or "", "")
        settlement_seed["engine_facts"] = list(facts)
        settlement_seed["engine_effects"] = engine_effects
        await store.commit()
    # 出了 with 块才开流：写锁不跨 LLM 调用
    yield "meta", diag
    # 上下文已经拼好，正要调叙述模型。这一条发出去之后到第一个 token 之间
    # 就是最后一段静默期，前端据此显示「组织线索中…」
    yield "stage", "building"

    # 模型解析放这里：模型配错时 resolve_model_ref 抛 ValueError，
    # 在生成器内抛才能变成一条 error 事件，放外面会变成 500 白屏
    model, api_format = llm_client.get_agent_client("writer", fresh_module.model_ref)

    # **一次调用写完整轮**：环境、所有 NPC 的言行、玩家行动的结果都在 messages
    # 这一份上下文里，模型从头写到尾，边写边往前端吐字。
    #
    # 曾经拆成过「GM 写环境草稿 → 感知分发 → 每个 NPC 各一次 → 合稿」的分角色
    # 管线，图的是结构性隔离（写台词的模型根本拿不到玩家面板）。代价太大：一轮
    # 正文实际被生成三遍（草稿、分发逐字重抄、合稿重写），演员那几次还走写作
    # 模型且串行，而且整条链路攒到最后才吐——玩家盯着空白等全部跑完。
    # 隔离改回提示词约束（rpg_gm.jinja2 的「不要做的事」、PRIVATE_SHEET_NOTE、
    # SCENE_PREAMBLE 三处）。那套管线存档在 rpg-knowledge-pipeline 分支
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
    except (asyncio.CancelledError, GeneratorExit, Exception):
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
    if not reply:
        raise ValueError("模型没有返回剧情，请重试这一轮")
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
            retain_task(settlement_task)
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
                is_free = not (action_id or item_name or skill_name or move_to or company)
                if is_free and fresh_module.free_costs_slot and result["settlement"]["status"] == "done":
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
                            clock_npcs = list((await store.execute(
                                select(RpgNpc).where(RpgNpc.module_id == module2.id)
                            )).scalars().all())
                            slot_facts = spend_slot_action(module2, sess2, clock_npcs)
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
    # **这是唯一一次「玩家说完话了还在调模型」**，所以它必须排在 done 之前——
    # done 之后前端就不再收了，玩家的侧栏会一直停在旧状态。
    # 没勾任何角色、或者勾了的都在场，这一次调用根本不发生。
    #
    # **只有这一轮时段真的翻篇了才调。** 从前是每轮都调，而调度器问的是「不在
    # 跟前的那个人最近在做什么」——时段没动，答案和上一轮不会有区别，那次调用
    # 是白花的。跳过时她那句话保持原样：apply_npc_activity 只在有内容时才写，
    # 不调它天然不会清空。按「结束这个时段」按钮那条路不经过这里，
    # 调度补在 routes/rpg.py 的 advance_time 里。
    #
    # 时钟只可能被引擎那条路（吃格子的动作、行动预算攒满）和上面 scene_wrapped
    # 那条路推动，两处都落在下面这次比对里，所以推时段的地方不必各自回传标记
    try:
        async with AsyncSessionLocal() as store:
            scheduled_session = await store.get(RpgSession, session_id)
            clock_now = clock_before if scheduled_session is None else (
                (scheduled_session.day or 1), (scheduled_session.slot or "")
            )
            payload = None if scheduled_session is None else _state_payload(scheduled_session)
        if clock_now != clock_before:
            # diag 是这一轮注入过设定的人（在场 + 被提到的）。他们归叙事模型管，
            # 调度器另写一份会和玩家刚经历的剧情对不上
            # npcs_onstage 是「在场 + 被提到」，比 npcs_here 宽：被提到的人这一轮
            # 也拿到了设定，调度器再替他们编一份「今天在干什么」会和刚写的对不上。
            # 原先这里还要单独补一个 thread_id（线主），线没了——线主的定义本来就是
            # 「你正在跟她说话的那个」，而她已经在这份名单里了
            engaged = {int(n["id"]) for n in diag.get("npcs_onstage") or []}
            await idle_npc_activities(session_id, engaged)
            async with AsyncSessionLocal() as store:
                scheduled_session = await store.get(RpgSession, session_id)
                if scheduled_session is not None:
                    payload = _state_payload(scheduled_session)
        # 这条 state 就算上面整段都跳过了也照发：它不只带「谁最近在做什么」。
        # tick_cooldowns 每轮都在减冷却、note_slot_chat 每轮都在加聊天数，而
        # skills / slot_chats 不在 STATE_FIELDS 里，结算那条 state 带不上它们——
        # 吞掉这一条，玩家会看到一颗明明已经能点的技能还灰着
        if payload is not None:
            yield "state", payload
    except Exception:
        logger.exception("RPG 局 %s 角色调度失败", session_id)

    yield "done", {
        "message_id": message_id,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "aux_input_tokens": aux_in,
        "aux_output_tokens": aux_out,
    }
