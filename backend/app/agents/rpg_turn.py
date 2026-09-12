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
)
from app.services import llm_client
from app.services.context_budget import truncate_to_token_budget
from app.services.llm_json import call_json
from app.services.rpg_context import (
    DEFAULT_CHAR_NAME,
    SUMMARY_TOKEN_BUDGET,
    build_rpg_messages,
    here_npcs,
    history_window,
    named_npcs,
    npc_place,
    thread_summarized_upto,
    thread_summary,
    world_npcs,
)
from app.services.rpg_dice import DEFAULT_BAND, OUTCOME_LABELS, normalize_band, resolve_rate, roll
from app.services.rpg_prompts import render
from app.services.rpg_state import (
    OFFSCREEN_CHARS,
    OFFSCREEN_TAG,
    apply_inventory,
    apply_npc_activity,
    apply_relations,
    apply_state_delta,
    apply_stats,
    check_condition,
    check_zero,
    chronicle_lines,
    def_map,
    for_check_stats,
    mark_met,
    match_npc,
    norm_name,
    note_move,
    note_visited,
    npc_activity,
    push_chronicle,
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
# 结算时给模型看的剧情长度。太长会让它把早前的变化又报一遍
SETTLE_CHARS = 3000
# 结算时给模型看的大事记条数。只为防它把同一件事反复写进去，
# 不是让它接着往下编，所以只看最近几条
CHRONICLE_PROMPT_LINES = 10


# ── 对话线：一条线 = 一个 thread_id，NULL = 场面线 ─────────────────────────

def find_thread_npc(npcs: list[RpgNpc], thread_id: int | None) -> RpgNpc | None:
    if not thread_id:
        return None
    return next((n for n in npcs if n.id == thread_id), None)


def resolve_thread_id(
    sess: RpgSession, npcs: list[RpgNpc], thread_id: int | None, target_npc: str
) -> int | None:
    """这一轮归哪条线。None = 场面线。只在这里解析一次，别处不要重算。

    **不拿 target_npc 兼作线的键**：它管的是「这个动作用在谁身上」
    （relation_effects 加在谁头上），和「这段叙事归哪条历史」是两件事。
    在老兵线里对老板娘用动作是合法的。

    显式传了就用传的（认不出来算没有）；没传的话，**只有 target_npc 人就
    站在你面前**才归他。远处那个人照旧只吃动作的数值，叙事留在你所在的这条
    线上——否则「对不在场的人用动作」会被 thread_blocker 当场拒成 400，
    而那本来是个合法操作。
    """
    if thread_id:
        return thread_id if any(n.id == thread_id for n in npcs) else None
    who = next(
        (n for n in here_npcs(npcs, sess.location, sess.slot, sess.npc_places)
         if norm_name(n.name) == norm_name(target_npc)),
        None,
    )
    return who.id if who else None


def thread_blocker(sess: RpgSession, npcs: list[RpgNpc], thread_id: int | None) -> str:
    """角色线能不能收输入。返回拒绝理由，空串 = 放行。

    线主不在当前地点就整轮拒掉——历史照常可读，只是不给输入框。
    不拒的话线和历史就不再一一对应，之后每个查询都要考虑「线主不在这儿」
    的分支；堵在入口比散在各处便宜得多。
    """
    npc = find_thread_npc(npcs, thread_id)
    if npc is None:
        return ""
    where = npc_place(npc, sess.slot, sess.npc_places)
    if where != (sess.location or "").strip():
        return f"你得先回到{where or '他常在的地方'}，才能和{(npc.name or '').strip()}说话"
    return ""


def _thread_clause(thread_id: int | None):
    """SQL 过滤：这一条线的消息。NULL 和「空」在这里必须是同一个意思。"""
    col = RpgMessage.thread_id
    return col.is_(None) if not thread_id else col == thread_id


def _in_thread(message: RpgMessage, thread_id: int | None) -> bool:
    return (message.thread_id or None) == (thread_id or None)


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
        "flags": sess.flags or {},
        "location": sess.location or "",
        "npc_states": sess.npc_states or {},
        # GM 这一局记下的 NPC 近况：角色卡上那一块要跟着这一轮就更新
        "npc_notes": sess.npc_notes or {},
        # AI 调度给不在场的人记的「最近在做什么」，同理
        "npc_activities": sess.npc_activities or {},
        # 剧情把谁挪到哪儿了：带回去面板才认得出「她此刻就在你面前」，
        # 不带的话要等整页重新拉一次才动
        "npc_places": sess.npc_places or {},
        "status": sess.status,
        # 去过哪儿：地图的迷雾按它散开，不带的话要等整页重新拉一次才亮
        "visited": sess.visited or [],
        # 时钟也跟着走。不带的话按完「结束这个时段」要等整页重新拉一次才动
        "time_slots": sess.time_slots or [],
        "slot": sess.slot or "",
        "day": sess.day or 1,
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


def _run_action(
    module: RpgModule, sess: RpgSession, action: RpgAction, target: RpgNpc | None
) -> tuple[list[str], list[str]]:
    facts, warnings = [], []
    ok, why = check_condition(action.requires, sess, [target] if target else None)
    if not ok:
        return [f"你本想{action.name}，但{why}，没能做成"], []
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
    return facts, warnings


async def _resolve_engine(
    session_id: int, action_id: int | None, item_name: str, move_to: str, target_npc: str
) -> tuple[list[str], list[str], dict]:
    """把有定义的那部分算完并落库。返回 (事实句, warnings, 状态快照)。

    在叙事之前落库而不是攒到最后：装配上下文时读到的必须是改完之后的数值，
    否则模型一边被告知「精力 -5」，一边在【你】段里看到没扣的旧值。
    """
    facts: list[str] = []
    warnings: list[str] = []
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

        if move_to:
            locs = list((await store.execute(
                select(RpgLocation).where(RpgLocation.module_id == module.id)
            )).scalars().all())
            target = next((l for l in locs if norm_name(l.name) == norm_name(move_to)), None)
            if target is None:
                warnings.append(f"模组里没有「{move_to}」这个地点")
            else:
                facts += _move(sess, target, npcs)

        if action_id:
            action = await store.get(RpgAction, action_id)
            if action is None or action.module_id != module.id:
                warnings.append("这个动作已经被删掉了")
            else:
                who = next((n for n in npcs if norm_name(n.name) == norm_name(target_npc)), None)
                if action.needs_target and who is None:
                    warnings.append(f"「{action.name}」得先选一个对象")
                else:
                    got, warn = _run_action(module, sess, action, who)
                    facts += got
                    warnings += warn

        if facts:
            warnings += check_zero(module, sess)
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
    session_id: int, reply: str, in_tok: int, out_tok: int, thread_id: int | None = None
) -> int:
    """落 assistant 行。必须另开 session：路由里那个在 handler 返回时就关了，
    而 handler 早于生成器结束返回。

    thread_id 要和玩家那条 user 行一致，否则刷新之后这一问一答分在两条线上。
    """
    async with AsyncSessionLocal() as store:
        row = RpgMessage(
            session_id=session_id, role="assistant", content=reply,
            input_tokens=in_tok, output_tokens=out_tok, thread_id=thread_id,
        )
        store.add(row)
        sess = await store.get(RpgSession, session_id)
        # 显式改一个字段才会触发 onupdate，存档列表靠 updated_at 排序
        sess.updated_at = datetime.utcnow()
        await store.commit()
        await store.refresh(row)
        return row.id


# ── ⑥⑦ AI 结算：只管自由行动那部分的后果 ─────────────────────────────────

def _place_block(movable: list[RpgNpc], sess: RpgSession) -> str:
    """结算提示词末尾追加的「人物位置」段。没人可动就是空串。

    附在 rpg_settle.jinja2 之后而不是改进模板：那个模板用户可以自定义，
    往里加变量会让他们的旧版本静默失效（同 style_block 的理由）。

    得**把这几个人现在的位置写给模型看**：不写的话它只知道「赫敏推门进来」，
    不知道她原本在宿舍，也就写不出「她回去了」那种清空。
    """
    if not movable:
        return ""
    rows = "".join(
        f"{n.name} 现在在 {npc_place(n, sess.slot, sess.npc_places) or '行踪不明'}\n"
        for n in movable
    )
    return (
        "\n\n=== 人物位置 ===\n"
        "这段剧情里**真的换了地方**的人（被叫来、跟着走、被带走、回自己屋），"
        "在输出里加一个 npc_places：\n"
        + rows
        + '{"npc_places": {"赫敏": "校长办公室"}}\n'
        '她只是回到自己平时待的地方，就写空串 ""，系统会按作息表替她算。\n'
        "没换地方的人不要写。这个字段里只准出现上面这几位，别人一律不要写。\n"
        "它只影响「她在不在你跟前」，不改任何数值。\n"
    )


async def _settle(
    session_id: int, message_id: int, narration: str, outcome_label: str,
    engine_note: str, thread_id: int | None = None,
) -> dict:
    """从刚写出的剧情里读出状态变化，夹紧后落库。返回给前端的一份结果。

    整个函数不抛：结算失败只是这一轮的数值没动，不该让已经写好的剧情变成错误。
    """
    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        module = await store.get(RpgModule, sess.module_id)
        npcs = list((await store.execute(
            select(RpgNpc).where(RpgNpc.module_id == module.id)
        )).scalars().all())
        # 有人物的线只让模型改「线主 + 在场的人」：给全量名单它会顺手给不在场
        # 的人加好感，那些数字没有任何剧情依据。主角模板不登场，world_npcs 排掉
        #
        # 模组一个地点都没定义时 sess.location 是空串，here_npcs 按定义返回空，
        # 于是这份名单恒为空、模板里那行整个不渲染，关系和近况一条都记不进去
        # 且不报错。没有地点就意味着「所有人都在同一个场面里」，这是唯一说得通
        # 的读法，也是这类纯对话模组唯一能工作的读法
        who = (
            here_npcs(npcs, sess.location, sess.slot, sess.npc_places)
            if (sess.location or "").strip()
            else world_npcs(npcs)
        )
        owner = find_thread_npc(npcs, thread_id)
        if owner is not None and all(n.id != owner.id for n in who):
            who.append(owner)
        # 第二个 store 块会重新查一遍 npcs（另一批对象），只有 id 能跨过去
        who_ids = {n.id for n in who}
        prompt = render(
            "rpg_settle.jinja2",
            narration=narration[-SETTLE_CHARS:],
            outcome_label=outcome_label,
            stats=sess.stats or {},
            location=sess.location or "",
            inventory=sess.inventory or [],
            flags=sess.flags or {},
            npcs=[
                {"id": n.id, "name": n.name, "notes": (sess.npc_notes or {}).get(str(n.id)) or {}}
                for n in who
            ],
            # 整局用过的键名的并集。只给每个人自己的键不够：模型会在赫敏身上
            # 写「伤势」、在老兵身上另起「受伤」，两套名字从此各长各的。
            # 小说侧同一条路（summarizer 喂的是整本书角色键名的并集）
            note_keys=sorted({
                key for notes in (sess.npc_notes or {}).values()
                if isinstance(notes, dict) for key in notes
            }),
            relation_names=list(def_map(module.relation_stat_defs)),
            engine_note=engine_note,
            # 最近 10 条给模型看一眼，免得同一件事被反复写进大事记
            chronicle=chronicle_lines(sess)[-CHRONICLE_PROMPT_LINES:],
        )
        # 人物位置。可动的只有「这段正文里真的出现了」的人——玩家嘴上叫一声
        # 不算，正文里写了她推门进来才算（named_npcs 的口径，和下面那道
        # 写入闸门用的是同一条规则，两边不能分叉）。
        #
        # 拼在模板后面而不是写进 rpg_settle.jinja2：那个模板用户可以自定义，
        # 他们的旧版本不含这一段，位置这条线会对这些人静默失效。同 style_block
        prompt += _place_block(named_npcs(world_npcs(npcs), narration), sess)
        model, api_format = llm_client.get_agent_client("memory", module.fast_model_ref)

    data, in_tok, out_tok = await call_json(
        [{"role": "user", "content": prompt}], model, api_format, max_tokens=1500,
    )

    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        module = await store.get(RpgModule, sess.module_id)
        npcs = list((await store.execute(
            select(RpgNpc).where(RpgNpc.module_id == module.id)
        )).scalars().all())
        # 分线之后在角色线里被叙述走到别处会变成看得见的 bug：线主不在了，
        # 他的输入框永久置灰。场面线照旧——「自由打字绕过地图」是既有决定
        warnings = apply_state_delta(
            module, sess, data, npcs, allow_move=thread_id is None,
            # 近况只许记在这一轮真的摆在模型眼前的人身上，见 apply_state_delta
            note_npcs=[n for n in npcs if n.id in who_ids],
            # 位置比近况再紧一层：只有正文里真的出现过的人。模型据一个
            # 只在玩家嘴里出现过的名字就能把人挪到跟前，那是纯凭空的编造
            move_npcs=named_npcs(world_npcs(npcs), narration),
        )
        # 大事记（模型认为「已经传开」的那部分）。和每轮建议同一条路：
        # 顺手读一个字段，不额外花一次 LLM 调用
        push_chronicle(sess, data.get("chronicle"))
        row = await store.get(RpgMessage, message_id)
        if row is not None:
            row.state_delta = data
            row.aux_input_tokens = in_tok
            row.aux_output_tokens = out_tok
        await store.commit()
        payload = _state_payload(sess)

    return {
        "state": payload,
        "warnings": warnings,
        "suggestions": [str(s).strip() for s in (data.get("suggestions") or []) if str(s).strip()],
        "outcome_consistent": data.get("outcome_consistent"),
        "aux_input_tokens": in_tok,
        "aux_output_tokens": out_tok,
    }


# ── ⑧ 压缩旧剧情：一条线一份概要 ──────────────────────────────────────────

# 摘要给模型看的一句话前缀。和 suggest 那边保持一致
SUMMARY_MAX_TOKENS = 1200


async def _maybe_summarize(session_id: int, thread_id: int | None) -> bool:
    """这条线未压缩的消息超出窗口时，把溢出的那一段折成概要。

    **每条线各存一份**。一份全局概要会注入每一条线，等于把密室里的对话原样
    告诉所有人——chronicle 之所以规定「只写已经传开的事」，防的就是这个。

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
        keep = max(1, module.context_turns or 20) * 2
        upto = thread_summarized_upto(sess, thread_id)
        pending = [
            m for m in (await store.execute(
                select(RpgMessage)
                .where(RpgMessage.session_id == session_id, RpgMessage.id > upto)
                .order_by(RpgMessage.id)
            )).scalars().all()
            if _in_thread(m, thread_id)
        ]
        if len(pending) <= keep:
            return False

        overflow = pending[: len(pending) - keep]
        last_id = overflow[-1].id
        who = (sess.char_name or "").strip() or DEFAULT_CHAR_NAME
        transcript = "\n".join(
            f"{who if m.role == 'user' else 'GM'}：{m.content}" for m in overflow
        )
        prompt = render(
            "rpg_summary.jinja2",
            previous_summary=thread_summary(sess, thread_id).strip(),
            transcript=transcript,
        )
        # 摘要单独一个字段：它的输出会喂给下一次摘要，错一次会一路带到局终，
        # 和「快且便宜就行」的裁决不是一类活。空 = 跟着裁决模型走
        model, api_format = llm_client.get_agent_client(
            "memory", module.summary_model_ref or module.fast_model_ref
        )

    text = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.3,
        max_tokens=SUMMARY_MAX_TOKENS,
    )
    if not (text or "").strip():
        return False

    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        if sess is None:
            return False
        if thread_id is None:
            sess.summary = text.strip()
            sess.summarized_upto_id = last_id
        else:
            # JSON 列就地改动 SQLAlchemy 认不出来（没上 MutableDict），
            # 必须换成新字典才会写回去
            sess.thread_summaries = {
                **(sess.thread_summaries or {}), str(thread_id): text.strip(),
            }
            sess.thread_upto = {**(sess.thread_upto or {}), str(thread_id): last_id}
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
    thread_id: int | None = None,
) -> list[str]:
    """「帮我想想」：给出 3 条玩家接下来可以做的事。

    和每轮结算顺带产出的 suggestions 是两条独立的路：那条是被动等来的，
    这条是玩家按按钮要的。返回空列表表示没能生成，前端提示一下就好。

    history 由调用方按线筛过，thread_id 用来取对的那一份概要——拿错了会把
    别的线的往事当成这条线的前情，而建议看上去仍然很合理。
    """
    recent = history_window(module, sess, history, thread_id)[-SUGGEST_WINDOW:]
    if not recent:
        return []

    transcript = "\n".join(
        f"{'你' if m.role == 'user' else 'GM'}：{m.content}" for m in recent
    )
    prompt = render(
        "rpg_suggest.jinja2",
        char_name=(sess.char_name or "").strip() or DEFAULT_CHAR_NAME,
        location=sess.location or "",
        summary=truncate_to_token_budget(
            thread_summary(sess, thread_id), SUMMARY_TOKEN_BUDGET
        ),
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
    move_to: str = "",
    target_npc: str = "",
    thread_id: int | None = None,
) -> AsyncIterator[tuple[str, object]]:
    """跑完一轮，yield (事件名, 数据)，由路由编码成 SSE。

    玩家那条消息已经由路由落库了（网络断了也得留下）。action_id / item_name /
    move_to 是「点出来的」行动，走引擎；三个都空就是自由打字，走 AI 结算。

    thread_id 是这一轮归哪条对话线，由路由解析一次后传进来（见 resolve_thread_id），
    这里只照着用：装配上下文时只取这条线的历史，回复也落回这条线。
    """
    facts: list[str] = []
    engine_note = ""
    if action_id or item_name or move_to:
        try:
            facts, warns, state = await _resolve_engine(
                session_id, action_id, item_name, move_to, target_npc
            )
            for warn in warns:
                yield "warning", warn
            if facts:
                engine_note = "；".join(facts)
                yield "state", state
        except Exception:
            logger.exception("RPG 局 %s 引擎结算失败", session_id)
            yield "warning", "这个动作没能结算，本轮按自由行动处理了"

    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        module = await store.get(RpgModule, sess.module_id)
        last = (await store.execute(
            select(RpgMessage)
            .where(
                RpgMessage.session_id == session_id,
                RpgMessage.role == "assistant",
                # 裁决的「最近一段剧情」也要取这条线的，否则在老兵线里判定
                # 时旁边酒馆那几句会干扰语境
                _thread_clause(thread_id),
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
        # 线过滤在调用点做，history_window 的签名一个字不改：传进去的就是
        # 「这条线的消息」，它只管按摘要指针和条数切。这样既有用例全部照旧
        history = [m for m in history if _in_thread(m, thread_id)]
        messages, diag = await build_rpg_messages(
            store, fresh_module, fresh_sess, history, content, judgement, facts, thread_id
        )
        # 外貌已经随这次上下文发出去了，就地记一笔，下一轮不再重复发。
        # 放在开流之前而不是之后：叙事失败也算见过，模型确实已经拿到过那段描写。
        # 只认 npcs_here：被提到一句的人这一轮也拿到了设定，但玩家并没见到他，
        # 记成见过会让他的外貌永远等不到该出现的那一次
        mark_met(fresh_sess, [n["id"] for n in diag["npcs_here"]])
        await store.commit()
    # 出了 with 块才开流：写锁不跨 LLM 调用
    yield "meta", diag

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
            _spawn_detached(_store_reply(session_id, reply, in_tok, out_tok, thread_id))
        raise

    reply = "".join(buf).strip()
    message_id = await _store_reply(session_id, reply, in_tok, out_tok, thread_id)

    if reply:
        label = OUTCOME_LABELS.get((judgement or {}).get("outcome") or "", "")
        try:
            result = await _settle(
                session_id, message_id, reply, label, engine_note, thread_id
            )
            for warn in result["warnings"]:
                yield "warning", warn
            yield "state", result["state"]
            if result["suggestions"]:
                yield "suggestions", result["suggestions"]
            if result["outcome_consistent"] is False:
                yield "warning", "这段剧情好像没照判定结果写"
            aux_in += result["aux_input_tokens"]
            aux_out += result["aux_output_tokens"]
        except Exception:
            # 结算失败只是数值没动，剧情已经写好了。前端据 state_delta 为 null
            # 给「补结算」按钮
            logger.exception("RPG 局 %s 结算失败", session_id)
            yield "warning", "这一轮的状态变化没能结算，可以稍后手动补"

    # 压缩排在结算之后：这一轮的消息已经落库，它也该参与计数。
    # 失败不吭声——玩家没要求过这件事，报错只会让他以为这一轮出了问题
    try:
        await _maybe_summarize(session_id, thread_id)
    except Exception:
        logger.exception("RPG 局 %s 概要生成失败，上下文退化为纯截断", session_id)

    # AI 调度排在最后：它要知道这一轮提到了谁，那是 build_rpg_messages 算的。
    # **这是唯一一次「玩家说完话了还在调模型」**，而且是每轮都调，所以它必须
    # 排在 done 之前——done 之后前端就不再收了，玩家的侧栏会一直停在旧状态。
    # 没勾任何角色、或者勾了的都在场，这一次调用根本不发生
    try:
        # diag 是这一轮注入过设定的人（在场 + 被提到的）。他们归叙事模型管，
        # 调度器另写一份会和玩家刚经历的剧情对不上
        engaged = {int(n["id"]) for n in diag.get("npcs_onstage") or []}
        # 线主单独补一笔。模组一个地点都没定义时 here_npcs 恒为空，玩家在和她
        # 私聊却没说她的名字，她就不在那份名单里——于是调度器会给一个**正在和
        # 你说话的人**另写一份「她今天在干什么」，下一轮两句直接打架
        if thread_id:
            engaged.add(int(thread_id))
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
