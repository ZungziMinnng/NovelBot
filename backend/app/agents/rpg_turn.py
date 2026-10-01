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
import time
from dataclasses import replace
from datetime import datetime
from typing import AsyncIterator

from sqlalchemy import select, update

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
from app.services import llm_client, rpg_settlement, rpg_vectors
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
    opposed_for,
    opposed_roster,
    present_ids,
    rank_stat_of,
    ref_roster,
    resolve_refs,
    slot_summary,
    slot_upto,
    slot_window,
    suggest_blocks,
    turn_present,
    world_npcs,
)
from app.services.rpg_dice import (
    DEFAULT_BAND, OUTCOME_LABELS, RATE_PER_POINT, normalize_band, resolve_rate, roll,
)
from app.services.rpg_prompts import render
from app.services.rpg_operation import retain_task
from app.services.rpg_state import (
    AWAY,
    npc_away,
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
    def_map,
    effect_cost_reason,
    for_check_stats,
    mark_fired,
    mark_met,
    match_npc,
    match_place,
    norm_name,
    note_slot_chat,
    note_visited,
    npc_activity,
    npc_bonds_of,
    npc_offscreen_of,
    random_movement_ok,
    record_offscreen,
    set_npc_bond,
    random_place_expired,
    set_cooldown,
    skill_cooldown_left,
    slots_in_place,
    spend_slot_action,
    tick_cooldowns,
    tier_of,
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
        # 那句话按时段留的底。跟着一起带回去：档案里「她这几格在忙什么」
        # 和上面那一句是同一次写入的两面，只刷一个会让两处对不上
        "npc_activity_log": sess.npc_activity_log or {},
        # 调度写下的幕后往事和关系标签。全量带回去，筛「已查明」是前端的事——
        # 上帝视角那颗开关要的就是没筛过的那份
        "npc_offscreen": sess.npc_offscreen or [],
        "npc_bonds": sess.npc_bonds or [],
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
                # 来到了灵药园柴房」。同 move_by_name 里那道闸，从前只有按钮那条路有，
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


# 裸「到」排在最后：走到 / 回到 / 来到 / 移动到 都在它前面，正则的最左最先匹配
# 保证「走到天台」认的还是「走到」，不会被裸「到」抢掉半个动词。
# 「到天台看看」从前整句认不出来——表里有走到/回到/来到，偏偏没有裸「到」，于是
# 玩家留在原地，GM 照着写了一段已经上了天台的剧情，结算再报「顶楼天台不是你这
# 一轮待过的地方」，那儿的近况一条都记不下。
# 单字这么常见却敢收，靠的是动词**后面**那道白名单（_place_hits + _MOVE_TAIL）：
# 「说到公司的事」「我想到家里还有事」的续字都不在 _MOVE_TAIL 里，一律不认。
# 「等她到家」这种说别人的归 _MOVE_DENY（窗口里有「她」「等」）
_MOVE_VERBS = "前往|前去|去往|走到|走向|走进|进入|回到|返回|回|移动到|赶往|来到|去|到"
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
# 「时候」进表是为了裸「到」：「问她什么时候到家」里的主语「她」被「什么时候」
# 这四个字挤出了窗口，不收这个词就会把**玩家**送回家。它同时管住「到时候去公司」
# 那种推迟。代价是「这个时候去公司」也不认——照这张表一贯的偏向，宁可不认
_MOVE_DENY = re.compile(
    r"[不别莫没未他她它你并等]|懒得|然后|时候|"
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
# 人名同理：一个字的「李」在任何句子里都撞得到（_moves_by_someone_else 用）
_MIN_NAME_PART = 2


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
    for _clause, rest in _move_heads(text):
        hits |= _place_hits(norm_name(rest), names)
    # 一句话指了两个地方就别替玩家挑，交给 AI 去读
    return hits.pop() if len(hits) == 1 else ""


def _move_heads(text: str):
    """这句话里每个「敢当成玩家动身」的移动动词后面那一截。

    从 movement_target 里原样抽出来的，为的是 movement_candidate 能复用
    **同一套前置守卫**（第二个目的地、_SUGGEST、_MOVE_DENY）。各写一份的话
    迟早漂成「移动那边拦、建地点这边不拦」——而那一侧漂错的代价是往作者的
    地点表里插一条「他去客栈」。
    """
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
        yield head_text, text[match.end():].strip().lstrip("了向到往").strip().strip('「」『』“”"')


# 自动建出来的地名长度。上限同 _ENGINE_MOVE 里那个 {1,12}；下限借
# _MIN_PLACE_PART——一个字的「园」建出来谁都对得上，等于给地点表下毒
_NEW_PLACE_MAX = 12
# 地名里不该出现的字。命中一个就整条弃掉：这些字说明切下来的这截是**半句话**
# 而不是一个地名（代词、否定、数量、以及「的」这种一看就是从句子中间切开的）
# 指示代词（这/那）单独列一句：「去那儿看看」切出来的是「那儿」，长度和字符都
# 合法，可它不是个地名——而作者的地点表里一旦长出「那儿」，往后每个「去那边」
# 都会对上它
_NOT_A_PLACE = re.compile(r"[我你他她它们不别没未很都也就还又把被和跟给让请谁什么哪这那]")

# 地名得像个地名：末尾必须是这些字之一。**这是这条路上唯一的锚**，不是又一道
# 过滤器——没有它，`_MOVE_TAIL` 就从「边界确认」退化成「地名切割」：
# 「我去宗主说得对」里 _MOVE_TAIL 认得「说」，于是前面那截「宗主」被当成地名建进库
# （「回去修炼了」→「去修炼」、「去问问宗主说得对不对」→「问问宗主」，同一个病）。
# 原来那条路上不出这种事，因为它有 `_place_hits` 拿**登记地名**当锚，尾巴只负责
# 确认「地名到这儿为止」；这条路上没有登记名可比，锚只能由地名自己的形状来当。
#
# 同 _MOVE_TAIL：**白名单，不是黑名单**，所以漏的错法是「不建」（整句交给 AI，
# 原地不动），不是「建错」。作者想要「太玄」这种没有通名后缀的地名，手动加一条。
# 刻意不收的几个：「门」（「去开门」）、「观」（「去参观」）、「界/境/层」
# （「去下一层」）——它们太容易撞上日常说法
_PLACE_TAIL = re.compile(
    r"(?:阁|殿|室|房|园|苑|山|林|谷|峰|崖|洞|窟|城|村|镇|庄|店|铺|楼|院|寺|庙|塔|"
    r"桥|巷|街|港|湾|河|湖|海|岛|井|田|场|厅|堂|台|关|营|寨|府|宫|宅|舍|屋|窖|"
    r"仓|库|馆|所|站|坊|亭|廊|家|码头|客栈)$"
)


def movement_candidate(content: str, locations: list[RpgLocation], npcs: list[RpgNpc]) -> str:
    """这句话里那个**还没登记过**的去处。空串 = 没有，或者不敢当地名。

    `movement_target` 对不上登记名就返回空串，而那一截候选它其实已经算出来了
    ——这里把它捞出来，交给路由去建。判据全是「宁可不建」：建错一条地点会
    永久长在作者的地点表里，而且每轮都拼进 prompt。

    **「和已有地点重合」这件事不用另写判据**：`_place_hits` 的匹配方向是单向的
    ——它只认「玩家说的那截是登记名的后缀」（`head.startswith(key[cut:])`）。
    所以已有「织云阁地下密室」时：
      - 玩家说「密室」→ 命中 → movement_target 就返回那个地点，走移动，这里根本
        不会被调到；
      - 玩家说「太玄大殿密室」→ 不命中（head 的头是「太」，对不上任何后缀）→
        当成新地方。
    这正是需求要的口径：话说得**更短**是同一个地方，话说得**更长**是另一个地方。
    千万别顺手放宽成双向子串或者「共享后缀」——「太玄大殿密室」和「织云阁地下
    密室」共享「密室」，那两种写法都会把它判成重合，需求里第二个例子当场就错。
    """
    text = content.strip().rstrip("。！!").strip()
    # 问句是在打听，不是在动身（同 movement_target 第一道闸）
    if re.search(r"[?？]|吗$", text):
        return ""
    names = {norm_name(l.name): l.name for l in locations if l.name}
    hits = set()
    # **必须先按分句切**，同 movement_target：不切的话「先回客栈，再去太玄大殿
    # 密室」里第一个动词后面那截是「客栈，再去太玄大殿密室」，整条被当成地名
    # 建进库。下面那道标点闸是第二层保险，别拿掉任何一层
    clauses = re.split(r"[，,。；;！!\n]+", text)
    for clause in clauses:
        for _head, rest in _move_heads(clause.strip()):
            # 对得上登记地点的归 movement_target，这儿只收它认不出来的
            if _place_hits(norm_name(rest), names):
                return ""
            # 「去后山竹林看看」的 rest 是「后山竹林看看」，地名只到「竹林」为止。
            # **切的位置由 _PLACE_TAIL 定，不由 _MOVE_TAIL 定**：拿 _MOVE_TAIL 找
            # 切口的话，「我去宗主说得对」会在「说」那儿切出一个叫「宗主」的地名
            # ——那张表是用来确认「地名到这儿为止」的，它认得的字里一半是日常动词。
            # 所以反过来：从长到短试，第一个**自己就长得像个地名**的前缀才算。
            name = ""
            for cut in range(min(len(rest), _NEW_PLACE_MAX), _MIN_PLACE_PART - 1, -1):
                head = rest[:cut].strip().strip("的了呢吧啊嘛")
                if _PLACE_TAIL.search(head) and not _NOT_A_PLACE.search(head):
                    name = head
                    break
            if not (_MIN_PLACE_PART <= len(name) <= _NEW_PLACE_MAX):
                continue
            # 「去赫敏那儿」不能建出一个叫「赫敏那儿」的地点
            if match_npc(name, npcs):
                continue
            hits.add(name)
    # 同 movement_target：一句话指了两个地方就别替玩家挑
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
# 单用判据：「动词前面这一段里有没有携带动词」。_moves_by_someone_else 靠它
# 把「带赫敏去客栈」放回玩家自己动身那条路上（见那个函数的例外清单）
_CARRY_VERB_RE = re.compile(_CARRY_VERB)
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
# 第一人称。_moves_by_someone_else 用它把「我跟赫敏去客栈」「我和赫敏一起去后山」
# 放回玩家自己动身那条路上——这两句里名字确实在动词前面，但动身的是玩家
_FIRST_PERSON = re.compile(r"[我咱]")
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
# 派遣专用的动词表，比 _MOVE_VERBS 多两个**光身的**「到 / 来」：「让她到卧室
# 等我」「喊她来公司」是最自然的支使说法，而 _MOVE_VERBS 里只有「回到 / 来到」
# 这类双字词，于是这两句一个字都不动、整句交给 AI，位置改动最后被结算那道
# 「缺少赶来的原文依据」打回——玩家下了指令，三道关一道都没执行。
#
# 光身的字只敢加在这条**派遣专用**的表里，不能加进 _MOVE_VERBS：那张表还管
# 玩家自己的去向，「我到家了」会被读成一次移动。放心的另一半是去处那头由
# _registered_place 兜着：「让她把东西放到桌上」的「桌上」不是登记地名，不认
_MOVE_OR_BACK = _MOVE_VERBS + "|到|来"
_SEND_TAIL = "等我|等着我|等我回来|候着|待着|呆着|别乱跑|去|来|吧|了"
_SEND_VERB = "派|打发|使唤|吩咐|安排|命令|让|叫|喊"
# 名字和使役动词之间夹的语气副词。「让韩曼宁**先**回家吧」里 who 会把「先」
# 一起吃进去，于是 _named_exactly 要求的全等对不上，这句就此作废
_SEND_ADVERB = re.compile(r"^(?:就|先|快|赶紧|马上|立刻|现在|这就|自己|亲自)+|"
                          r"(?:就|先|快|赶紧|马上|立刻|现在|这就|自己|亲自)+$")
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
# 使役动词**前面**那几个字：有否定或条件，这句就不是在支使人。「别让韩曼宁回家」
# 「如果让她回家」——_SEND 是从「让」开始匹配的，前面那个「别」整个落在匹配之外，
# 不在这里拦一道，引擎反倒替玩家把人派走了。
# 口径同 movement_target：先剥提议前缀（_SUGGEST），再只看紧邻的几个字
# （_DENY_WINDOW）。拿整句前缀按单字拦会误伤「我不累，让她回家」。
# _SEND_SUBJ 那条不需要这道门：它 ^ 锚定，否定词会落进 who 里，而具名主语走
# _named_exactly（要求正好是这个名字），「如果韩曼宁回家」自己就对不上
_SEND_DENY = re.compile(r"[不别莫甭没未]|如果|要是|万一|假如|倘若|只要|除非")
# 「把韩曼宁叫到卧室来」。宾语提前是最常见的支使句式之一，而 _SEND 要求
# 使役动词紧挨着人名（「叫韩曼宁…」），提前之后就对不上了。
#
# **只收招呼类的动词**：「把她带到卧室」的「带」是携带（玩家自己也过去），
# 归 _CARRY 那条线，收进来就会把一次携带记成一次派遣，她被挪走而玩家留在原地
_SEND_BA = re.compile(
    r"把(?P<who>" + _WHO + r"{1,10}?)(?:叫|喊|请|派|支)(?:" + _MOVE_OR_BACK + r")"
    r"(?P<where>" + _WHO + r"{1,12}?)(?:" + _SEND_TAIL + r")?$"
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


def _send_who(
    span: str, here: list[RpgNpc], npcs: list[RpgNpc],
) -> tuple[list[RpgNpc], bool]:
    """派遣的对象，以及「这是不是点了名的一个人」。

    **名字认全世界，不只认跟前**：玩家说「让韩曼宁回家」，她此刻在内衣店——
    派她去别处不是携带那条线忌讳的「凭空挪到你跟前」，指令的落点本来就在别处。
    从前这里只认跟前的人，于是这句一个字都不动，交给 AI 去写，正文里她用代词
    出场，结算再因为「缺少该角色赶来的原文依据」把位置改动打回——玩家明明下了
    指令，三道关一道都没执行。

    先试全等的名字，再落回原来那条（代词、多人、match_npc 的放宽）：她就在
    跟前时两条路给出同一个人，所以这个顺序只新增「不在跟前」那一种情况。

    点没点名要往外说：句末带「了」的陈述句只对点了名的人算指令，见 _parse_send。
    """
    # 语气副词先削掉：「让韩曼宁先回家吧」里 who 是「韩曼宁先」，全等对不上，
    # 这句就此作废。削在这里而不是放进正则：who 是贪婪吃到动词为止的一段，
    # 在正则里再加一层可选前后缀会让那条本来就长的式子更难看懂（见 _SEND_ADVERB）
    bare = _SEND_ADVERB.sub("", span.strip())
    got = _named_exactly(bare, world_npcs(npcs)) or _named_exactly(span, world_npcs(npcs))
    if got:
        return [got], True
    return _resolve_who(bare, here) or _resolve_who(span, here), False


def _parse_send(
    text: str, here: list[RpgNpc], npcs: list[RpgNpc],
    locations: list[RpgLocation], private: bool = False,
) -> list[tuple[int, str]]:
    """返回 [(npc_id, 地名)]。认不出就是空列表。

    「你」指谁：跟前恰好一个人就认，私聊时就是对面那个人；跟前站着两个就说的是
    谁不明——不出手（同 movement_target 的 len(hits) == 1）。宁可漏认：派遣猜错
    的代价也是把人挪到错的地方，和移动同级。
    """
    # 句末的「了」是完成态。代词主语一律不认：「他去后山了」是在讲别人的事，
    # 而「他」会被解析成跟前那个人，不拦就把她**派到后山去**。
    #
    # **点了名的是例外**：「韩曼宁回到家了」这种陈述语气，说的就是让她回家——
    # 玩家的输入本身就是指令，不是「供模型理解意图」的参考。两道守卫替它兜底：
    # 名字必须全等（「我看见韩曼宁回家了」的主语整段对不上），地点必须登记过。
    # 「昨天 / 刚才 / 曾经」那种真·回顾更早就被 parse_company 的 _PAST 拦掉了
    done = text.endswith("了")
    # _SEND_BA 和 _SEND 走同一套守卫（否定/条件前缀、名字、登记地名），
    # 所以放在一组里：下面那个 else 分支对两者都成立
    for pattern in (_SEND, _SEND_BA, _SEND_SUBJ):
        match = pattern.search(text)
        if not match:
            continue
        if pattern is _SEND_SUBJ:
            subject = match.group("who").strip()
            if subject in _PRONOUNS:
                if done:
                    continue
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
                got = _named_exactly(subject, world_npcs(npcs))
                who = [got] if got else []
        else:
            # 使役动词前面有否定或条件，这句不是在支使人（见 _SEND_DENY）
            window = _SUGGEST.sub("", text[:match.start()])[-_DENY_WINDOW:]
            if _SEND_DENY.search(window):
                continue
            who, named = _send_who(match.group("who"), here, npcs)
            if done and not named:
                continue
        if not who:
            continue
        place = _registered_place(match.group("where"), locations)
        if not place:
            continue
        return [(npc.id, place) for npc in who]
    return []


def _fallback(
    raw: str, locations: list[RpgLocation], npcs: list[RpgNpc], sess: RpgSession,
) -> Company:
    """认不出任何命令时的退路：去向照旧交给 movement_target 单独跑一遍。

    这不是「顺手也试一下移动」——路由那边是 `move_target = company.move_to`
    **无条件覆盖**的，返回一个空对象等于替玩家把这一句里的移动一起取消掉。
    被取消的不只是「我去后山」：屋里空无一人的时候，`_here_candidates` 是空的，
    从前那种「没有别人在场就什么都认不出」会让玩家在空屋里走不动路。

    收的是**原文**不是清洗过的那份：这一支要和改动之前路由里那一行
    `movement_target(content, locations)` 逐字一致，`_prep_company` 剥掉的
    礼貌前缀和尾部标点不该顺手改掉移动识别的口径。

    地名认不出时再试一次「去找赫敏 / 去往赫敏处」：去处是个人，落点是她此刻在哪儿。
    """
    return Company(move_to=movement_target(raw, locations)
                   or _npc_destination(raw, locations, npcs, sess))


# 人名后面允许跟的「那个人所在的地方」说法。「去赫敏家」的「家」不在这里——
# 那是另一个地方，不是她此刻站的地方
_NPC_SPOT = re.compile(r"^(?:所在的地方|在的地方|那里|那儿|那边|那|身边|旁边|跟前|处)")


def _npc_destination(
    raw: str, locations: list[RpgLocation], npcs: list[RpgNpc], sess: RpgSession,
) -> str:
    """「去往赫敏处」「去找赫敏」「到赫敏那儿去」→ 赫敏此刻所在的登记地点。空串 = 不认。

    前置守卫和 movement_target 共用 _move_heads（否定、他人主语、第二个目的地）。
    动词前面点了别人的名、或者有使役词的一律不认：「让赫敏去找韩曼宁」动身的是赫敏。
    人名可以只说一半（同 match_npc 的方向：说得比登记名短），但不能说得更长——
    「去赫敏家」不是去赫敏那儿。对上两个人不认。她已离开、或者在一个没登记的
    地方，也不认，交回 AI。
    """
    text = raw.strip().rstrip("。！!").strip()
    if re.search(r"[?？]|吗$", text):
        return ""
    people = world_npcs(npcs)
    hits = set()
    for clause in re.split(r"[，,。；;！!\n]+", text):
        for head, rest in _move_heads(clause.strip()):
            if _SEND_WORDS.search(head) or named_npcs(people, head):
                continue
            rest = norm_name(re.sub(r"^(?:找|见)", "", rest))
            for cut in range(_MIN_NAME_PART, len(rest) + 1):
                who, tail = rest[:cut], rest[cut:]
                if tail and not (_NPC_SPOT.match(tail) or _MOVE_TAIL.search(tail)):
                    continue
                hits |= {n.id for n in people
                         if (name := norm_name(n.name)) and (name.startswith(who) or name.endswith(who))}
    if len(hits) != 1:
        return ""
    npc = next(n for n in people if n.id in hits)
    if npc_away(sess, npc.id):
        return ""
    place = npc_place(npc, sess.slot, sess.npc_places, sess.npc_followers, sess.location)
    names = {norm_name(l.name): l.name for l in locations if l.name}
    return names.get(norm_name(place), "")


def _moves_by_someone_else(text: str, npcs: list[RpgNpc], locations: list[RpgLocation]) -> bool:
    """这句里要动身的是不是**别人**。

    两种形状都是错认的重灾区，落到 movement_target 上被挪走的会是**玩家**：
    「派赫敏去客栈」玩家自己没动，「赫敏去客栈」动的也不是玩家。错认的代价是
    下一轮正文里玩家已经站在别处了，比漏认大得多，所以一律拦下、整句交回 AI。

    ① 派遣动词 + 具名对象（「派赫敏去客栈」）。跟前有她的时候归 _parse_send，
       这一条管的正是她不在跟前、那边够不着的情况。
    ② 移动动词前面**出现**一个登记角色的名字（「赫敏去客栈」「赫敏得去客栈一趟」）。

    ② 从前要求那一段**整个等于**一个名字，于是名字后面多挂一个字就漏：
    「赫敏这个点该回宿舍了」「嘱咐赫敏回宿舍」「赫敏得去客栈一趟」全都落到
    movement_target 上，被挪走的是**玩家**——该走的是她。代词那一侧从来不要求
    全等（「她这个点该回宿舍了」被 _MOVE_DENY 的字符窗口拦着，「她」在那张字表里），
    两把尺子松紧不一样，名字这把松得多，这就是那个洞。

    放宽之后靠两个例外把原先全等护住的东西接回来，缺一个都会造出新 bug：

    - **携带动词**护「带赫敏去客栈」。她不在跟前时 _parse_carry 够不着（那条只
      支使得动跟前的人），落到这儿来；不排掉就成了该走的时候玩家留在原地，而
      GM 照着写一段已经到了的剧情。
    - **第一人称**护「我跟赫敏去客栈」「我和赫敏一起去后山」——这两句动身的
      确实是玩家。

    名字要两个字以上（同 _MIN_NAME_PART 的理由）：一个字的名字在任何句子里都撞得到。

    代价是会多漏一些玩家自己的移动（「赫敏在的话就去客栈」整句交回 AI）。按这份
    识别一贯的纪律——错认把人凭空挪走比漏认贵得多——这个方向是对的。

    **只是不再挪错人，不等于把她挪对了**：这几句现在一个字都不动、整句交给 AI。
    要让「嘱咐赫敏回宿舍」真的挪她，得另外给 _SEND_VERB 补词或让裁决那一步回
    一个派遣字段，是另一件事。

    **按分句判，不按整句前缀判**：「我让赫敏先走，我去客栈」里那个派遣短语在
    前一句，拿整句前缀去搜会把后一句玩家自己的移动一起拦掉。

    **只拦自己认得出去向的分句**：这道闸防的是「她的去向被安到玩家头上」，
    而 movement_target 的去向只可能出自某个能单独认出登记地点的分句。认不出
    地点的那句（「晏昭华表示刚刚送到门口就回去了」——转述她做过的事）挪不动
    任何人，从前却照样把整句拦下，连同前面那句「你移动到客厅」一起吞掉。
    """
    previous = ""
    for clause in re.split(r"[，,。；;！!？?\n]+", text):
        match = _MOVE_VERB_RE.search(clause)
        if not match or not movement_target(clause, locations):
            previous = clause
            continue
        lead = clause[:match.start()]
        if _SEND_WORDS.search(lead) and named_npcs(npcs, lead):
            return True
        # 动词打头的分句（「赫敏，去客栈」），主语在上一句里——_SEND_SUBJ 那条
        # 正则本来就认这个形式（who 后面跟一个可选的逗号），这里的口径得和它一致
        head = norm_name((lead or previous).strip())
        if head and not _CARRY_VERB_RE.search(head) and not _FIRST_PERSON.search(head) \
                and any(
                    len(norm_name(npc.name)) >= _MIN_NAME_PART
                    and norm_name(npc.name) in head
                    for npc in world_npcs(npcs)
                ):
            return True
        previous = clause
    return False


def missed_dispatch(
    content: str, locations: list[RpgLocation], npcs: list[RpgNpc],
) -> tuple[str, str]:
    """疑似漏认的派遣：这句话里同时有一个登记角色和一个登记地名。返回 (人, 地)。

    **只用来记日志，不改任何行为**。词表那套识别是穷举句式的，漏认时玩家下的
    指令三道关全落空（引擎不动、正文用代词、结算报「缺少赶来的原文依据」），
    而漏了多少没人知道。先量几天真实频次，再决定要不要让裁决那一步顺手回一个
    派遣字段——裁决本来就在读这句话、本来就在调模型。

    判据故意宽松（不看动词、不看语序），所以**假阳性是预期的**：「她从药店回来
    以后」也会被记下。它量的是上限，不是准确数。
    """
    who = next((npc.name for npc in named_npcs(npcs, content)), "")
    if not who:
        return "", ""
    return who, _registered_place(_prep_company(content), locations)


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
        return _fallback(content, locations, npcs, sess)
    if _PAST.search(text) or re.search(r"^" + _WHO + r"{0,4}被", text):
        return _fallback(content, locations, npcs, sess)

    here = _here_candidates(npcs, sess, private_with, mode)
    if not here:
        # 跟前一个人都没有。「带谁走 / 打发谁」无从谈起，但**派遣照认**——
        # 点了名的指令（「让韩曼宁回家」）落点本来就在别处，跟她此刻在不在你
        # 跟前没关系。真实存档里玩家独自在家说「韩曼宁回到家了」，从前走的是
        # 下面那条 _moves_by_someone_else：一个字不动、交给 AI 写，正文用代词
        # 出场，结算再以「缺少赶来的原文依据」打回——玩家下的指令三道关全落空
        sent = _parse_send(text, here, npcs, locations, mode == PRIVATE_MODE)
        if sent:
            return Company(dispatch=sent)
        # 「派赫敏去客栈」这类替**不在场**的人动身的句子不能落到 movement_target
        # 上：那个「去」的主语是她，落下去就是把玩家平白挪走
        if _moves_by_someone_else(text, npcs, locations):
            return EMPTY_COMPANY
        return _fallback(content, locations, npcs, sess)

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

    sent = _parse_send(text, here, npcs, locations, mode == PRIVATE_MODE)
    if sent:
        return Company(dispatch=sent)

    # 走到这儿说明三条命令一条都没认出来。但**认不出命令不等于这句是玩家在动身**：
    # 「派赫敏去客栈」而赫敏不在跟前时 _parse_send 够不着（它只支使得动跟前的人），
    # 这句里的「去客栈」再落到 movement_target 上，被挪走的就成了玩家——而被支使
    # 的是她。错认的代价比漏认大得多，宁可整句交回 AI
    if _moves_by_someone_else(text, npcs, locations):
        return EMPTY_COMPANY

    return _fallback(content, locations, npcs, sess)


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

    等级项排到最后：作者十有八九会把「境界」标成 for_check，于是它成了第一个，
    每一次回落都变成「用境界检定」——而没有对手的等级检定不产生任何修正，
    等于这一轮的数值全白点。有别的项就先用别的。
    """
    usable = [n for n in for_check_stats(module.stat_defs) if n in (stats or {})]
    rank = rank_stat_of(module)
    if rank:
        usable.sort(key=lambda n: n == rank)
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
        # 没人填能力数值就是空的，整块（含 opponent 字段说明）都不渲染
        opposed=opposed_roster(module, npcs),
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
        # 这一次要对上的人。原样留着名字，认人交给 opposed_for（它用 match_npc，
        # 比 refs 那条宽松子串匹配严）。模组没开对抗时模型根本看不到这个字段
        "opponent": str(data.get("opponent") or "").strip(),
        "reason": str(data.get("reason") or "").strip(),
    }, in_tok, out_tok


def apply_roll(module: RpgModule, sess: RpgSession, judgement: dict, npcs=()) -> dict:
    """把档位换成成功率并判一次。纯 Python，没有 LLM 插手的余地。

    judgement 一律用 .get() 读：玩家在输入框旁手选检定项那一条路上，它是手搓的
    五个键的字面量，连 refs 都没有；而这个调用点不在那个 try 里面，一次 KeyError
    就是整轮 500——那还是玩家每次用下拉框都会走的路。

    npcs 给默认值，老调用不用改。
    """
    stats = sess.stats or {}
    attr = judgement.get("attr") or ""
    rank = rank_stat_of(module)
    card, rival = opposed_for(module, npcs, judgement.get("opponent"), attr)

    if rank and rival is not None:
        # 等级制真的碰上人了：比的一律是等级项，attr 只进叙事和台账
        stat = rank
        value = stats.get(rank)
        opposed = rival
        per_point = int(getattr(module, "rank_per_level", 0) or 0) or RATE_PER_POINT
    else:
        stat = attr
        value = stats.get(attr)
        # 没对手时 None = 对 STAT_BASELINE 比，也就是老行为
        opposed = rival
        per_point = RATE_PER_POINT
        if rank and attr == rank and rival is None:
            # 裁判挑中了等级项，又没有对手（等级制下这是最常见的情形）。
            # 等级尺和属性尺不是一把尺，落回 STAT_BASELINE=10 会让境界 3 的人
            # 练个功都必败。比自己 → 差为 0 → 这一项不产生任何修正
            opposed = value

    rate = resolve_rate(
        module.rate_table, judgement.get("band"), value, module.difficulty_bias,
        opposed=opposed, per_point=per_point,
    )
    out = {**judgement, **roll(rate, module.random_check)}
    # 三个键一律覆写：模型报上来的名字如果没认出人，原样留着就会让判定条写出
    # 「对 阿隼」而实际上什么都没对上。认出了就报，哪怕那一项没填——判定条
    # 照样写「对 魔尊」。opposed_stat 只在真比了的时候给，前端拿它查 tiers
    out["opponent"] = card.name if card is not None else ""
    out["opposed_stat"] = stat if rival is not None else ""
    out["opposed_value"] = rival
    # 给叙事模型看的那一句。在这儿拼是因为只有这里同时握着模组定义、玩家数值
    # 和对手数值；judgement_blocks 手上只有一份 judgement
    out["opposed_note"] = ""
    if card is not None and rival is not None:
        spec = def_map(module.stat_defs).get(stat)
        out["opposed_note"] = f"{stat} {_tier_text(spec, value)} 对 {_tier_text(spec, rival)}"
    return out


def _tier_text(spec, value) -> str:
    """一个数值写给人看的样子：有档名就用档名（元婴期），没有就是裸数字。"""
    if value is None:
        return "未知"
    tier = tier_of(spec, value)
    return str(tier.get("label") or value) if tier else str(value)


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

    时间和地名单**不止给 npc_places 用，更是给 suggestions 那三条用的**，所以
    即使没人可挪也照样拼。模板里压根没有时间（叙事那一侧早就有，见
    `_compose_state` 里那句「看不见它就会自己编」），于是记录员编出来的建议会
    写「明天早上再去找她」而现在就是早上、「等天黑了动手」而当前时段已经是夜。
    地名同理：它只能从这一段正文里认地名，模组里那地方叫「悦来居」它照样写
    「回镇上的客栈」——而**建议里的地名一个字都不过校验**（结算这条路只出
    free 和 item，free 文本不查白名单，见 rpg_suggestions.clean_suggestions），
    编错了原样递到玩家眼前。
    """
    out = ""
    # 只在模组设了时段时才写，同 _compose_state / has_clock 那道判据：
    # 没时钟的模组说「第 1 天」只会让模型以为有个它看不见的日程表
    slot = str(getattr(sess, "slot", "") or "").strip()
    if slot:
        day = max(1, int(getattr(sess, "day", 1) or 1))
        out += (
            "\n\n=== 现在是什么时候 ===\n"
            f"第 {day} 天 · {slot}\n"
            "suggestions 里别和它拧着来：这一刻已经是上面这个时段了，"
            "不要写「明天早上再去」「等天黑了动手」这种把眼下当成别的时候的话。\n"
        )
    if locations:
        out += (
            "\n\n=== 这一带有哪些地方 ===\n"
            + "、".join(locations) + "\n"
            "**只有这些地方存在。** 提到地名时照抄上面的原名，一个字都不要改，"
            "也不要自己造一个——玩家照一个不存在的地名走不过去。\n"
            # 模板里那句「地点的清单你看不到」现在不成立了，但它说的是 kind 的事：
            # 这份名单是拿来把地名**写对**的，不是拿来出 move 那一档的。
            # 改模板对覆写用户是静默失效，所以在这儿把话说全
            "这份名单是让你把地名写对用的，suggestions 的 kind 仍然只有"
            " free 和 item 两种——想让玩家去某个地方，就写成 free。\n"
        )
    if not movable:
        return out
    rows = "".join(
        f"{n.name} 现在在 "
        f"{'已离开（不在任何地方）' if npc_away(sess, n.id) else npc_place(n, sess.slot, sess.npc_places, sess.npc_followers, sess.location) or '行踪不明'}\n"
        for n in movable
    )
    return out + (
        "\n\n=== 人物位置 ===\n"
        "这段剧情里**真的换了地方**的人（被叫来、跟着走、被带走、回自己屋），"
        "在输出里加一个 npc_places：\n"
        + rows
        # 地名单只在上面那一段列一次：同一份白名单在提示词里出现两遍，改起来
        # 迟早只改一处，两份说法打架时模型听哪一份没人说得清
        + ("地名只能从上面「这一带有哪些地方」里挑。\n" if locations else "")
        + '{"npc_places": {"赫敏": "校长办公室"}}\n'
        '她只是回到自己平时待的地方，就写空串 ""，系统会按作息表替她算。\n'
        f'正文写她离开了、又没说去哪，就写 "{AWAY}"：她从此不在任何地方，直到剧情写她回来（那时照常写地名）。\n'
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

# 每一格概要的**硬**上限，字数。模板里那句「500 字以内」是撑不住的：这是累积式
# 概要，模型手里那份旧的可能已经一千多字，外加一句「不要丢掉旧信息」，出来就是
# 一千多字。真实存档里实测过 1518 字和 1431 字的格子，提示词一次都没拦住。
# 所以闸得在引擎这边。两份数（这里和模板）要一起改
SUMMARY_CHARS = 500


def _clip_summary(text: str) -> str:
    """把概要截到 SUMMARY_CHARS 字，尽量落在句号上。

    **切尾巴、留开头**，看着反直觉，但对着架构看是对的：这一格概要只覆盖
    `thread_upto` 之前的消息，之后的仍然以原文发出去——所以尾巴上那段新事在
    上下文里还有另一份，而开头那段旧事除了这份概要哪儿都没有（履历只注入
    最后 5 条）。切尾巴是切掉重复的那一份。

    半句话比没有还糟（同 EFFECT_CHARS 那句）：模型下一轮会把读到的半句当成
    事实往长里写。落不到句号上就补个省略号，至少看得出这儿断了。
    """
    body = text[:SUMMARY_CHARS].rstrip()
    if len(text) <= SUMMARY_CHARS:
        return body
    head = max(body.rfind(mark) for mark in "。！？\n")
    return body[:head + 1] if head >= SUMMARY_CHARS // 2 else body + "…"


# 一个格子留几条历史。24 条约等于 6 个游戏日（4 格制），够回看一阵。
# 这个数不是凭手感定的，是被存档体积逼出来的：AUTO_SAVE_KEEP 是 30，而每个
# 快照都带一份完整的 summary_log，十来个格子 × 24 条 × 500 字 × 30 个档已经
# 是几 MB 一局。要再往上加，先想清楚快照那头
SUMMARY_LOG_KEEP = 24


def _log_summary(rows, sess: RpgSession, text: str, last_id: int) -> list[dict]:
    """把这一次压出来的概要记进历史。**按 (day, slot) 覆盖，不是一次折叠一条。**

    一格里会折好几次（第 12 局玩家那格 225 条消息折了近 200 次），每次都留一份
    500 字的全文重写，存档表立刻就撑不住。按格覆盖之后它跟着**游戏内格数**长，
    不跟着消息数长——第 9 天满打满算也才几十条。

    覆盖而不是追加，等于「这一格的记忆最后长成什么样」。同一格里中间那几个
    版本丢掉不可惜：它们说的是同一段剧情，只是压到的原文一次比一次多。

    满了按**保新弃旧**（同 chronicle 的口径）：旧的那几格早就被当前那份概要
    吸收进去了，而最近几格才是玩家想核对的。
    """
    row = {
        "day": int(sess.day or 1),
        "slot": (sess.slot or "").strip(),
        "upto": int(last_id),
        "text": text,
    }
    kept = [
        r for r in (rows or [])
        if isinstance(r, dict)
        and (r.get("day"), r.get("slot")) != (row["day"], row["slot"])
    ]
    return (kept + [row])[-SUMMARY_LOG_KEEP:]


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
        return _clip_summary((text or "").strip())

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
        log = dict(sess.summary_log or {})
        # 玩家那格也记在局部变量里，不往 sess 上写：ORM 对象一脏，下面那次
        # execute 前的 autoflush 就会带着 onupdate 把 updated_at 顶掉
        player_summary, player_upto = sess.summary, sess.summarized_upto_id
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
                player_summary, player_upto = text, job["last_id"]
            else:
                summaries[job["slot"]] = text
                pointers[job["slot"]] = job["last_id"]
            log[job["slot"]] = _log_summary(
                log.get(job["slot"]), sess, text, job["last_id"],
            )
            wrote = True
        if not wrote:
            return False
        # 不走 ORM 提交，手写 UPDATE 并把 updated_at 原样写回：它和结算并排跑
        # （见 run_turn），而结算拿 updated_at 当「这期间没人动过这局」的凭据，
        # 被 onupdate 顶一下就会误报冲突、整轮结算作废。概要不在 STATE_FIELDS 里，
        # 本来就不该算「改过这局的状态」
        await store.execute(
            update(RpgSession).where(RpgSession.id == session_id).values(
                summary=player_summary,
                summarized_upto_id=player_upto,
                thread_summaries=summaries,
                thread_upto=pointers,
                summary_log=log,
                updated_at=RpgSession.updated_at,
            ).execution_options(synchronize_session=False)
        )
        await store.commit()
    return True


# ── ⑨ AI 调度：没被提到的角色自己过日子 ───────────────────────────────────

# 调度那次调用的上限。**必须有**：底层 httpx 客户端没设超时，于是 OpenAI SDK
# 退回它自己的默认值（read 600s × 最多 3 次尝试），单次调用能合法占住半小时。
# 它跑在 exclusive_session 的租约里、心跳会一直替它续期，卡住的不只是这一下，
# 而是整局——玩家再点什么都是 409。
#
# 写死 60 秒不做成配置项：它是「一两句背景描写」的快模型调用，实测个位数秒级。
# 真超了 60 秒，等下去也不会更好，宁可这一格没人动
AUX_CALL_TIMEOUT = 60

# 模型被要求「没什么可写就输出无」时可能给出的各种写法
_NONE_WORDS = {"无", "無", "none", "无。", "（无）", "(无)", "没有", "-"}

# 一次调用写完所有闲着的角色，所以给得比单人一句宽
ACTIVITY_MAX_TOKENS = 500
# 模组开了幕后往事时多给的那一截：一条相遇行比一句近况长两三倍
ENCOUNTER_EXTRA_TOKENS = 300
# 一次调度最多认几条相遇。整局人少的时候两条就够一屋子人配对；不封顶的话
# 模型会把每个同处一地的人两两配一遍，一格里冒出五六件幕后事
ENCOUNTER_MAX = 2
# 给调度看的「这几个人之间此前发生过的事」，每对人取最近几条。续写要有上文，
# 但它看的是便宜档，全量喂进去是浪费
ENCOUNTER_HISTORY = 3
# 给模型看的「最近一段剧情」长度。只为对齐时间轴，不给它全文
ACTIVITY_RECENT_CHARS = 300

# 「她答应了等你」这类话里会出现的词。近况里撞上任意一个，随机移动这一格就
# 跳过她——**光靠提示词拦不住**：随机移动是引擎在调模型**之前**就写进
# npc_places 的，等模型开口时人已经挪走了，它再听话也只能照新地点编。
#
# 为什么是关键词而不是一个正经的「承诺」字段：结算那边已经有 promise 这个
# 事件类型，但它落在 rpg_messages 的报告里、是给检索用的流水，没有「这个约
# 到什么时候失效」可言。真要做成字段，得让模型判「这句话算不算一个约、管几个
# 时段」——那是一次新的语义判断，判错的代价是把人锁死在原地不动。
#
# **只认「在原地等你」这一种约，不认所有承诺。** 从前「答应」「说好」「承诺」
# 「保证」也在表里，可这几个词底下的约大半和位置无关：「答应过下周陪你去看房」
# 「保证不再喝酒」「答应帮你带包烟」——近况是结算长期写进去的一张表，这类句子
# 一挂就是几十格，于是她从此再也不动，而且侧栏上没有任何说明。
# 这道闸门防的本来就是「刚答应等你回来就跑了」，判据该是「她这会儿该待着不动」，
# 不是「她欠着你一件事」。
#
# ponytail: 关键词匹配，天花板是两头都不准——换个说法会漏（漏了只是回到她照旧
# 被挪走，不锁死谁），而一句「答应了等你毕业」这种长期的约仍旧会一直拦着她，
# 直到结算把那条近况写成 null（提示词里有这条规矩）。真要更准就得让模型判
# 「这个约管几个时段」，那是一次新的语义判断，判错的代价正是锁死
_PROMISE_HINTS = ("等你", "等着", "在等", "等我")


def _has_promise(sess, npc_id: int) -> bool:
    """她近况里有没有「在原地等你」这类还没了结的约。"""
    notes = (sess.npc_notes or {}).get(str(npc_id)) or {}
    if not isinstance(notes, dict):
        return False
    text = "".join(f"{key}{value}" for key, value in notes.items())
    return any(hint in text for hint in _PROMISE_HINTS)


# 两个闲人碰到一处之后，先一起待满几格再各自照常挪。不设的话随机抽签会在
# 他们碰上的下一格就把两人拆开，「幕后往事」里写的那场相遇根本来不及发生
NPC_TOGETHER_SLOTS = 2


def _together_hold(sess, idle: list) -> set[int]:
    """记下这一格谁和谁在同一处，返回因为「刚碰上」这一格不挪的人。

    账本是 sess.npc_together：{"3-7": {"count": 已一起过的格数, "last": "天|时段"}}。
    同一格只记一次（last 去重），分开了就删，所以 count 数的是「连着在一处」。
    按对记而不是按地点记：第三个人走进来，他和原先两人都是新的一对，三人一起再待满。

    跟着玩家的人不算：他们的位置就是玩家的位置，那是「和你在一起」。
    这一格有一头不在 idle 里（在你跟前、已离开）的那对判不了，原样留着——
    删掉的话你跟她说完话，她回去又得重新陪那个人待两格。
    random 和 ai 两种模式都走这里：被拦下的人 destinations 为空，模型那边就是「不准动」。
    """
    followers = set(sess.npc_followers or [])
    here = (sess.location or "").strip()
    groups: dict[str, list[int]] = {}
    for n in idle:
        if n.id in followers:
            continue
        place = norm_name(npc_place(n, sess.slot, sess.npc_places, sess.npc_followers, here) or "")
        if place:
            groups.setdefault(place, []).append(n.id)
    mark = f"{max(1, sess.day or 1)}|{(sess.slot or '').strip()}"
    old = dict(getattr(sess, "npc_together", None) or {})
    idle_ids = {n.id for n in idle}
    ledger = {
        key: row for key, row in old.items()
        if not {int(part) for part in key.split("-")} <= idle_ids
    }
    held: set[int] = set()
    for ids in groups.values():
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                key = f"{min(a, b)}-{max(a, b)}"
                row = old.get(key) or {"count": 0, "last": ""}
                if row.get("last") != mark:
                    row = {"count": int(row.get("count") or 0) + 1, "last": mark}
                ledger[key] = row
                if row["count"] < NPC_TOGETHER_SLOTS:
                    held |= {a, b}
    sess.npc_together = ledger
    return held


def _meetings(met: list[str], idle: list, npcs: list, moves: dict[int, str],
              where_now: dict[int, str], sess: RpgSession) -> list[tuple]:
    """把调度写的相遇行核一遍，返回 (甲, 乙, 地点, 发生了什么, 关系标签, 撞见的人)。

    一行是「甲＋乙｜地点｜发生了什么｜关系标签」，标签可以不写。**碰没碰上由引擎
    说了算**：两人这一格挪完之后（moves 优先，没挪的看 where_now）必须落在同一处，
    而且那一处不是玩家所在的地方——玩家就站在那儿的话，这件事该由正文来写，
    不是幕后。对不上的整行丢，理由同近况那几条：不报 warning。

    撞见的人不问模型：同一格落在同一处的第三个人，引擎自己就知道。
    """
    here = norm_name(sess.location or "")
    final = {n.id: moves.get(n.id) or where_now.get(n.id) or "" for n in idle}
    # 没被调度的人也会在场撞见。跟着玩家的、在玩家跟前的，落在 here，下面那道就排掉了
    for n in world_npcs(npcs):
        if n.id not in final:
            final[n.id] = npc_place(n, sess.slot, sess.npc_places, sess.npc_followers,
                                    (sess.location or "").strip()) or ""
    people = {n.id: n for n in world_npcs(npcs)}
    out: list[tuple] = []
    seen: set[tuple[int, int]] = set()
    for body in met:
        segs = [s.strip() for s in body.replace("|", "｜").split("｜")]
        if len(segs) < 3:
            continue
        pair = [s.strip('"“”「」『』*_#>【】[]（）() 　') for s in re.split(r"[＋+]", segs[0])]
        if len(pair) != 2:
            continue
        a, b = match_npc(pair[0], idle), match_npc(pair[1], idle)
        what = segs[2].strip('"“”「」『』')
        if a is None or b is None or a.id == b.id or not what or what.lower() in _NONE_WORDS:
            continue
        key = tuple(sorted((a.id, b.id)))
        spot = norm_name(final[a.id])
        # 模型写的地名只用来对账，存的是引擎算出来的那个——两边写法（全称/简称）
        # 可能不一样，而侧栏和地点表认的是登记名
        if (key in seen or not spot or spot == here or norm_name(final[b.id]) != spot
                or not (norm_name(segs[1]) and norm_name(segs[1]) in spot)):
            continue
        label = re.sub(r"^关系\s*[：:]\s*", "", segs[3]).strip() if len(segs) > 3 else ""
        witnesses = [people[i] for i, place in final.items()
                     if i not in key and i in people and norm_name(place) == spot]
        seen.add(key)
        out.append((a, b, final[a.id], what, label, witnesses))
        if len(out) >= ENCOUNTER_MAX:
            break
    return out


def _move_mode(npc, module) -> str:
    """这个人的去处怎么挑。角色自己选过就听角色的，没选（""）跟随模组。"""
    return (getattr(npc, "move_mode", "") or "") or module.npc_move_mode


async def idle_npc_activities(
    session_id: int, engaged_ids: set[int], *, from_clock: bool = False,
    same_slot: bool = False,
) -> dict[str, str]:
    """给这一轮没被提到的、勾了「AI 调度」的角色各记一句「最近在做什么」。

    engaged_ids 是这一轮注入过设定的那批人（在场 + 被提到的），由调用方从
    build_rpg_messages 的 diag 里取。他们这一轮归叙事模型管，不该再被调度器
    另写一份——两边各写一遍，玩家下回见面时听到的会和自己刚经历的对不上。

    from_clock = 这一次是玩家按「结束时段」推来的，不是一个回合。两条路上
    「最后一条正文」的含义不一样，见下面 protected_ids 那一段。

    same_slot = 这一轮时段没翻篇，玩家在这一格里接着说话/行动，不在跟前的人
    也接着过这一格：**只续写，不挪人、不写相遇**。换地方和相遇仍然一格最多一次，
    只在翻篇时发生——每轮都能挪的话一个时段里她能来回跑好几处。

    **一次调用写完所有人**，不是一人一次：勾了调度的角色可能有一屋子，
    一人一次的话玩家每轮要为 N 次调用付钱、等 N 次往返。

    **谁准动是引擎的事，去哪儿是模型的事**，这条分界是有来由的。原先两头都在
    引擎：去处由 `random.choice` 在候选里抽一个，它没有任何是非判断——厕所、
    女子浴室和公园在它眼里等价，于是真实存档里出现过「她被挪到菜市场厕所」。
    模型手上有她的人设、近况和前几轮正文，挑得出说得通的地方。
    反过来「谁准动」不能交出去：跟着你的人、许过约的人、站在你跟前的人、
    时段不对的人，判错的代价是她当着玩家的面凭空消失或者当场毁诺。

    还有三件事是刻意不做的，写在这里免得后来改的人顺手加上：
    - **不让模型自己编地名**。去处只能从这个人的白名单里挑（`destinations`），
      对不上就当它没写——凭空一个地名会让侧栏显示玩家走不过去的地方。
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
        # 已离开的人不归调度管：她不在任何地方，挪她、给她写近况都等于替剧情把她带回来。
        # **例外是「随机强制」的人**：作者选那个模式就是要引擎替她抽去处，抽中了就
        # 等于引擎把她带回来了。抽不中的（时段不对、许过约、白名单一个地方都对不上）
        # 仍然不在——下面挑完去处之后再把这些人筛出去
        idle = [
            n for n in world_npcs(npcs)
            if n.ai_scheduled and n.id not in engaged_ids
            and (not npc_away(sess, n.id) or _move_mode(n, module) == "random")
        ]
        if not idle:
            return {}
        last = (await store.execute(
            select(RpgMessage)
            .where(RpgMessage.session_id == session_id, RpgMessage.role == "assistant")
            .order_by(RpgMessage.id.desc())
            .limit(1)
        )).scalars().first()
        # 玩家上一格发的那句。**和上面那条正文是两件事**：`last` 是模型写的一段
        # 叙事，而这一条是玩家自己的意图（「我去公司」「在家等她回来」），正文
        # 常常只把它演成一句环境描写。按「结束时段」不产生新消息，于是连按几格
        # 时 recent 一直是同一段、调度每次拿到的输入几乎一样——它当然每次都写
        # 出差不多的东西。玩家那句是这里唯一还带着新信息的东西。
        #
        # 没有 day/slot 列可以按格子查（rpg_messages 只有 location/present），
        # 拿的是「最后一条 user」。两条推格子的路上它都正好落在刚结束那一格里：
        # 时钟那条路不写消息，回合那条路里刚处理完的这一条属于将要结束的这格
        said = (await store.execute(
            select(RpgMessage)
            .where(RpgMessage.session_id == session_id, RpgMessage.role == "user")
            .order_by(RpgMessage.id.desc())
            .limit(1)
        )).scalars().first()
        # 跟着走的人永远不挪。**正文里点过名的人只在回合那条路上不挪**：
        # 那时 last 就是刚生成的这一轮，「刚露过面的人别凭空瞬移」成立。
        # 按时钟不产生正文，last 会一直停在同一条，连按几格护的都是同一批人，
        # 于是勾了随机移动的人一次都动不了。真正还在场的人由下面「站在玩家
        # 位置上的不挪」那道兜住，这条路上不需要再拿正文当挡箭牌
        protected_ids = set(sess.npc_followers or [])
        if not from_clock:
            protected_ids |= {
                npc.id for npc in named_npcs(npcs, last.content if last else "")
            }
        slot = (sess.slot or "").strip()
        places = dict(sess.npc_places or {})
        random_places = dict(getattr(sess, "npc_random_places", None) or {})
        location_changed = False
        # 随机移动只在配置的时段、配置的地点里生效；出了这个范围就撤销随机覆盖，
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
            # 同 rpg_state._clear_expired_random_places，共用一个判据：连白名单
            # 一起判（地点被划掉就当场过期），但一格作息表都没排过的人出了可移动
            # 时段不清——她没有排期可落回，清掉只会让她瞬移回常驻地
            if random_place_expired(npc, slot, marked):
                places.pop(key, None)
                random_places.pop(key, None)
                location_changed = True
        sess.npc_places = places
        sess.npc_random_places = random_places
        # 刚和别人碰上的先不挪，一起待满 NPC_TOGETHER_SLOTS 格再说。
        # 排在上面那段清理之后：过期的随机位置已经撤掉，算出来的才是她此刻真正在哪儿
        together_before = dict(getattr(sess, "npc_together", None) or {})
        held = _together_hold(sess, idle)
        movable = [
            npc for npc in idle
            # 这一步只问「准不准动」，去哪儿下面挑，所以不传 place
            if not same_slot
            and random_movement_ok(npc, slot) and npc.id not in protected_ids
            and npc.id not in held
            # 许过约的人不挪。她答应等你回来吃午饭、你一按结束时段她就被扔到
            # 公园去，那个约当场作废，而玩家看到的是她莫名其妙毁诺
            and not _has_promise(sess, npc.id)
            # 站在玩家跟前的人不挪——挪走等于当着他的面凭空消失。
            #
            # **只在回合那条路上判**。时钟这条路上 sess.location 是「按下按钮的
            # 那一刻玩家在哪儿」，而玩家紧接着就会走动：真实存档里他和妻子都在
            # 家，按一下结束时段，调度当场判同场、跳过她，然后他去了公司——
            # 她就此留在家，而下次推时段他要是又在家，同一件事再来一遍。
            # 这一格结束之后玩家人都走了，「当着他的面消失」那个理由不成立。
            #
            # 跟着走的人仍然护着：他们在 protected_ids 里（npc_followers），
            # 那一层判的是「她这一格还跟着你」，不是一个马上要失效的位置相等
            and (
                from_clock
                or not norm_name(sess.location or "")
                or norm_name(npc_place(npc, sess.slot, sess.npc_places))
                != norm_name(sess.location)
            )
        ]
        # 每个准动的人各自的候选地点。模型在这份名单里挑，挑不中就不动——
        # 白名单整张对不上（地点改名/删了）时这个人的名单为空，等于不准动，
        # 比「退回全量地点表」安全（那是个不报错的静默破功）
        destinations: dict[int, list[str]] = {}
        # 模组选了「随机强制」时引擎替她抽中的地方。在这里面的人这一格**一定**
        # 换地方，模型只编她在那儿干什么（见 RpgModule.npc_move_mode）
        forced: dict[int, str] = {}
        # 整张地点表。**不再只在有人准动时才查**：下面解析那一步也要用它来认出
        # 「句子里提到的是一个真地方」——她在物业办公室、近况却写她在内衣店挑料子，
        # 靠的就是这张表把「内衣店」认成地名而不是一句闲话
        locations = list((await store.execute(
            select(RpgLocation).where(RpgLocation.module_id == module.id)
        )).scalars().all())
        all_names = list(dict.fromkeys(
            place.name.strip() for place in locations if (place.name or "").strip()
        ))
        if movable:
            names = all_names
            for npc in movable:
                current = npc_place(npc, sess.slot, sess.npc_places)
                pool = [name for name in names if random_movement_ok(npc, slot, name)]
                # 排掉她此刻所在的地方：留着的话「原地不动」和「挑中了这里」
                # 在落库那一步没有区别，而前者本来就该零写入
                spots = [name for name in pool if norm_name(name) != norm_name(current)]
                if spots and _move_mode(npc, module) == "random":
                    # 抽签没有是非判断（本函数开头那段），这是作者明知这一点
                    # 选的：顺着人设挑，她永远只在那几个地方转。白名单照旧是
                    # 她自己那份，不合适的地方由作者从可去地点里划掉。
                    # destinations 只留抽中的那一个，下面解析那一步照常认地名
                    pick = random.choice(spots)
                    destinations[npc.id] = [pick]
                    forced[npc.id] = pick
                elif spots:
                    # **候选顺序每次都洗一遍。** 白名单是按模组的地点表排的，
                    # 每一格给模型的是同一份、同一个顺序的名单，而它手上另外
                    # 那几样（人设、位置、上次那句）也几乎不变——于是它每次都挑
                    # 同一个，玩家看到的就是「一直在那几个地方」。这不是模型
                    # 的毛病：同样的输入本该得到同样的输出，随机性得由我们给。
                    #
                    # 洗顺序而不是替它抽一个：抽签抽不出「厕所和公园不一样」，
                    # 那正是当初把 random.choice 拿掉的理由（见本函数开头）。
                    # 洗完仍然是它按人设挑，只是不再有个天生排第一的。
                    random.shuffle(spots)
                    destinations[npc.id] = spots
        if location_changed or sess.npc_together != together_before:
            await store.commit()
        # 已离开的人只有真被抽中去处时才算回来（见上面 idle 那一段）。没抽中的这一格
        # 还是不在任何地方：留在名单里模型会照常给她写一句近况，那就是在「她不在任何
        # 地方」的同时又说她在某处干什么
        idle = [n for n in idle if n.id in forced or not npc_away(sess, n.id)]
        if not idle:
            return {}
        # 每个人此刻在哪儿。算一次给三处用：名单里的 place、下面「蹲了几格」
        # 的计数、以及落库时给流水记的那个位置——各算一遍必然漂移
        where_now = {
            n.id: npc_place(
                n, sess.slot, sess.npc_places, sess.npc_followers,
                (sess.location or "").strip(),
            ) or ""
            for n in idle
        }
        # 幕后往事那一段要的上文：这几个闲人之间此前的关系和发生过的事。
        # 只挑两头都在这批人里的——一头在玩家跟前的那对，这一格根本碰不上
        encounters = bool(module.npc_encounters) and len(idle) >= 2 and not same_slot
        idle_ids = {n.id for n in idle}
        by_id = {n.id: n for n in idle}
        bonds, past, together = [], [], []
        if encounters:
            bonds = [
                f"{by_id[r['a']].name}和{by_id[r['b']].name}：{r.get('label')}"
                for r in (sess.npc_bonds or [])
                if isinstance(r, dict) and r.get("a") in idle_ids and r.get("b") in idle_ids
            ]
            past = [
                f"第{r.get('day')}天{r.get('slot') or ''}，{by_id[r['a']].name}和{by_id[r['b']].name}"
                f"在{r.get('place') or '某处'}：{r.get('content')}"
                for r in (sess.npc_offscreen or [])
                if isinstance(r, dict) and r.get("a") in idle_ids and r.get("b") in idle_ids
            ][-ENCOUNTER_HISTORY * 2:]
            groups: dict[str, list[str]] = {}
            for n in idle:
                # 被强制挪的人按抽中的地方分组：她这一格就在那儿，
                # 碰不碰得上要按挪完之后算（_meetings 也是这么核的）
                place = forced.get(n.id) or where_now.get(n.id) or ""
                if place:
                    groups.setdefault(place, []).append(n.name)
            together = [f"{place}：{'、'.join(names)}" for place, names in groups.items() if len(names) > 1]
        prompt = render(
            "rpg_activity.jinja2",
            continuing=same_slot,
            encounters=encounters,
            bonds=bonds,
            past=past,
            together=together,
            day=max(1, sess.day or 1),
            slot=(sess.slot or "").strip(),
            location=(sess.location or "").strip(),
            recent=((last.content or "")[-ACTIVITY_RECENT_CHARS:] if last else "") or "（故事刚开始）",
            # 玩家那句取头不取尾：他的输入是「我去公司待一天」这样一句意图，
            # 重点在开头，长的那种后面跟的是细节。正文相反（尾巴才是刚发生的），
            # 所以上面那条切的是尾
            said=(said.content or "").strip()[:ACTIVITY_RECENT_CHARS] if said else "",
            npcs=[
                {
                    "name": n.name,
                    "place": where_now.get(n.id) or "行踪不明",
                    # 她在那个地方连着待了几格。**这是名单里唯一一个量化的
                    # 「该换地方了」**：模板里「默认让他挪」是个形容词，而模型
                    # 顺着人设推，最说得通的永远是留在原地（见下面 last_place）。
                    # 真实存档里韩曼宁早晨禁动 → 整个早晨在家 → 中午那次调度
                    # 看到的是「在家 + 在家擦灶台」，于是它接着写在家，下午再来
                    # 一遍：一条自我延续的链，起点是配置，后面几节是模型接的。
                    # 1 不给（刚换过地方，没有压力可言），模板据此条件渲染
                    "stuck": slots_in_place(sess, n.id, where_now.get(n.id, "")),
                    # 人设整份给，**不再夹 60 字**：模板要它「写出来必须像他的
                    # 性格」，可真实模组里人设 135~331 字，夹到 60 只剩开头那半句
                    # 身份介绍，性格、习惯、忌讳全在后面被切掉——它凭那半句写出来
                    # 的东西谁都像。整份给的代价是这份名单变长，而这次调用的
                    # 上限是 500 token 的**输出**，输入这边本来就宽（整个 prompt
                    # 原先才 1900 字上下）
                    "persona": (n.persona or n.description or "").strip(),
                    "activity": npc_activity(sess, n.id),
                    # 她跟玩家待过时结算记下的最后一条经历（正文里真发生过的）。
                    # 不给的话调度只看得见她上次离开时那句，写出来像那件事没发生过
                    "lived": next((
                        str(row.get("content") or "").strip()
                        for row in reversed((sess.npc_history or {}).get(str(n.id)) or [])
                        if isinstance(row, dict) and str(row.get("content") or "").strip()
                    ), ""),
                    # 引擎上次替她挑的那个地方（`npc_random_places` 本来就记着，
                    # 不用新存一份）。**给了它模型才有理由换地方**：洗牌只是
                    # 去掉「天生排第一」，可她此刻就在上次那个地方，模型照着
                    # 人设推，最说得通的往往还是留下——一直在那几个地方的另
                    # 一半原因在这儿。空 = 这一格是她第一次被挪，或上次没动
                    "last_place": str((getattr(sess, "npc_random_places", None) or {}).get(str(n.id)) or ""),
                    # 她眼下的近况。**必须给**：结算把「答应了等你回来吃午饭」
                    # 这类承诺记在这儿，而调度不读正文——不给的话它只知道她的
                    # 性格和位置，于是理直气壮地写一句和刚许的诺冲突的话。
                    # 夹 60 字：整张近况表能长到几百字，它会把这份名单撑爆
                    "notes": "；".join(
                        f"{k} {v}" for k, v in ((sess.npc_notes or {}).get(str(n.id)) or {}).items()
                    )[:60],
                    # 她这一格准去的地方。空 = 不准动（没勾随机移动、时段不对、
                    # 跟着你、许过约、就站在你跟前），模板据此换一套写法
                    "destinations": destinations.get(n.id, []),
                    # 引擎替她抽中的去处，非空时模板不给「可去」，只告诉模型她已经去了那儿
                    "forced": forced.get(n.id, ""),
                }
                for n in idle
            ],
        )
        model_ref = module.activity_model_ref or module.fast_model_ref

    try:
        model, api_format = llm_client.get_agent_client("memory", model_ref)
        text = await asyncio.wait_for(
            llm_client.dispatch_chat_complete(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                api_format=api_format,
                temperature=0.9,
                max_tokens=ACTIVITY_MAX_TOKENS + (ENCOUNTER_EXTRA_TOKENS if encounters else 0),
            ),
            timeout=AUX_CALL_TIMEOUT,
        )
    except TimeoutError:
        # 单独一条、而且只是 warning：超时不是缺陷，是这一格不值得再等下去。
        # 混在下面的 exception 里只会看到一段没有信息量的 CancelledError 栈。
        # **去处也跟着一起丢**：它和活动是同一次调用的两半，模型没开口就等于
        # 这一格没人动——过期清理那一步已经提交了，那部分不受影响
        # （test_..._survives_..._failure 钉的）
        logger.warning("RPG 局 %s 角色调度超时（%s 秒）", session_id, AUX_CALL_TIMEOUT)
        return {}
    except Exception:
        logger.exception("RPG 局 %s 角色调度失败", session_id)
        return {}

    # 模型写的是名字，落库要的是 id。名字对不上就整行丢掉——**不报 warning**：
    # 这是玩家没要求过的后台动作，为它的瑕疵打断他一轮剧情不划算
    updates: dict[str, str] = {}
    moves: dict[int, str] = {}
    met: list[str] = []
    for raw in (text or "").splitlines():
        line = re.sub(r"^\s*(?:[-*•]\s*)?(?:\d+\s*[.、)）]\s*)?", "", raw).strip()
        if not line:
            continue
        # 相遇行先摘出来，等所有人的去处都定了再核（见下面 _meetings）。
        # 必须拦在按冒号拆之前：它的名字段是「甲＋乙」，落进下面那条路只会被丢掉
        found = re.match(r"^[*【\[]*相遇[*】\]]*\s*[：:]\s*(.+)$", line)
        if found:
            if encounters:
                met.append(found.group(1))
            continue
        # 全角冒号是模板要求的写法，半角是模型自己换的，两种都收
        parts = re.split(r"[：:]", line, maxsplit=1)
        if len(parts) != 2:
            continue
        # 名字两头的装饰一律削掉。**星号和方括号必须在内**：模型写
        # 「**韩曼宁**：…」「【韩曼宁】：…」是常态（Markdown 强调、剧本体），
        # 而从前只削引号，于是名字段成了「*韩曼宁**」，match_npc 认不出来，
        # 整行丢掉——她这一格既没换地方也没有近况，界面上一句解释都没有
        who = match_npc(parts[0].strip().strip('"“”「」『』*_#>【】[]（）() 　'), idle)
        says = parts[1].strip().strip('"“”「」『』')
        if who is None or not says:
            continue
        # 准动的人那一行是「名字：地点｜做什么」。竖线两侧都要有东西，
        # 缺一半就当它只写了活动——半句话不该换来一次位置改动
        spots = destinations.get(who.id) or []
        # **不准动的人写了竖线也要拆。** 从前这一问连 spots 一起判（没地方可去
        # 就不拆），于是「小区物业办公室｜溜进值班室翻看监控」整串连地名一起存进
        # 了近况。拆开之后那半句地名怎么处理见下面 hit is None 那一支——**不是
        # 削掉留句子**：削掉的话一句内衣店的话会落在物业办公室名下，那正是
        # 「一句话走两个地方」那条规矩禁的事
        bar = "｜" in says or "|" in says
        where = ""
        if bar:
            where, _, says = (says.replace("|", "｜")).partition("｜")
            where, says = where.strip(), says.strip()
            # 两头写反了也收：「在柜台前排队｜药店」。模板写的是「地点｜活动」，
            # 可模型时不时颠倒过来，而颠倒过来的行**两头都废**——地名那一侧
            # 对不上白名单于是不挪，活动那一侧存进去的是一个光秃秃的地名
            # （真实探针里近况就写着「药店」两个字）。判据是「哪一侧整个等于
            # 一个候选地名」：活动是一句话，不会恰好等于某个地名
            if not any(norm_name(name) == norm_name(where) for name in spots) \
                    and any(norm_name(name) == norm_name(says) for name in spots):
                where, says = says, where
        # 「赫敏：无」也算没写。不挡住的话角色卡上会挂一行「最近：无」，
        # 而且它会一直留在那儿，模型下一轮还照着它编。
        # **必须拦在下面挪人之前**：「赫敏：药店｜无」这一行位置改了、近况没写，
        # 于是她换了地方却没有一句话解释她在那儿干什么——半句话不该换来一次
        # 位置改动，这里和上面那条竖线是同一个道理
        if not says or says.lower() in _NONE_WORDS:
            continue
        if bar:
            # 地名只认白名单里的那几个。模型现编一个的话侧栏会显示它、
            # 地点总览里却找不到，玩家照提示走不过去
            hit = next((name for name in spots if norm_name(name) == norm_name(where)), None)
            if hit is None:
                # 模型爱把地名写短：模组里叫「情趣内衣店」，它写「内衣店」。
                # 只认全等的话这一行整个作废，她这一格就停在原处——真实白名单里
                # 一半地名都是三四个字的复合词，撞上这条的概率不低。
                #
                # 敢放宽是因为**候选池就是她自己那份白名单**（几个地名），不是
                # 全量地点表：短名只对上一个才算，对上两个就当没写。match_place
                # 不肯放这个方向（「藏经阁」→「藏经阁顶层」是凭空编造），那边的
                # 池子是整张地点表，这里不一样
                short = [
                    name for name in spots
                    if len(norm_name(where)) >= 2 and norm_name(where) in norm_name(name)
                ]
                hit = short[0] if len(short) == 1 else None
            if hit:
                moves[who.id] = hit
            elif norm_name(where) != norm_name(where_now.get(who.id, "")):
                # 拆出来的地名既不是一次合法移动、又不是她此刻所在的地方 → **整行丢掉**。
                # 真实存档第 12 局：结算把韩曼宁挪进了范建明的暗间（剧情写的位置，
                # 不是调度挪的），于是这一格她 spots 是空的，模型仍旧写了
                # 「情趣内衣店｜捏着蕾丝边料反复比量」。只削地名留句子的话，一句
                # 内衣店的话就落在物业办公室名下——侧栏和近况对不上，正是下面
                # 「一句话走两个地方」那条规矩禁的事。丢了这一格沿用上一句，
                # 陈旧但不自相矛盾。
                #
                # 地名**等于**她此刻所在地的不丢：那是「她决定留在原地」的另一种
                # 写法（模板让她这时别写地点，可它有时照写），句子和位置本来就对得上
                continue
        elif spots:
            # 竖线漏了、地名写进了句子里：「韩曼宁：在小区物业办公室翻看监控回放」。
            # 模板准她提自己「可去」里的地名，于是这种行看着完全合法，只是位置没跟着
            # 改——真实存档里侧栏写「在家」、近况写「在小区物业办公室翻看监控回放」。
            # 按字面处理（只记近况）就是那个 bug，所以照句子里的地名把她挪过去。
            #
            # 不会把「留在原地」误判成移动：`spots` 上面已经排掉了她此刻所在的地方，
            # 所以一句「在药店柜台后面抓药」对在药店的人来说匹配不到任何候选。
            # 两个以上候选地名同时出现，整行作废（见下面那个 elif）。
            #
            # **单字地名不参与**：这是纯字面包含，而「家」这种一个字的地名在
            # 「在管家房里整理」「回娘家路上」里随处命中，能把她挪到一个句子根本
            # 没提的地方去。竖线那条路不受影响（那是整名相等），漏了竖线又只有
            # 单字候选的话就退回「只记近况」——那正是修这个洞之前的样子
            named = [
                name for name in spots
                if len(norm_name(name)) >= 2 and norm_name(name) in norm_name(says)
            ]
            if len(named) == 1:
                moves[who.id] = named[0]
            elif named:
                # 两个以上候选地名同时出现 = 她这一句在赶路（「在商场中心逛了逛，
                # 又转到情趣内衣店门口看了几眼才回家」）。模板明令一句话只准写
                # 她所在那个地方能发生的事，所以这一行本来就不合规。
                # **整行丢掉，不是只丢位置**：留着近况的话侧栏写「在家」、近况写
                # 她逛商场，玩家看到的是两处对不上（真实存档第 12 局韩曼宁）。
                # 丢了她这一格沿用上一句，陈旧但不自相矛盾——同上面「无」那条
                continue
        # 句子里点着一个**登记过的地名**，而她既没往那儿挪、此刻也不在那儿 → 整行丢掉。
        # 上面那两支只拿她自己那份白名单比，于是白名单**外**的登记地名一路漏到这里：
        # 真实存档第 12 局「11 中午｜place=家｜在菜市场挑拣中午的青菜」——菜市场是
        # 登记地点，但她的白名单里只有菜市场厕所，于是位置不动、近况照存，侧栏写
        # 「在家」。判据用整张地点表（`all_names`），不是白名单。
        #
        # ponytail: 只认**全名**出现（两字以上），天花板是简称漏掉——上面那条真实
        # 记录写的是「菜市场」，而登记名是「菜市场摊位区」，这一条抓不住它。放宽到
        # 「登记名的任意子串」会连正当的句子一起误杀（她在家给公司打电话 → 撞上
        # 「公司」），而这里丢的是玩家看得见的一句近况。要更准就得判这个地名是不是
        # 她这句话的所在地，那是一次句法分析
        if who.id in forced:
            # 抽中的地方是定死的：句子里点着别的登记地名（还写她在家擦灶台、
            # 或者跑去了第三个地方），就是模型没照着写 → 整行丢掉，这一格不挪。
            # 不挪而不是照挪：挪过去配一句别处的话，侧栏和近况又对不上
            if any(
                len(norm_name(name)) >= 2
                and norm_name(name) in norm_name(says)
                and norm_name(name) != norm_name(forced[who.id])
                for name in all_names
            ):
                continue
            moves[who.id] = forced[who.id]
        if who.id not in moves and any(
            len(norm_name(name)) >= 2
            and norm_name(name) in norm_name(says)
            and norm_name(name) != norm_name(where_now.get(who.id, ""))
            for name in all_names
        ):
            continue
        updates[str(who.id)] = says
    meetings = _meetings(met, idle, npcs, moves, where_now, sess)
    if not updates and not moves and not meetings:
        return {}

    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        if sess is None:
            return {}
        for npc_id, place in moves.items():
            apply_npc_place(sess, npc_id, place, source="random")
        for a, b, place, what, label, witnesses in meetings:
            record_offscreen(sess, a, b, place, what, witnesses)
            set_npc_bond(sess, a, b, label)
        for npc_id, says in updates.items():
            # 这一格她落在哪儿，跟着流水一起记：原地不动是零写入，不记的话
            # 「她在这儿蹲了几格」谁也数不出来（见 rpg_state.slots_in_place）。
            # 取 moves 里刚挑的那个，没挪的人取 where_now 算出来的现位置
            apply_npc_activity(sess, int(npc_id), says,
                               place=moves.get(int(npc_id)) or where_now.get(int(npc_id), ""))
        await store.commit()
    return updates


# ── 帮我想想：玩家主动要三条建议 ──────────────────────────────────────────

# 给模型的最近剧情条数。**从前是 8**（约 4 个回合），而叙事模型看的是
# context_turns * 2（默认 40 条）：同一局里写正文的看得见四十条，编建议的只看
# 得见最后八条，于是三四个回合前埋下的线在建议里等于没发生过——玩家看到的就是
# 「建议和上下文不搭」。抬到 16（约 8 个回合）不跟着 context_turns 走，是因为
# 这一路的读者是便宜档，跟着作者那个数走会把它拖到四十条
SUGGEST_WINDOW = 16
# 剧情原文那一段的上限。**必须有**：窗口抬宽之后它是唯一没有闸的一块，
# 一轮一千字的模组能靠它一家把资料段全挤出模型的视野
SUGGEST_TRANSCRIPT_BUDGET = 2400


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

    # keep_end：超预算时切的是**最早**那几条。建议要贴的是眼前这一刻，
    # 丢掉开头远比丢掉刚刚发生的那一段划算
    transcript = truncate_to_token_budget("\n".join(
        f"{'你' if m.role == 'user' else 'GM'}：{m.content}" for m in recent
    ), SUGGEST_TRANSCRIPT_BUDGET, keep_end=True)
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
        # 0.7，**从前是 0.95**。高温本来是为了让三条别写成同一件事的三种说法，
        # 代价是它也会往剧情外面飘——而这是个必须贴着眼前这一段走的任务。
        # 「三条要拉开」现在由提示词里那句「拉开的是走向的不同」管着，
        # 比靠温度撞出来的差异靠得住
        temperature=0.7,
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
    opponent_override: str = "",
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
    # 每段耗时（秒），done 之前打一行日志。要改哪一段先看这一行，别凭感觉
    timings: dict[str, float] = {}
    mark = [time.monotonic()]

    def _lap() -> float:
        now = time.monotonic()
        spent, mark[0] = round(now - mark[0], 2), now
        return spent

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

    # 向量召回只吃玩家这句原话，不等裁决结果，所以在裁决之前就发出去，两次网络
    # 并排等。嵌入端点慢的时候（超时 20 秒）这一段原先整段压在首字之前。
    # 自己开一个会话：它只读模型库那一行，不碰本轮的写
    async def _vector_prefetch() -> list[str]:
        async with AsyncSessionLocal() as db:
            return await rpg_vectors.search(sess, module, content, db)

    vector_task = retain_task(asyncio.create_task(_vector_prefetch()))
    timings["prep"] = _lap()

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
                # 对手也是手选的。不给这条路一个入口的话，等级制下玩家只要
                # 用一次下拉框，就能把一次 -75 的对抗换成常规检定
                "opponent": opponent_override,
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
            # 手选的对手压过模型报的那个。那个下拉框的一半理由就是「模型没认出
            # 对手」时的人工兜底，让模型的空串盖掉它等于这一半白做
            if judgement and opponent_override:
                judgement["opponent"] = opponent_override

        if module.check_mode == "always" and judgement and not judgement["need_check"]:
            judgement["need_check"] = True
            judgement["attr"] = judgement["attr"] or _fallback_attr(module, stats)

    if judgement:
        if judgement["need_check"] and judgement["attr"]:
            judgement = apply_roll(module, sess, judgement, npcs)
        else:
            # 没有一项数值可判（模组还没定义），退回纯叙事
            judgement["need_check"] = False
        yield "adjudicate", {
            "need_check": judgement["need_check"],
            "attr": judgement["attr"],
            "band": judgement["band"],
            "intent": judgement["intent"],
            "reason": judgement["reason"],
            "opponent": judgement.get("opponent", ""),
        }
        if judgement["need_check"]:
            # 这两个 dict 是手写白名单，不是 judgement 本身。漏了对手的话，
            # 本轮那条判定条上不显示对手，刷新页面重读 row.roll 才有
            yield "roll", {
                "rate": judgement["rate"], "dice": judgement["dice"],
                "outcome": judgement["outcome"], "attr": judgement["attr"],
                "opponent": judgement.get("opponent", ""),
                "opposed_stat": judgement.get("opposed_stat", ""),
                "opposed_value": judgement.get("opposed_value"),
            }
        try:
            await _store_roll(session_id, user_message_id, judgement, aux_in, aux_out)
        except Exception:
            # 判定没存下不该拦住叙事：玩家已经看到结果了，这一轮照常写完
            logger.exception("RPG 局 %s 判定落库失败", session_id)
    timings["adjudicate"] = _lap()
    # 在开会话之前等：向量那一路慢的时候不白占一个数据库连接。
    # 这一段只记「比裁决多等了多久」，并排之后正常是 0
    vector_keys = await vector_task
    timings["vector_wait"] = _lap()

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
            mode, private_with, action_time=action_time, vector_keys=vector_keys,
        )
        # 外貌已经随这次上下文发出去了，就地记一笔，下一轮不再重复发。
        # 放在开流之前而不是之后：叙事失败也算见过，模型确实已经拿到过那段描写。
        # 只认 npcs_here：被提到一句的人这一轮也拿到了设定，但玩家并没见到他，
        # 记成见过会让他的外貌永远等不到该出现的那一次
        mark_met(fresh_sess, [n["id"] for n in diag["npcs_here"]])
        # 一次性词条也已经随这次上下文发出去了，就地记一笔。位置和理由同上一行：
        # 叙事失败也算放过，模型确实已经拿到过那段文字。想让它重来只有读档
        mark_fired(fresh_sess, [t["id"] for t in diag["triggered"] if t.get("once")])
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
    timings["context"] = _lap()

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
                if not buf:
                    timings["first_token"] = _lap()
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
    timings["writer"] = _lap()

    # 概要只读消息原文、不读结算结果，所以不必排在结算后面——跟结算并排跑，
    # 长局里几乎每轮都要压一次，原先这一次调用整段串在结算之后。
    # 能并排的前提是它落库时不碰 updated_at（见 _maybe_summarize 末尾）：
    # 结算靠 updated_at 判断「这期间有没有别人改过这局」，被它顶一下就会误判冲突。
    # 失败不吭声——玩家没要求过这件事，报错只会让他以为这一轮出了问题
    async def _summarize_quietly() -> None:
        try:
            await _maybe_summarize(session_id)
        except Exception:
            logger.exception("RPG 局 %s 概要生成失败，上下文退化为纯截断", session_id)

    summary_task = retain_task(asyncio.create_task(_summarize_quietly()))

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
    timings["settle"] = _lap()

    # 结算之后剩下的三件事彼此不读对方的产物，并排跑，玩家只等最慢的那一个：
    # 概要（上面已经开跑）、向量补写、AI 调度。它们落库的列互不相交
    # （概要那几列 / vector_upto_id / npc_places·npc_activities），
    # 每个都是「重新读一遍 → 只改自己那几列 → 提交」，SQLite 的写锁由 busy_timeout 排队。
    #
    # 向量补写要排在结算之后：这一轮的结算已经落库，事实才嵌得全。
    # 模组没配嵌入模型时这一句一次网络都不发；失败也不吭声（函数自己吞），
    # 召回退回 BM25 + 词面两路，玩家看不出区别
    #
    # AI 调度要知道这一轮提到了谁，那是 build_rpg_messages 算的。
    # **这是唯一一次「玩家说完话了还在调模型」**，所以它必须排在 done 之前——
    # done 之后前端就不再收了，玩家的侧栏会一直停在旧状态。
    # 没勾任何角色、或者勾了的都在场，这一次调用根本不发生。
    #
    # **每轮都调**，时段没翻篇也调：玩家在这一格里说话、行动，不在跟前的人也在
    # 接着过这一格。没翻篇时 same_slot=True，只续写一句「接下来在做什么」，
    # 不挪人、不写相遇——换地方和相遇一格最多一次，只在翻篇时发生。
    # 按「结束这个时段」按钮那条路不经过这里，调度补在 routes/rpg.py 的 advance_time 里。
    #
    # 时钟只可能被引擎那条路（吃格子的动作、行动预算攒满）和上面 scene_wrapped
    # 那条路推动，两处都落在下面这次比对里，所以推时段的地方不必各自回传标记
    async def _schedule() -> dict | None:
        try:
            async with AsyncSessionLocal() as store:
                scheduled_session = await store.get(RpgSession, session_id)
                clock_now = clock_before if scheduled_session is None else (
                    (scheduled_session.day or 1), (scheduled_session.slot or "")
                )
                payload = None if scheduled_session is None else _state_payload(scheduled_session)
            # diag 是这一轮注入过设定的人（在场 + 被提到的）。他们归叙事模型管，
            # 调度器另写一份会和玩家刚经历的剧情对不上
            # npcs_onstage 是「在场 + 被提到」，比 npcs_here 宽：被提到的人这一轮
            # 也拿到了设定，调度器再替他们编一份「今天在干什么」会和刚写的对不上。
            # 原先这里还要单独补一个 thread_id（线主），线没了——线主的定义本来就是
            # 「你正在跟她说话的那个」，而她已经在这份名单里了
            engaged = {int(n["id"]) for n in diag.get("npcs_onstage") or []}
            await idle_npc_activities(session_id, engaged, same_slot=clock_now == clock_before)
            async with AsyncSessionLocal() as store:
                scheduled_session = await store.get(RpgSession, session_id)
                if scheduled_session is not None:
                    payload = _state_payload(scheduled_session)
            return payload
        except Exception:
            logger.exception("RPG 局 %s 角色调度失败", session_id)
            return None

    # 概要那个 task 套 shield：玩家这时断开的话另外两件跟着取消（同原先），
    # 概要照样压完——它在租约的 retain 名单里，下一轮本来就要等它
    _, _, payload = await asyncio.gather(
        asyncio.shield(summary_task), rpg_vectors.sync_session(session_id), _schedule(),
    )
    timings["tail"] = _lap()
    # 这条 state 就算上面整段都跳过了也照发：它不只带「谁最近在做什么」。
    # tick_cooldowns 每轮都在减冷却、note_slot_chat 每轮都在加聊天数，而
    # skills / slot_chats 不在 STATE_FIELDS 里，结算那条 state 带不上它们——
    # 吞掉这一条，玩家会看到一颗明明已经能点的技能还灰着
    if payload is not None:
        yield "state", payload

    logger.info("RPG 局 %s 回合耗时 %s 合计 %.2fs",
                session_id, timings, sum(timings.values()))
    yield "done", {
        "message_id": message_id,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "aux_input_tokens": aux_in,
        "aux_output_tokens": aux_out,
    }
