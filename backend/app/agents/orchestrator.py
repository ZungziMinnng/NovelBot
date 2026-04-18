"""
Orchestrator: LangGraph 风格的状态机，协调所有 Agent。
以 AsyncIterator 形式输出 SSE 事件，支持流式渲染。
"""
import asyncio
import json
from typing import AsyncIterator, TypedDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete
from app.models.memory import Memory

from app.models.novel import Novel
from app.models.chapter import Chapter
from app.services.context_builder import build_generation_context
from app.services import summarizer
from app.agents import writer, critic
from app.config import settings


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
        # ── 预清理：删除当前章节的旧摘要 ─────────────────────────────────
        # 确保生成全程 DB 里没有该章节的陈旧记忆数据，
        # 也避免生成失败时遗留脏数据影响后续章节的滚动摘要窗口。
        await session.execute(
            sql_delete(Memory).where(
                Memory.novel_id == novel.id,
                Memory.chapter_number == chapter_number,
                Memory.volume == volume,
                Memory.memory_type == "chapter_summary",
            )
        )
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
            ):
                if isinstance(item, dict):
                    # 元信息（如重试 warning、LLM payload）
                    if "warning" in item:
                        yield _sse("warning", item["warning"])
                    elif "llm_payload" in item:
                        yield _sse_json("llm_request", item["llm_payload"])
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
                passed, issues, critic_in_tok, critic_out_tok = await critic.review_chapter(
                    generated_text=state["generated_text"],
                    ctx=state["context"],
                    fast_model=novel.fast_model,
                )
                state["passed"] = passed
                state["critic_issues"] = issues
                state["total_input_tokens"] += critic_in_tok
                state["total_output_tokens"] += critic_out_tok
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

        # ── Node 5: Update Memory ─────────────────────────────────────────
        yield _sse("stage", "updating_memory")
        yield _sse_json("agent_start", {"agent": "memory", "label": "更新记忆"})
        summary_coro = summarizer.summarize_chapter(session, chapter, novel)
        char_coro = summarizer.update_character_states(
            session, chapter, novel, instruction=state["instruction"]
        )
        (_, sum_in, sum_out), (char_ok, char_warning, char_in, char_out) = (
            await asyncio.gather(summary_coro, char_coro)
        )
        mem_in = sum_in + char_in
        mem_out = sum_out + char_out
        state["total_input_tokens"] += mem_in
        state["total_output_tokens"] += mem_out
        yield _sse_json("agent_done", {
            "agent": "memory",
            "label": "更新记忆",
            "input_tokens": mem_in,
            "output_tokens": mem_out,
            "passed": char_ok,
        })
        await session.commit()
        if char_warning:
            yield _sse("warning", char_warning)

        # ── Node 6: Discover New Characters ──────────────────────────────
        from app.agents import character_agent
        existing_names = [c["name"] for c in state["context"].get("characters", [])]
        try:
            candidates = await character_agent.discover_new_characters(
                novel, state["generated_text"], existing_names
            )
            if candidates:
                yield _sse_json("new_characters", {"candidates": candidates})
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
