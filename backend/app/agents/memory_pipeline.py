"""
生成后记忆管线：章节保存之后的记忆更新（摘要/角色/实体地点状态）、
周期性刷新（故事弧/全书概要/漂移检测/全文审查）与新设定候选后过滤。
从 orchestrator 拆出，行为与拆分前完全一致；候选生成等场景可整体跳过本管线。
"""
import asyncio
import logging
import time
from typing import AsyncIterator, Awaitable, Callable

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.chapter import Chapter
from app.models.llm_usage import LlmUsage
from app.models.novel import Novel
from app.services import summarizer, llm_client, entity_embeddings
from app.services.sse import sse_event

logger = logging.getLogger(__name__)

_sse = sse_event
_sse_json = sse_event


async def _emit_llm_call(novel_id: int, chapter_number: int, data: dict) -> str:
    """把一次 LLM 调用记入 llm_usage 账本（独立短会话，失败仅警告），
    并返回原样的 llm_call SSE 事件。"""
    try:
        async with AsyncSessionLocal() as s:
            s.add(LlmUsage(
                novel_id=novel_id,
                chapter_number=chapter_number,
                agent=data.get("agent") or "",
                model=data.get("model") or "",
                status=data.get("status") or "ok",
                input_tokens=int(data.get("input_tokens") or 0),
                output_tokens=int(data.get("output_tokens") or 0),
                duration_ms=int(data.get("duration_ms") or 0),
            ))
            await s.commit()
    except Exception:
        logger.warning("LLM 用量记账失败（已忽略）", exc_info=True)
    return _sse_json("llm_call", data)


async def _timed(coro):
    t0 = time.monotonic()
    try:
        result = await coro
    except Exception as e:
        result = e
    return result, int((time.monotonic() - t0) * 1000)


async def _retry_on_lock(fn: Callable[[], Awaitable[None]], label: str = "", max_retries: int = 5, base_delay: float = 0.5) -> None:
    """SQLite 并发写入遇到 database is locked 时自动重试，指数退避。"""
    for i in range(max_retries):
        try:
            return await fn()
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            if i == max_retries - 1:
                raise
            delay = base_delay * (2 ** i)
            logger.warning("数据库锁定，%s秒后重试(%d/%d): %s", delay, i + 1, max_retries, label)
            await asyncio.sleep(delay)


async def run_memory_pipeline(
    session: AsyncSession,
    novel: Novel,
    chapter: Chapter,
    state: dict,
) -> AsyncIterator[str]:
    """章节保存后的记忆更新全流程，yield SSE 事件。

    读取 state 的 context / instruction / chapter_number / volume，
    并把记忆环节的 token 消耗累加进 state 的 total_input_tokens / total_output_tokens。
    """
    chapter_number = state["chapter_number"]

    # ── Node 5: Update Memory ─────────────────────────────────────────
    # 记忆操作依次执行并立即 commit，避免 SQLite 写锁跨 LLM 调用长期持有。
    mem_ref, _ = llm_client.get_agent_client("memory", novel.fast_model)
    mem_model = llm_client.resolve_model_ref(mem_ref)[0]  # 展示用真实模型名
    yield _sse("stage", "updating_memory")
    mem_warnings: list[str] = []
    sum_in = sum_out = char_in = char_out = ent_in = ent_out = 0
    char_ok = ent_ok = True
    char_warning = ent_warning = ""
    summary_text = ""
    projection_status = {
        "summary": "pending",
        "character_state": "pending",
        "entity_state": "pending",
        "location_state": "pending",
    }
    unmatched_chars: list[str] = []
    unmatched_entities: list[str] = []
    unmatched_locations: list[str] = []
    updated_char_ids: list[int] = []
    updated_entity_ids: list[int] = []
    updated_location_ids: list[int] = []

    # 已知名单（供合并调用里的新设定发现剔除已知条目，Node 6 复用做后过滤）
    existing_names = state["context"].get("_all_character_names", [c["name"] for c in state["context"].get("characters", [])])
    existing_entity_names = state["context"].get(
        "_all_system_names",
        [e["name"] for e in state["context"].get("items", []) + state["context"].get("systems", [])]
    )
    existing_locations = state["context"].get(
        "_all_location_info",
        [{"name": loc["name"], "type": loc["type"], "parent_name": loc.get("parent_name", "")}
         for loc in state["context"].get("locations", [])]
    )
    existing_tech_names = state["context"].get("_all_technique_names", [t["name"] for t in state["context"].get("techniques", [])])
    existing_faction_names = state["context"].get("_all_faction_names", [f["name"] for f in state["context"].get("factions", [])])

    # ── 章节摘要 + 新设定发现（单次 LLM 调用） ──
    discovered_raw: dict | None = None
    yield _sse("stage", "updating_memory_summary")
    yield _sse_json("agent_start", {"agent": "summarizer", "label": "章节摘要+新设定发现", "model": mem_model})
    try:
        r0, dur_sum = await _timed(summarizer.summarize_and_discover(
            session, chapter, novel,
            known_char_names=existing_names,
            known_entity_names=existing_entity_names,
            known_locations=existing_locations,
            known_tech_names=existing_tech_names,
            known_faction_names=existing_faction_names,
        ))
        if isinstance(r0, BaseException):
            raise r0
        (summary_text, discovered_raw, sum_in, sum_out) = r0
        projection_status["summary"] = "done" if summary_text else "skipped"
        await _retry_on_lock(lambda: session.commit(), "summary_commit")
    except Exception as e:
        logger.warning("章节摘要生成失败: %s", e)
        mem_warnings.append(f"摘要生成失败: {e}")
        projection_status["summary"] = f"failed:{type(e).__name__}: {e}"
        await session.rollback()
        dur_sum = 0
    yield await _emit_llm_call(novel.id, chapter_number, {
        "agent": "summarizer", "model": mem_model,
        "status": "error" if mem_warnings else "ok",
        "input_tokens": sum_in, "output_tokens": sum_out, "duration_ms": dur_sum,
    })
    yield _sse_json("agent_done", {
        "agent": "summarizer",
        "label": "章节摘要+新设定发现",
        "input_tokens": sum_in,
        "output_tokens": sum_out,
        "passed": projection_status["summary"] == "done",
    })

    # ── 角色状态更新 ──
    yield _sse("stage", "updating_memory_characters")
    yield _sse_json("agent_start", {"agent": "char_update", "label": "角色状态更新", "model": mem_model})
    try:
        r1, dur_char = await _timed(summarizer.update_character_states(
            session, chapter, novel, instruction=state["instruction"]
        ))
        if isinstance(r1, BaseException):
            raise r1
        (char_ok, char_warning, char_in, char_out, unmatched_chars, updated_char_ids) = r1
        projection_status["character_state"] = "done" if char_ok else f"failed:{char_warning or 'unknown'}"
        await _retry_on_lock(lambda: session.commit(), "char_state_commit")
    except Exception as e:
        logger.warning("角色状态更新失败: %s", e)
        mem_warnings.append(f"角色状态更新失败: {e}")
        projection_status["character_state"] = f"failed:{type(e).__name__}: {e}"
        await session.rollback()
        dur_char = 0
    yield await _emit_llm_call(novel.id, chapter_number, {
        "agent": "char_update", "model": mem_model,
        "status": "error" if isinstance(locals().get('r1'), BaseException) else "ok",
        "input_tokens": char_in, "output_tokens": char_out, "duration_ms": dur_char,
    })
    yield _sse_json("agent_done", {
        "agent": "char_update",
        "label": "角色状态更新",
        "input_tokens": char_in,
        "output_tokens": char_out,
        "passed": char_ok,
    })

    # ── 实体+地点状态更新（单次 LLM 调用） ──
    yield _sse("stage", "updating_memory_entities")
    yield _sse_json("agent_start", {"agent": "entity_update", "label": "实体/地点状态更新", "model": mem_model})
    loc_ok = True
    loc_warning = ""
    try:
        r2, dur_ent = await _timed(summarizer.update_entity_location_states(
            session, chapter, novel, instruction=state["instruction"]
        ))
        if isinstance(r2, BaseException):
            raise r2
        ent_ok = r2["entity"]["ok"]
        ent_warning = r2["entity"]["warning"]
        unmatched_entities = r2["entity"]["unmatched"]
        updated_entity_ids = r2["entity"]["updated_ids"]
        loc_ok = r2["location"]["ok"]
        loc_warning = r2["location"]["warning"]
        unmatched_locations = r2["location"]["unmatched"]
        updated_location_ids = r2["location"]["updated_ids"]
        ent_in = r2["input_tokens"]
        ent_out = r2["output_tokens"]
        projection_status["entity_state"] = "done" if ent_ok else f"failed:{ent_warning or 'unknown'}"
        projection_status["location_state"] = "done" if loc_ok else f"failed:{loc_warning or 'unknown'}"
        await _retry_on_lock(lambda: session.commit(), "entity_location_state_commit")
    except Exception as e:
        logger.warning("实体/地点状态更新失败: %s", e)
        mem_warnings.append(f"实体/地点状态更新失败: {e}")
        projection_status["entity_state"] = f"failed:{type(e).__name__}: {e}"
        projection_status["location_state"] = f"failed:{type(e).__name__}: {e}"
        await session.rollback()
        dur_ent = 0
    yield await _emit_llm_call(novel.id, chapter_number, {
        "agent": "entity_update", "model": mem_model,
        "status": "error" if isinstance(locals().get('r2'), BaseException) else "ok",
        "input_tokens": ent_in, "output_tokens": ent_out, "duration_ms": dur_ent,
    })
    yield _sse_json("agent_done", {
        "agent": "entity_update",
        "label": "实体/地点状态更新",
        "input_tokens": ent_in,
        "output_tokens": ent_out,
        "passed": ent_ok and loc_ok,
    })

    # 状态变更后重嵌向量，让检索能命中角色/实体的最新状态（失败仅警告）
    await entity_embeddings.reembed_updated(
        session, novel.id,
        char_ids=updated_char_ids,
        entity_ids=updated_entity_ids,
        location_ids=updated_location_ids,
    )

    yield _sse_json("projection_status", {"status": projection_status})

    mem_in = sum_in + char_in + ent_in
    mem_out = sum_out + char_out + ent_out
    state["total_input_tokens"] += mem_in
    state["total_output_tokens"] += mem_out
    warnings = [w for w in (char_warning, ent_warning, loc_warning, *mem_warnings) if w]
    if warnings:
        yield _sse("warning", "; ".join(warnings))

    # 自动刷新故事弧概要（每 15 章生成一次，中间粒度摘要层）
    ch_num = state["chapter_number"]
    if ch_num >= 15 and ch_num % 15 == 0:
        try:
            await summarizer.generate_arc_summary(
                session, novel,
                start_chapter=ch_num - 14,
                end_chapter=ch_num,
                volume=state["volume"],
            )
            await session.commit()
        except Exception:
            logger.warning("自动刷新故事弧概要失败", exc_info=True)

    # 自动刷新全书概要（每 5 章增量更新，每 20 章全量重建防止增量跑偏）
    if ch_num >= 5 and ch_num % 5 == 0:
        try:
            if ch_num % 20 == 0:
                await summarizer.generate_book_summary(session, novel)
            else:
                await summarizer.generate_book_summary(
                    session, novel, window=(ch_num - 4, ch_num),
                )
            await session.commit()
        except Exception:
            logger.warning("自动刷新全书概要失败", exc_info=True)

    # 世界观漂移检测（每 10 章弱提醒，只产 pending 供用户确认，绝不自动注入）
    if ch_num >= 10 and ch_num % 10 == 0:
        try:
            drifts = await summarizer.detect_worldview_drift(session, novel, recent=10)
            new_rows = await summarizer.persist_pending_drifts(session, novel.id, drifts)
            await session.commit()
            if new_rows:
                yield _sse_json("worldview_drift", {"count": len(new_rows)})
        except Exception:
            logger.warning("世界观漂移检测失败", exc_info=True)

    # 全文审查（按全局间隔自动触发）
    from app.config import settings as app_settings
    if getattr(app_settings, "enable_review", False):
        interval = getattr(app_settings, "review_interval", 10)
        if interval > 0 and ch_num >= interval and ch_num % interval == 0:
            try:
                from app.agents import review_agent
                yield _sse("stage", "全文审查中...")
                issues, r_in, r_out, r_model = await review_agent.run_fulltext_review(session, novel)
                yield _sse_json("review_result", {
                    "issues": issues,
                    "input_tokens": r_in,
                    "output_tokens": r_out,
                    "model": r_model,
                })
            except Exception:
                logger.warning("自动全文审查失败", exc_info=True)

    # ── Node 6: 新设定候选后过滤（发现调用已合并进章节摘要，无独立 LLM 调用）─
    from app.agents import character_agent
    try:
        if discovered_raw:
            candidates, entity_candidates, location_candidates, technique_candidates, faction_candidates = character_agent.filter_discovered(
                discovered_raw,
                existing_names, existing_entity_names, existing_locations,
                existing_tech_names, existing_faction_names,
            )
        else:
            # 合并调用降级为纯摘要时无发现结果；unmatched 补入逻辑仍生效
            candidates, entity_candidates, location_candidates, technique_candidates, faction_candidates = [], [], [], [], []
        # 将状态更新中未匹配的名字补入发现结果（发现 LLM 可能遗漏）
        all_discovered = {
            c["name"] for lst in (candidates, entity_candidates, location_candidates, technique_candidates, faction_candidates)
            for c in lst
        }
        _known_non_char = {n.strip() for n in existing_entity_names + existing_tech_names + existing_faction_names} | {l["name"].strip() for l in existing_locations}
        for name in unmatched_chars:
            if name not in all_discovered and name.strip() not in _known_non_char:
                candidates.append({"name": name, "role": "配角", "description": "（状态更新中发现，未录入角色库）"})
                all_discovered.add(name)
        _known_non_entity = {n.strip() for n in existing_names + existing_tech_names + existing_faction_names} | {l["name"].strip() for l in existing_locations}
        for name in unmatched_entities:
            if name not in all_discovered and name.strip() not in _known_non_entity:
                entity_candidates.append({"name": name, "type": "item", "description": "（状态更新中发现，未录入实体库）"})
                all_discovered.add(name)
        _known_non_loc = {n.strip() for n in existing_names + existing_entity_names + existing_tech_names + existing_faction_names}
        for name in unmatched_locations:
            if name not in all_discovered and name.strip() not in _known_non_loc:
                location_candidates.append({"name": name, "type": "", "description": "（状态更新中发现，未录入地点库）", "parent_name": ""})

        if candidates:
            yield _sse_json("new_characters", {"candidates": candidates})
        if entity_candidates:
            yield _sse_json("new_entities", {"candidates": entity_candidates})
        if location_candidates:
            yield _sse_json("new_locations", {"candidates": location_candidates})
        if technique_candidates:
            yield _sse_json("new_techniques", {"candidates": technique_candidates})
        if faction_candidates:
            yield _sse_json("new_factions", {"candidates": faction_candidates})
        threads = (discovered_raw or {}).get("threads") or []
        if threads:
            yield _sse_json("new_threads", {"threads": threads})
        resolutions = (discovered_raw or {}).get("resolutions") or []
        if resolutions:
            yield _sse_json("thread_resolutions", {"resolutions": resolutions})
        # 日志汇总一行：本章发现了哪些新设定候选（全零则不发）
        found_parts = [
            f"{name}{len(lst)}" for name, lst in (
                ("角色", candidates), ("实体", entity_candidates),
                ("地点", location_candidates), ("功法", technique_candidates),
                ("势力", faction_candidates), ("伏笔", threads),
                ("回收", resolutions),
            ) if lst
        ]
        if found_parts:
            label = "发现新设定：" + "·".join(found_parts)
            yield _sse_json("agent_start", {"agent": "discovery", "label": label})
            yield _sse_json("agent_done", {
                "agent": "discovery", "label": label,
                "input_tokens": 0, "output_tokens": 0, "passed": True,
            })
    except Exception:
        pass
