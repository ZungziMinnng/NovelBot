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
from app.services.llm_json import call_json
from app.services.rpg_context import build_rpg_messages
from app.services.rpg_dice import DEFAULT_BAND, OUTCOME_LABELS, normalize_band, resolve_rate, roll
from app.services.rpg_prompts import render
from app.services.rpg_state import (
    apply_inventory,
    apply_relations,
    apply_state_delta,
    apply_stats,
    check_condition,
    check_zero,
    def_map,
    for_check_stats,
    mark_met,
    norm_name,
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
        "status": sess.status,
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


def _move(
    sess: RpgSession, target: RpgLocation, here: RpgLocation | None, npcs: list[RpgNpc]
) -> list[str]:
    """走过去，或者说明为什么走不过去。返回事实句。

    连接是双向的：作者在 A 里写了 B，从 B 也能回 A。要求两边都写等于让人
    把每条路填两遍，忘一边就变成单行道，而作者根本不会想到去查。
    """
    from_name = (sess.location or "").strip()
    linked = (
        not from_name
        or not here
        or target.name in (here.connections or [])
        or from_name in (target.connections or [])
    )
    if not linked:
        return [f"你想去{target.name}，但从{from_name}没有路直接过去，只能作罢"]
    ok, why = check_condition(target.enter_requires, sess, npcs)
    if not ok:
        return [f"你想进{target.name}，但{why}，被挡在外面"]
    sess.location = target.name
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
                here = next(
                    (l for l in locs if norm_name(l.name) == norm_name(sess.location or "")), None
                )
                facts += _move(sess, target, here, npcs)

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
    session_id: int, reply: str, in_tok: int, out_tok: int
) -> int:
    """落 assistant 行。必须另开 session：路由里那个在 handler 返回时就关了，
    而 handler 早于生成器结束返回。
    """
    async with AsyncSessionLocal() as store:
        row = RpgMessage(
            session_id=session_id, role="assistant", content=reply,
            input_tokens=in_tok, output_tokens=out_tok,
        )
        store.add(row)
        sess = await store.get(RpgSession, session_id)
        # 显式改一个字段才会触发 onupdate，存档列表靠 updated_at 排序
        sess.updated_at = datetime.utcnow()
        await store.commit()
        await store.refresh(row)
        return row.id


# ── ⑥⑦ AI 结算：只管自由行动那部分的后果 ─────────────────────────────────

async def _settle(
    session_id: int, message_id: int, narration: str, outcome_label: str, engine_note: str
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
        prompt = render(
            "rpg_settle.jinja2",
            narration=narration[-SETTLE_CHARS:],
            outcome_label=outcome_label,
            stats=sess.stats or {},
            location=sess.location or "",
            inventory=sess.inventory or [],
            flags=sess.flags or {},
            npcs=[{"id": n.id, "name": n.name} for n in npcs],
            relation_names=list(def_map(module.relation_stat_defs)),
            engine_note=engine_note,
        )
        model, api_format = llm_client.get_agent_client("memory", module.fast_model_ref)

    data, in_tok, out_tok = await call_json(
        [{"role": "user", "content": prompt}], model, api_format, max_tokens=1200,
    )

    async with AsyncSessionLocal() as store:
        sess = await store.get(RpgSession, session_id)
        module = await store.get(RpgModule, sess.module_id)
        npcs = list((await store.execute(
            select(RpgNpc).where(RpgNpc.module_id == module.id)
        )).scalars().all())
        warnings = apply_state_delta(module, sess, data, npcs)
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
) -> AsyncIterator[tuple[str, object]]:
    """跑完一轮，yield (事件名, 数据)，由路由编码成 SSE。

    玩家那条消息已经由路由落库了（网络断了也得留下）。action_id / item_name /
    move_to 是「点出来的」行动，走引擎；三个都空就是自由打字，走 AI 结算。
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
            .where(RpgMessage.session_id == session_id, RpgMessage.role == "assistant")
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
        messages, diag = await build_rpg_messages(
            store, fresh_module, fresh_sess, history, content, judgement, facts
        )
        # 外貌已经随这次上下文发出去了，就地记一笔，下一轮不再重复发。
        # 放在开流之前而不是之后：叙事失败也算见过，模型确实已经拿到过那段描写
        mark_met(fresh_sess, [n["id"] for n in diag["npcs_onstage"]])
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
            _spawn_detached(_store_reply(session_id, reply, in_tok, out_tok))
        raise

    reply = "".join(buf).strip()
    message_id = await _store_reply(session_id, reply, in_tok, out_tok)

    if reply:
        label = OUTCOME_LABELS.get((judgement or {}).get("outcome") or "", "")
        try:
            result = await _settle(session_id, message_id, reply, label, engine_note)
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

    yield "done", {
        "message_id": message_id,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "aux_input_tokens": aux_in,
        "aux_output_tokens": aux_out,
    }
