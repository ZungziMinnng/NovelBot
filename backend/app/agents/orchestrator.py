"""
Orchestrator: LangGraph 风格的状态机，协调所有 Agent。
以 AsyncIterator 形式输出 SSE 事件，支持流式渲染。
"""
import logging
import time
from typing import AsyncIterator, TypedDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, delete as sql_delete
from app.models.memory import Memory

from app.models.novel import Novel
from app.models.chapter import Chapter
from app.services.context_builder import build_generation_context
from app.services.sse import sse_event
from app.services import summarizer, llm_client, entity_embeddings, state_snapshot
from app.agents import writer
from app.agents.draft_loop import run_draft_loop
from app.agents.memory_pipeline import (
    _emit_llm_call,
    _retry_on_lock,
    run_memory_pipeline,
)

logger = logging.getLogger(__name__)


class NovelState(TypedDict):
    novel_id: int
    chapter_number: int
    volume: int
    instruction: str
    target_words: int
    context: dict
    generated_text: str
    model_used: str
    critic_issues: str
    revision_count: int
    passed: bool
    writer_truncated: bool
    total_input_tokens: int
    total_output_tokens: int


_sse = sse_event
_sse_json = sse_event


async def _prepare_regen_rollback(
    session: AsyncSession, novel: Novel, chapter_number: int, volume: int,
) -> None:
    """生成/重写前回滚：删除旧章节摘要，恢复已有快照或首次创建快照。"""
    await session.execute(
        sql_delete(Memory).where(
            Memory.novel_id == novel.id,
            Memory.chapter_number == chapter_number,
            Memory.volume == volume,
            Memory.memory_type == "chapter_summary",
        )
    )
    await state_snapshot.rollback_or_create(session, novel.id, chapter_number, volume)
    await _retry_on_lock(lambda: session.commit(), "pregen_rollback")


async def run_chapter_generation(
    session: AsyncSession,
    novel: Novel,
    chapter_number: int,
    volume: int = 1,
    instruction: str = "",
    target_words: int = 2500,
    pov: str = "",
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
        "model_used": "",
        "critic_issues": "",
        "revision_count": 0,
        "passed": False,
        "writer_truncated": False,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
    }

    writer_system_prompt = getattr(novel, "writer_system_prompt", "") or ""
    writer_examples = getattr(novel, "writer_examples", []) or []

    try:
        # ── 预清理：删除旧摘要 + 回滚状态快照（current_state）──
        await _prepare_regen_rollback(
            session, novel, chapter_number, volume
        )

        # ── 自愈：补齐旧章缺失的摘要（摘要生成失败会静默丢失，导致记忆链条出现空洞；
        # 每次最多补 2 章，避免拖慢生成）──
        backfill_result = await session.execute(
            select(Chapter).where(
                Chapter.novel_id == novel.id,
                Chapter.number < chapter_number,
                Chapter.content != "",
                or_(Chapter.summary.is_(None), Chapter.summary == ""),
            ).order_by(Chapter.number.desc()).limit(2)
        )
        backfill_chapters = list(reversed(backfill_result.scalars().all()))
        if backfill_chapters:
            bf_nums = "、".join(str(c.number) for c in backfill_chapters)
            bf_ref, _ = llm_client.get_agent_client("memory", novel.fast_model)
            yield _sse_json("agent_start", {
                "agent": "summarizer_backfill",
                "label": f"补齐缺失摘要（第{bf_nums}章）",
                "model": llm_client.resolve_model_ref(bf_ref)[0],
            })
            bf_in = bf_out = 0
            bf_start = time.monotonic()
            for bch in backfill_chapters:
                try:
                    _, i_tok, o_tok = await summarizer.summarize_chapter(session, bch, novel)
                    bf_in += i_tok
                    bf_out += o_tok
                    await session.commit()
                except Exception:
                    logger.warning("补摘要失败：第%s章", bch.number, exc_info=True)
                    await session.rollback()
            state["total_input_tokens"] += bf_in
            state["total_output_tokens"] += bf_out
            yield await _emit_llm_call(novel.id, chapter_number, {
                "agent": "summarizer_backfill",
                "model": "",
                "status": "ok",
                "input_tokens": bf_in,
                "output_tokens": bf_out,
                "duration_ms": int((time.monotonic() - bf_start) * 1000),
            })
            yield _sse_json("agent_done", {
                "agent": "summarizer_backfill",
                "label": f"补齐缺失摘要（第{bf_nums}章）",
                "input_tokens": bf_in,
                "output_tokens": bf_out,
                "passed": True,
            })

        # ── Node 1: Build Context ──────────────────────────────────────────
        yield _sse("stage", "building_context")
        yield _sse_json("agent_start", {"agent": "context", "label": "上下文组装"})
        state["context"] = await build_generation_context(
            session=session,
            novel=novel,
            chapter_number=chapter_number,
            volume=volume,
            scene_hint=instruction,
            pov=pov,
            target_words=target_words,
        )
        context_meta = state["context"].pop("_meta", [])
        for step in context_meta:
            yield _sse_json("context_step", step)
        yield _sse_json("agent_done", {
            "agent": "context",
            "label": f"上下文组装（{len(context_meta)} 个区块）",
            "input_tokens": 0,
            "output_tokens": 0,
            "passed": True,
        })

        # ── Node 2/3/3b: 写作-审稿-修订循环（已拆至 draft_loop）──────────────
        async for event in run_draft_loop(
            session, novel, state, writer_system_prompt, writer_examples,
        ):
            yield event

        # ── Node 4: Save Chapter ───────────────────────────────────────────
        if not state["generated_text"].strip():
            raise ValueError("Writer 未生成任何内容，已中止保存。请检查模型配置或 API Key 是否正确。")
        if state["writer_truncated"]:
            yield _sse("warning", f"内容已达 Token 上限（{getattr(novel, 'writer_max_tokens', 16384)} tokens）被截断，建议在小说设置中增大「最大输出 Token」")
        yield _sse("stage", "saving")
        chapter = await _save_chapter(session, state, novel)
        await session.commit()

        # ── Node 5/6: 记忆更新 + 周期性刷新 + 新设定候选（已拆至 memory_pipeline）─
        async for event in run_memory_pipeline(session, novel, chapter, state):
            yield event

        # ── Emit total usage ───────────────────────────────────────────────
        yield _sse_json("total_usage", {
            "input_tokens": state["total_input_tokens"],
            "output_tokens": state["total_output_tokens"],
        })

        yield _sse("done", str(chapter.id))

    except Exception as e:
        logger.error(
            "章节生成失败 novel=%s chapter=%s: %s: %r",
            novel.id, chapter_number, type(e).__name__, e, exc_info=True,
        )
        await session.rollback()
        yield _sse("error", str(e) or f"{type(e).__name__}（无错误信息，详见后端日志）")


async def run_chapter_rewrite(
    session: AsyncSession,
    novel: Novel,
    chapter_number: int,
    annotations: list[dict],
    target_words: int = 0,
    rewrite_model: str = "",
    pov: str = "",
) -> AsyncIterator[str]:
    try:
        result = await session.execute(
            select(Chapter).where(
                Chapter.novel_id == novel.id,
                Chapter.number == chapter_number,
            )
        )
        chapter = result.scalar_one_or_none()
        if not chapter or not chapter.content:
            yield _sse("error", "当前章节无内容，无法重写")
            return

        original_text = chapter.content
        if target_words <= 0:
            target_words = len(original_text)

        # 预清理：回滚到本章生成前状态，避免在已污染状态上叠加重写记忆
        await _prepare_regen_rollback(session, novel, chapter_number, chapter.volume or 1)

        # ── Build context ──
        yield _sse("stage", "building_context")
        ctx = await build_generation_context(
            session, novel, chapter_number,
            volume=chapter.volume or 1,
            pov=pov,
            target_words=target_words,
        )
        for step in ctx.pop("_meta", []):
            yield _sse_json("context_step", step)

        # ── Rewrite ──
        yield _sse("stage", "rewriting")
        writer_model = rewrite_model or novel.writer_model or ""
        writer_ref, _ = llm_client.get_agent_client("writer", writer_model)
        model = llm_client.resolve_model_ref(writer_ref)[0]  # 展示用真实模型名
        yield _sse_json("agent_start", {"agent": "writer", "label": "批注重写", "model": model})

        writer_system_prompt = novel.writer_system_prompt or ""
        writer_examples = novel.writer_examples or []
        temperature = getattr(novel, "writer_temperature", None)
        if temperature is None:
            temperature = 0.7
        use_custom_temperature = getattr(novel, "writer_use_custom_temperature", True)
        max_tokens = novel.writer_max_tokens or 16384
        gemini_thinking_level = getattr(novel, "gemini_thinking_level", "medium") or "medium"
        deepseek_thinking_level = getattr(novel, "deepseek_thinking_level", "high") or "high"
        gemini_stream = getattr(novel, "gemini_stream", False) or False

        generated_text = ""
        writer_in_tok = writer_out_tok = 0
        t0 = time.monotonic()

        async for item in writer.stream_chapter_rewrite(
            ctx=ctx,
            original_text=original_text,
            annotations=annotations,
            target_words=target_words,
            writer_model=writer_model,
            writer_system_prompt=writer_system_prompt,
            writer_examples=writer_examples,
            temperature=temperature,
            use_custom_temperature=use_custom_temperature,
            max_tokens=max_tokens,
            gemini_thinking_level=gemini_thinking_level,
            deepseek_thinking_level=deepseek_thinking_level,
            gemini_stream=gemini_stream,
        ):
            if isinstance(item, dict) and "llm_payload" in item:
                yield _sse_json("llm_request", item["llm_payload"])
            elif isinstance(item, tuple):
                if len(item) == 3:
                    _, writer_in_tok, writer_out_tok = item
                elif len(item) == 2:
                    writer_in_tok, writer_out_tok = item
            else:
                generated_text += item
                yield _sse("token", item)

        writer_duration = int((time.monotonic() - t0) * 1000)
        yield await _emit_llm_call(novel.id, chapter_number, {
            "agent": "writer", "model": model, "status": "ok",
            "input_tokens": writer_in_tok, "output_tokens": writer_out_tok,
            "duration_ms": writer_duration,
        })
        yield _sse_json("agent_done", {
            "agent": "writer", "label": "批注重写",
            "input_tokens": writer_in_tok, "output_tokens": writer_out_tok,
            "passed": True,
        })

        yield _sse_json("original_draft", {"text": original_text})

        # ── Save ──
        if not generated_text.strip():
            raise ValueError("重写未生成任何内容")
        yield _sse("stage", "saving")
        chapter.content = generated_text
        chapter.word_count = len(generated_text)
        chapter.status = "draft"
        if model:
            chapter.model_used = model
        await session.flush()
        await session.commit()

        # ── Update memory ──
        yield _sse("stage", "updating_memory")
        mem_ref, _ = llm_client.get_agent_client("memory", novel.fast_model)
        yield _sse_json("agent_start", {
            "agent": "memory", "label": "更新记忆",
            "model": llm_client.resolve_model_ref(mem_ref)[0],
        })
        mem_in = mem_out = 0

        yield _sse("stage", "updating_memory_summary")
        try:
            (_, s_in, s_out) = await summarizer.summarize_chapter(session, chapter, novel)
            mem_in += s_in; mem_out += s_out
            await session.commit()
        except Exception as e:
            logger.warning("章节摘要更新失败: %s", e)
            await session.rollback()

        yield _sse("stage", "updating_memory_characters")
        upd_char_ids: list[int] = []
        upd_entity_ids: list[int] = []
        upd_location_ids: list[int] = []
        try:
            (_, _, c_in, c_out, _, upd_char_ids) = await summarizer.update_character_states(session, chapter, novel)
            mem_in += c_in; mem_out += c_out
            await session.commit()
        except Exception as e:
            logger.warning("角色状态更新失败: %s", e)
            await session.rollback()

        yield _sse("stage", "updating_memory_entities")
        try:
            r = await summarizer.update_entity_location_states(session, chapter, novel)
            mem_in += r["input_tokens"]; mem_out += r["output_tokens"]
            upd_entity_ids = r["entity"]["updated_ids"]
            upd_location_ids = r["location"]["updated_ids"]
            await session.commit()
        except Exception as e:
            logger.warning("实体/地点状态更新失败: %s", e)
            await session.rollback()

        await entity_embeddings.reembed_updated(
            session, novel.id,
            char_ids=upd_char_ids, entity_ids=upd_entity_ids, location_ids=upd_location_ids,
        )

        total_in = writer_in_tok + mem_in
        total_out = writer_out_tok + mem_out
        yield _sse_json("agent_done", {
            "agent": "memory", "label": "更新记忆",
            "input_tokens": mem_in, "output_tokens": mem_out, "passed": True,
        })

        yield _sse_json("total_usage", {
            "input_tokens": total_in, "output_tokens": total_out,
        })
        yield _sse("done", str(chapter.id))

    except Exception as e:
        logger.error(
            "章节重写失败 novel=%s chapter=%s: %s: %r",
            novel.id, chapter_number, type(e).__name__, e, exc_info=True,
        )
        await session.rollback()
        yield _sse("error", str(e) or f"{type(e).__name__}（无错误信息，详见后端日志）")


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

    model_used = state.get("model_used") or ""
    if chapter:
        chapter.content = state["generated_text"]
        chapter.instruction = state.get("instruction") or None
        chapter.status = "draft"
        chapter.word_count = len(state["generated_text"])
        if model_used:
            chapter.model_used = model_used
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
            model_used=model_used,
        )
        session.add(chapter)

    await session.flush()
    return chapter
