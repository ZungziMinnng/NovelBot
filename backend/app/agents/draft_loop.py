"""
写作-审稿-修订循环：Writer 流式生成 → Critic 质量审查 → 剧情细节审查，
未通过则带审稿意见增量修订，直至通过或达到重试上限。
从 orchestrator 拆出，行为与拆分前完全一致；截断标记经 state["writer_truncated"] 传回。
"""
import asyncio
import logging
import time
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import writer, critic
from app.agents.memory_pipeline import _emit_llm_call
from app.config import settings
from app.models.novel import Novel
from app.services import llm_client
from app.services.sse import sse_event

logger = logging.getLogger(__name__)

_sse = sse_event
_sse_json = sse_event


async def run_draft_loop(
    session: AsyncSession,
    novel: Novel,
    state: dict,
    writer_system_prompt: str,
    writer_examples: list,
) -> AsyncIterator[str]:
    """生成初稿并循环审稿修订，yield SSE 事件。

    读写 state 的 generated_text / model_used / critic_issues / revision_count /
    passed / token 计数，并把最后一轮的截断标记写入 state["writer_truncated"]。
    """
    chapter_number = state["chapter_number"]
    volume = state["volume"]

    # 展示用真实模型名（agent_start 事件标注）
    writer_ref, _ = llm_client.get_agent_client("writer", novel.writer_model)
    writer_model_name = llm_client.resolve_model_ref(writer_ref)[0]
    critic_ref, _ = llm_client.get_agent_client("critic", getattr(novel, "critic_model", "") or novel.fast_model)
    critic_model_name = llm_client.resolve_model_ref(critic_ref)[0]

    # 两份修订预算分开记：机械问题（字数/禁用词/截断）与审稿意见（设定冲突）互不挤占。
    max_local_retries = settings.max_local_retries
    max_llm_retries = settings.max_critic_retries
    local_retries = 0
    llm_retries = 0
    while state["revision_count"] <= max_local_retries + max_llm_retries:
        revision = state["revision_count"]
        if revision == 0:
            stage_label = "writing"
            agent_label = "生成章节"
        else:
            stage_label = f"revising_{revision}"
            agent_label = f"修改（第{revision}次）"

        yield _sse("stage", stage_label)
        yield _sse_json("agent_start", {"agent": "writer", "label": agent_label, "model": writer_model_name})

        full_text = ""
        writer_in_tok = 0
        writer_out_tok = 0
        writer_truncated = False
        writer_payload = None
        writer_start = time.monotonic()
        if revision > 0 and state["generated_text"].strip():
            # 增量修订：回传上一版全文+审稿意见，只修正被指出的问题（省去完整上下文）
            writer_stream = writer.stream_chapter_revision(
                ctx=state["context"],
                previous_text=state["generated_text"],
                issues_feedback=state["critic_issues"],
                instruction=state["instruction"],
                target_words=state["target_words"],
                writer_model=novel.writer_model,
                writer_system_prompt=writer_system_prompt,
                temperature=getattr(novel, "writer_temperature", 0.85),
                use_custom_temperature=getattr(novel, "writer_use_custom_temperature", True),
                max_tokens=getattr(novel, "writer_max_tokens", 16384),
                gemini_thinking_level=getattr(novel, "gemini_thinking_level", "medium"),
                deepseek_thinking_level=getattr(novel, "deepseek_thinking_level", "high"),
                gemini_stream=getattr(novel, "gemini_stream", False),
            )
        else:
            writer_stream = writer.stream_chapter(
                ctx=state["context"],
                instruction=state["instruction"],
                target_words=state["target_words"],
                writer_model=novel.writer_model,
                issues_feedback=state["critic_issues"],
                writer_system_prompt=writer_system_prompt,
                writer_examples=writer_examples,
                temperature=getattr(novel, "writer_temperature", 0.85),
                use_custom_temperature=getattr(novel, "writer_use_custom_temperature", True),
                max_tokens=getattr(novel, "writer_max_tokens", 16384),
                gemini_thinking_level=getattr(novel, "gemini_thinking_level", "medium"),
                deepseek_thinking_level=getattr(novel, "deepseek_thinking_level", "high"),
                gemini_stream=getattr(novel, "gemini_stream", False),
            )
        async for item in writer_stream:
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
        state["writer_truncated"] = writer_truncated

        if full_text.strip() or revision == 0:
            state["generated_text"] = full_text
        else:
            # 修订输出为空时保留上一版正文，避免丢稿
            yield _sse("warning", "本次修订未返回内容，已保留上一版正文")
        if writer_payload and writer_payload.get("model"):
            state["model_used"] = writer_payload["model"]
        state["total_input_tokens"] += writer_in_tok
        state["total_output_tokens"] += writer_out_tok
        writer_duration = int((time.monotonic() - writer_start) * 1000)
        yield await _emit_llm_call(novel.id, chapter_number, {
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
            yield _sse_json("agent_start", {"agent": "critic", "label": "质量审查", "model": critic_model_name})
            critic_start = time.monotonic()
            passed, issues, critic_in_tok, critic_out_tok, critic_model = await critic.review_chapter(
                generated_text=state["generated_text"],
                ctx=state["context"],
                fast_model=getattr(novel, "critic_model", "") or novel.fast_model,
                target_words=state["target_words"],
            )
            critic_duration = int((time.monotonic() - critic_start) * 1000)
            state["passed"] = passed
            state["critic_issues"] = issues
            state["total_input_tokens"] += critic_in_tok
            state["total_output_tokens"] += critic_out_tok
            yield await _emit_llm_call(novel.id, chapter_number, {
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

            if not passed:
                is_local = critic_model == critic.LOCAL_PRECHECK_MODEL
                if is_local:
                    exhausted = local_retries >= max_local_retries
                else:
                    exhausted = llm_retries >= max_llm_retries
                yield _sse_json("critic_issues", {"issues_text": issues})
                if exhausted:
                    yield _sse(
                        "warning",
                        f"{'本地检查' if is_local else '质量审查'}仍未通过，"
                        f"修订次数已用完，保留当前版本。审稿意见见 Agent 日志。",
                    )
                    break
                # 首次 Critic 失败时，先发出初稿内容，让前端展示对比视图
                if state["revision_count"] == 0:
                    yield _sse_json("original_draft", {"text": state["generated_text"]})
                if is_local:
                    local_retries += 1
                else:
                    llm_retries += 1
                state["revision_count"] += 1
                continue
        else:
            # Critic 已关闭，继续执行可选的剧情细节审查
            state["passed"] = True

        # ── Node 3b: 剧情细节审查（可选，基于前 20 章） ───────────────
        if getattr(novel, "enable_detail_review", False):
            from app.agents import review_agent

            yield _sse("stage", "detail_reviewing")
            detail_model_override = getattr(novel, "detail_review_model", "") or ""
            detail_ref, _ = llm_client.get_agent_client("review", detail_model_override)
            detail_model = llm_client.resolve_model_ref(detail_ref)[0]
            yield _sse_json("agent_start", {"agent": "detail_review", "label": "剧情细节审查", "model": detail_model})
            detail_start = time.monotonic()
            try:
                detail_passed, detail_issues, detail_in_tok, detail_out_tok, detail_model = (
                    await asyncio.wait_for(
                        review_agent.review_generated_with_recent_chapters(
                            session=session,
                            novel=novel,
                            generated_text=state["generated_text"],
                            chapter_number=chapter_number,
                            volume=volume,
                            model_override=detail_model_override,
                        ),
                        timeout=settings.detail_review_timeout,
                    )
                )
            except asyncio.TimeoutError:
                detail_duration = int((time.monotonic() - detail_start) * 1000)
                logger.warning(
                    "剧情细节审查超时，跳过并保留当前修订稿: novel_id=%s chapter=%s "
                    "revision=%s model=%s timeout=%ss",
                    novel.id,
                    chapter_number,
                    state["revision_count"],
                    detail_model,
                    settings.detail_review_timeout,
                )
                yield await _emit_llm_call(novel.id, chapter_number, {
                    "agent": "detail_review",
                    "model": detail_model,
                    "status": "timeout",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "duration_ms": detail_duration,
                })
                yield _sse_json("agent_done", {
                    "agent": "detail_review",
                    "label": "剧情细节审查（超时跳过）",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "passed": False,
                })
                yield _sse(
                    "warning",
                    f"剧情细节审查超过 {int(settings.detail_review_timeout)} 秒未响应，"
                    "已跳过审查并保留当前修订稿。",
                )
                break
            except Exception as exc:
                detail_duration = int((time.monotonic() - detail_start) * 1000)
                logger.warning(
                    "剧情细节审查调用失败，跳过并保留当前修订稿: novel_id=%s chapter=%s "
                    "revision=%s model=%s error=%s",
                    novel.id,
                    chapter_number,
                    state["revision_count"],
                    detail_model,
                    exc,
                    exc_info=True,
                )
                yield await _emit_llm_call(novel.id, chapter_number, {
                    "agent": "detail_review",
                    "model": detail_model,
                    "status": "error",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "duration_ms": detail_duration,
                })
                yield _sse_json("agent_done", {
                    "agent": "detail_review",
                    "label": "剧情细节审查（连接失败，已跳过）",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "passed": False,
                })
                yield _sse(
                    "warning",
                    f"剧情细节审查模型 {detail_model} 连接失败，"
                    "已跳过审查并保留当前修订稿。请检查该模型的供应商及代理设置。",
                )
                break
            detail_duration = int((time.monotonic() - detail_start) * 1000)
            state["total_input_tokens"] += detail_in_tok
            state["total_output_tokens"] += detail_out_tok
            yield await _emit_llm_call(novel.id, chapter_number, {
                "agent": "detail_review",
                "model": detail_model,
                "status": "ok",
                "input_tokens": detail_in_tok,
                "output_tokens": detail_out_tok,
                "duration_ms": detail_duration,
            })
            yield _sse_json("agent_done", {
                "agent": "detail_review",
                "label": "剧情细节审查",
                "input_tokens": detail_in_tok,
                "output_tokens": detail_out_tok,
                "passed": detail_passed,
            })

            if detail_issues:
                yield _sse_json("review_result", {
                    "issues": detail_issues,
                    "input_tokens": detail_in_tok,
                    "output_tokens": detail_out_tok,
                    "model": detail_model,
                })

            if not detail_passed:
                # 细节审查是内容层判断，与 Critic 共用 LLM 那份预算
                if llm_retries >= max_llm_retries:
                    yield _sse(
                        "warning",
                        "剧情细节审查仍未通过，修订次数已用完，保留当前版本。",
                    )
                    break
                issue_text = "\n".join(
                    f"- {issue.get('description', '')}" for issue in detail_issues
                ).strip()
                state["critic_issues"] = f"剧情细节审查发现以下问题，请修订本章：\n{issue_text}"
                if state["revision_count"] == 0:
                    yield _sse_json("original_draft", {"text": state["generated_text"]})
                llm_retries += 1
                state["revision_count"] += 1
                continue

        break
