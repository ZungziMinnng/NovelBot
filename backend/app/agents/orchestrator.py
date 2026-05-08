"""
Orchestrator: LangGraph 风格的状态机，协调所有 Agent。
以 AsyncIterator 形式输出 SSE 事件，支持流式渲染。
"""
import asyncio
import json
import logging
import time
from typing import AsyncIterator, TypedDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete
from sqlalchemy.orm.attributes import flag_modified
from app.models.memory import Memory

from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.world_entity import WorldEntity
from app.models.location import Location
from app.services.context_builder import build_generation_context
from app.services import summarizer, llm_client
from app.agents import writer, critic
from app.config import settings

logger = logging.getLogger(__name__)


class NovelState(TypedDict):
    novel_id: int
    chapter_number: int
    volume: int
    instruction: str
    target_words: int
    context: dict
    generated_text: str
    critic_issues: str
    revision_count: int
    passed: bool
    total_input_tokens: int
    total_output_tokens: int


def _sse(event: str, data: str) -> str:
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def _sse_json(event: str, data: dict) -> str:
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


async def _timed(coro):
    t0 = time.monotonic()
    try:
        result = await coro
    except Exception as e:
        result = e
    return result, int((time.monotonic() - t0) * 1000)


async def run_chapter_generation(
    session: AsyncSession,
    novel: Novel,
    chapter_number: int,
    volume: int = 1,
    instruction: str = "",
    target_words: int = 800,
) -> AsyncIterator[str]:
    """
    章节生成主流程，yield SSE 格式字符串。

    SSE 事件类型：
      stage        → 当前阶段（building_context / writing / reviewing / revising / done / error）
      token        → Writer 流式 token
      agent_start  → {"agent": str, "label": str}
      agent_done   → {"agent": str, "label": str, "input_tokens": int, "output_tokens": int, "passed": bool}
      total_usage  → {"input_tokens": int, "output_tokens": int}
      done         → 生成完成，data 为最终章节 ID
      error        → 错误信息
    """
    state: NovelState = {
        "novel_id": novel.id,
        "chapter_number": chapter_number,
        "volume": volume,
        "instruction": instruction,
        "target_words": target_words,
        "context": {},
        "generated_text": "",
        "critic_issues": "",
        "revision_count": 0,
        "passed": False,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
    }

    writer_system_prompt = getattr(novel, "writer_system_prompt", "") or ""

    try:
        # ── 预清理：删除旧摘要 + 回滚状态快照 ─────────────────────────────
        await session.execute(
            sql_delete(Memory).where(
                Memory.novel_id == novel.id,
                Memory.chapter_number == chapter_number,
                Memory.volume == volume,
                Memory.memory_type == "chapter_summary",
            )
        )
        # 如果存在状态快照（说明是重新生成），恢复角色/实体/地点状态
        snap_result = await session.execute(
            select(Memory).where(
                Memory.novel_id == novel.id,
                Memory.chapter_number == chapter_number,
                Memory.volume == volume,
                Memory.memory_type == "state_snapshot",
            )
        )
        snapshot = snap_result.scalar_one_or_none()
        if snapshot:
            try:
                snap_data = json.loads(snapshot.content)
                for cid_str, cstate in snap_data.get("characters", {}).items():
                    char = await session.get(Character, int(cid_str))
                    if char:
                        char.current_state = cstate
                        flag_modified(char, "current_state")
                for eid_str, estate in snap_data.get("entities", {}).items():
                    ent = await session.get(WorldEntity, int(eid_str))
                    if ent:
                        ent.current_state = estate
                        flag_modified(ent, "current_state")
                for lid_str, lstate in snap_data.get("locations", {}).items():
                    loc = await session.get(Location, int(lid_str))
                    if loc:
                        loc.current_state = lstate
                        flag_modified(loc, "current_state")
                await session.delete(snapshot)
                logger.info("已从快照恢复章节 %d 的状态", chapter_number)
            except Exception:
                logger.warning("状态快照恢复失败", exc_info=True)
        await session.commit()

        # ── Node 1: Build Context ──────────────────────────────────────────
        yield _sse("stage", "building_context")
        state["context"] = await build_generation_context(
            session=session,
            novel=novel,
            chapter_number=chapter_number,
            volume=volume,
            scene_hint=instruction,
        )
        for step in state["context"].pop("_meta", []):
            yield _sse_json("context_step", step)

        # ── Node 2: Write (with optional revision loop) ────────────────────
        max_retries = settings.max_critic_retries
        while state["revision_count"] <= max_retries:
            revision = state["revision_count"]
            if revision == 0:
                stage_label = "writing"
                agent_label = "生成章节"
            else:
                stage_label = f"revising_{revision}"
                agent_label = f"修改（第{revision}次）"

            yield _sse("stage", stage_label)
            yield _sse_json("agent_start", {"agent": "writer", "label": agent_label})

            full_text = ""
            writer_in_tok = 0
            writer_out_tok = 0
            writer_truncated = False
            writer_payload = None
            writer_start = time.monotonic()
            async for item in writer.stream_chapter(
                ctx=state["context"],
                instruction=state["instruction"],
                target_words=state["target_words"],
                writer_model=novel.writer_model,
                issues_feedback=state["critic_issues"],
                writer_system_prompt=writer_system_prompt,
                temperature=getattr(novel, "writer_temperature", 0.85),
                max_tokens=getattr(novel, "writer_max_tokens", 4096),
                thinking_level=getattr(novel, "thinking_level", "medium"),
                gemini_stream=getattr(novel, "gemini_stream", False),
            ):
                if isinstance(item, dict):
                    # 元信息（如重试 warning、LLM payload）
                    if "warning" in item:
                        yield _sse("warning", item["warning"])
                    elif "llm_payload" in item:
                        writer_payload = item["llm_payload"]
                        yield _sse_json("llm_request", writer_payload)
                elif isinstance(item, tuple):
                    finish_reason, writer_in_tok, writer_out_tok = item
                    if finish_reason == "length":
                        writer_truncated = True
                else:
                    full_text += item
                    yield _sse("token", item)

            state["generated_text"] = full_text
            state["total_input_tokens"] += writer_in_tok
            state["total_output_tokens"] += writer_out_tok
            writer_duration = int((time.monotonic() - writer_start) * 1000)
            yield _sse_json("llm_call", {
                "agent": "writer",
                "model": writer_payload.get("model", "") if writer_payload else "",
                "status": "truncated" if writer_truncated else "ok",
                "input_tokens": writer_in_tok,
                "output_tokens": writer_out_tok,
                "duration_ms": writer_duration,
                "payload": writer_payload,
            })
            yield _sse_json("agent_done", {
                "agent": "writer",
                "label": agent_label,
                "input_tokens": writer_in_tok,
                "output_tokens": writer_out_tok,
                "passed": True,
            })

            # ── Node 3: Critic (可选) ──────────────────────────────────────
            if getattr(novel, "enable_critic", True):
                yield _sse("stage", "reviewing")
                yield _sse_json("agent_start", {"agent": "critic", "label": "质量审查"})
                critic_start = time.monotonic()
                passed, issues, critic_in_tok, critic_out_tok, critic_model = await critic.review_chapter(
                    generated_text=state["generated_text"],
                    ctx=state["context"],
                    fast_model=novel.fast_model,
                )
                critic_duration = int((time.monotonic() - critic_start) * 1000)
                state["passed"] = passed
                state["critic_issues"] = issues
                state["total_input_tokens"] += critic_in_tok
                state["total_output_tokens"] += critic_out_tok
                yield _sse_json("llm_call", {
                    "agent": "critic",
                    "model": critic_model,
                    "status": "ok",
                    "input_tokens": critic_in_tok,
                    "output_tokens": critic_out_tok,
                    "duration_ms": critic_duration,
                })
                yield _sse_json("agent_done", {
                    "agent": "critic",
                    "label": "质量审查",
                    "input_tokens": critic_in_tok,
                    "output_tokens": critic_out_tok,
                    "passed": passed,
                })

                if passed:
                    break
                # 首次 Critic 失败时，先发出初稿内容，让前端展示对比视图
                if state["revision_count"] == 0:
                    yield _sse_json("original_draft", {"text": state["generated_text"]})
                state["revision_count"] += 1
            else:
                # Critic 已关闭，直接使用 Writer 生成结果
                break

        # ── Node 4: Save Chapter ───────────────────────────────────────────
        if not state["generated_text"].strip():
            raise ValueError("Writer 未生成任何内容，已中止保存。请检查模型配置或 API Key 是否正确。")
        if writer_truncated:
            yield _sse("warning", f"内容已达 Token 上限（{getattr(novel, 'writer_max_tokens', 4096)} tokens）被截断，建议在小说设置中增大「最大输出 Token」")
        yield _sse("stage", "saving")
        chapter = await _save_chapter(session, state, novel)
        await session.commit()

        # ── Node 4b: 保存状态快照（供重新生成时回滚）──────────────────────
        try:
            chars_r = await session.execute(select(Character).where(Character.novel_id == novel.id))
            ents_r = await session.execute(select(WorldEntity).where(WorldEntity.novel_id == novel.id))
            locs_r = await session.execute(select(Location).where(Location.novel_id == novel.id))
            snap_content = json.dumps({
                "characters": {str(c.id): c.current_state for c in chars_r.scalars().all()},
                "entities": {str(e.id): e.current_state for e in ents_r.scalars().all()},
                "locations": {str(l.id): l.current_state for l in locs_r.scalars().all()},
            }, ensure_ascii=False)
            await session.execute(
                sql_delete(Memory).where(
                    Memory.novel_id == novel.id,
                    Memory.chapter_number == chapter_number,
                    Memory.volume == volume,
                    Memory.memory_type == "state_snapshot",
                )
            )
            session.add(Memory(
                novel_id=novel.id, chapter_number=chapter_number, volume=volume,
                memory_type="state_snapshot", content=snap_content,
            ))
            await session.commit()
        except Exception:
            logger.warning("状态快照保存失败", exc_info=True)
            await session.rollback()

        # ── Node 5: Update Memory + Generate Suggestions ───────────────────
        # 记忆操作依次执行并立即 commit，避免 SQLite 写锁跨 LLM 调用长期持有。
        # 剧情建议（纯 LLM，无 DB）在后台并行。
        yield _sse("stage", "updating_memory")
        yield _sse_json("agent_start", {"agent": "memory", "label": "更新记忆"})

        from app.api.routes.generation import generate_plot_suggestions
        suggestions_task = asyncio.create_task(generate_plot_suggestions(
            novel, state["generated_text"], state["context"], state["chapter_number"],
            writer_system_prompt=writer_system_prompt,
        ))

        mem_model, _ = llm_client.get_agent_client("memory", novel.fast_model)
        mem_warnings: list[str] = []
        sum_in = sum_out = char_in = char_out = ent_in = ent_out = 0
        char_ok = ent_ok = True
        char_warning = ent_warning = ""

        # ── 章节摘要 ──
        try:
            r0, dur_sum = await _timed(summarizer.summarize_chapter(session, chapter, novel))
            if isinstance(r0, BaseException):
                raise r0
            (_, sum_in, sum_out) = r0
            await session.commit()
        except Exception as e:
            logger.warning("章节摘要生成失败: %s", e)
            mem_warnings.append(f"摘要生成失败: {e}")
            await session.rollback()
            dur_sum = 0
        yield _sse_json("llm_call", {
            "agent": "summarizer", "model": mem_model,
            "status": "error" if mem_warnings else "ok",
            "input_tokens": sum_in, "output_tokens": sum_out, "duration_ms": dur_sum,
        })

        # ── 角色状态更新 ──
        try:
            r1, dur_char = await _timed(summarizer.update_character_states(
                session, chapter, novel, instruction=state["instruction"]
            ))
            if isinstance(r1, BaseException):
                raise r1
            (char_ok, char_warning, char_in, char_out) = r1
            await session.commit()
        except Exception as e:
            logger.warning("角色状态更新失败: %s", e)
            mem_warnings.append(f"角色状态更新失败: {e}")
            await session.rollback()
            dur_char = 0
        yield _sse_json("llm_call", {
            "agent": "char_update", "model": mem_model,
            "status": "error" if isinstance(locals().get('r1'), BaseException) else "ok",
            "input_tokens": char_in, "output_tokens": char_out, "duration_ms": dur_char,
        })

        # ── 实体状态更新 ──
        try:
            r2, dur_ent = await _timed(summarizer.update_entity_states(
                session, chapter, novel, instruction=state["instruction"]
            ))
            if isinstance(r2, BaseException):
                raise r2
            (ent_ok, ent_warning, ent_in, ent_out) = r2
            await session.commit()
        except Exception as e:
            logger.warning("实体状态更新失败: %s", e)
            mem_warnings.append(f"实体状态更新失败: {e}")
            await session.rollback()
            dur_ent = 0
        yield _sse_json("llm_call", {
            "agent": "entity_update", "model": mem_model,
            "status": "error" if isinstance(locals().get('r2'), BaseException) else "ok",
            "input_tokens": ent_in, "output_tokens": ent_out, "duration_ms": dur_ent,
        })

        # ── 地点状态更新 ──
        loc_in = loc_out = 0
        loc_ok = True
        loc_warning = ""
        try:
            r3, dur_loc = await _timed(summarizer.update_location_states(
                session, chapter, novel, instruction=state["instruction"]
            ))
            if isinstance(r3, BaseException):
                raise r3
            (loc_ok, loc_warning, loc_in, loc_out) = r3
            await session.commit()
        except Exception as e:
            logger.warning("地点状态更新失败: %s", e)
            mem_warnings.append(f"地点状态更新失败: {e}")
            await session.rollback()
            dur_loc = 0
        yield _sse_json("llm_call", {
            "agent": "location_update", "model": mem_model,
            "status": "error" if isinstance(locals().get('r3'), BaseException) else "ok",
            "input_tokens": loc_in, "output_tokens": loc_out, "duration_ms": dur_loc,
        })

        # ── 等待剧情建议 ──
        try:
            suggestions = await suggestions_task
        except Exception as e:
            logger.warning("plot_suggestions 失败: %s", e)
            suggestions = []

        mem_in = sum_in + char_in + ent_in + loc_in
        mem_out = sum_out + char_out + ent_out + loc_out
        state["total_input_tokens"] += mem_in
        state["total_output_tokens"] += mem_out
        yield _sse_json("agent_done", {
            "agent": "memory",
            "label": "更新记忆",
            "input_tokens": mem_in,
            "output_tokens": mem_out,
            "passed": char_ok and ent_ok and loc_ok,
        })
        warnings = [w for w in (char_warning, ent_warning, loc_warning, *mem_warnings) if w]
        if warnings:
            yield _sse("warning", "; ".join(warnings))
        if suggestions:
            yield _sse_json("plot_suggestions", {"suggestions": suggestions})

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

        # 自动刷新全书概要（每 5 章刷新一次）
        if ch_num >= 5 and ch_num % 5 == 0:
            try:
                await summarizer.generate_book_summary(session, novel)
                await session.commit()
            except Exception:
                logger.warning("自动刷新全书概要失败", exc_info=True)

        # 全文审查（按间隔自动触发）
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

        # ── Node 6: Discover New Characters + Entities + Locations (parallel) ─
        from app.agents import character_agent
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
        try:
            candidates, entity_candidates, location_candidates, technique_candidates = await asyncio.gather(
                character_agent.discover_new_characters(
                    novel, state["generated_text"], existing_names
                ),
                character_agent.discover_new_entities(
                    novel, state["generated_text"], existing_entity_names
                ),
                character_agent.discover_new_locations(
                    novel, state["generated_text"], existing_locations
                ),
                character_agent.discover_new_techniques(
                    novel, state["generated_text"], existing_tech_names
                ),
            )
            if candidates:
                yield _sse_json("new_characters", {"candidates": candidates})
            if entity_candidates:
                yield _sse_json("new_entities", {"candidates": entity_candidates})
            if location_candidates:
                yield _sse_json("new_locations", {"candidates": location_candidates})
            if technique_candidates:
                yield _sse_json("new_techniques", {"candidates": technique_candidates})
        except Exception:
            pass

        # ── Emit total usage ───────────────────────────────────────────────
        yield _sse_json("total_usage", {
            "input_tokens": state["total_input_tokens"],
            "output_tokens": state["total_output_tokens"],
        })

        yield _sse("done", str(chapter.id))

    except Exception as e:
        await session.rollback()
        yield _sse("error", str(e))


async def _save_chapter(
    session: AsyncSession,
    state: NovelState,
    novel: Novel,
) -> Chapter:
    """保存或更新章节到数据库"""
    result = await session.execute(
        select(Chapter).where(
            Chapter.novel_id == state["novel_id"],
            Chapter.number == state["chapter_number"],
            Chapter.volume == state["volume"],
        )
    )
    chapter = result.scalar_one_or_none()

    if chapter:
        chapter.content = state["generated_text"]
        chapter.instruction = state.get("instruction") or None
        chapter.status = "draft"
        chapter.word_count = len(state["generated_text"])
    else:
        chapter = Chapter(
            novel_id=state["novel_id"],
            volume=state["volume"],
            number=state["chapter_number"],
            title=f"第{state['chapter_number']}章",
            content=state["generated_text"],
            instruction=state.get("instruction") or None,
            status="draft",
            word_count=len(state["generated_text"]),
        )
        session.add(chapter)

    await session.flush()
    return chapter
