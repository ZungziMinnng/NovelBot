"""编辑器选段改写 / 扩写 / 缩写：只改作者选中的那段，前后文只作衔接参考。

不落库：结果回前端给作者看，接受了才替换进编辑框，再走正常的保存（会进历史版本）。
"""
import logging
import time

from app.database import AsyncSessionLocal
from app.models.llm_usage import LlmUsage
from app.models.novel import Novel
from app.prompts.loader import render
from app.services import llm_client

logger = logging.getLogger(__name__)

MODE_LABELS = {"rewrite": "改写", "expand": "扩写", "condense": "缩写"}
# 目标字数相对原文的倍数
_RATIO = {"rewrite": 1.0, "expand": 1.8, "condense": 0.6}
# 前后文各截多少字给模型参考，够衔接就行
BEFORE_CHARS = 1500
AFTER_CHARS = 800


def target_words(mode: str, selected: str) -> int:
    return max(20, int(len(selected.strip()) * _RATIO[mode]))


def build_messages(novel: Novel, mode: str, before: str, selected: str, after: str, instruction: str) -> list[dict]:
    system = render(
        "passage_rewrite.jinja2",
        genre=novel.genre or "",
        writing_style=novel.writing_style or "",
        mode=mode,
        mode_label=MODE_LABELS[mode],
        target_words=target_words(mode, selected),
        instruction=instruction.strip(),
    )
    before = before[-BEFORE_CHARS:].strip()
    after = after[:AFTER_CHARS].strip()
    parts = []
    if before:
        parts.append(f"=== 前文（只作参考，不要输出）===\n{before}")
    parts.append(f"=== 选中的段落（{MODE_LABELS[mode]}这一段）===\n{selected.strip()}")
    if after:
        parts.append(f"=== 后文（只作参考，不要输出）===\n{after}")
    parts.append(f"请直接输出{MODE_LABELS[mode]}后的选中段落。")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


async def run(novel: Novel, mode: str, before: str, selected: str, after: str,
              instruction: str = "", model_override: str = "") -> str:
    messages = build_messages(novel, mode, before, selected, after, instruction)
    model, api_format = llm_client.get_agent_client("writer", model_override or novel.writer_model or "")
    real_model = llm_client.resolve_model_ref(model)[0]
    max_tokens = max(1024, target_words(mode, selected) * 3)
    t0 = time.monotonic()
    status = "ok"
    in_tok = out_tok = 0
    try:
        content, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
            messages, model, api_format, temperature=0.7, max_tokens=max_tokens,
        )
    except Exception:
        status = "error"
        raise
    finally:
        try:
            async with AsyncSessionLocal() as s:
                s.add(LlmUsage(
                    novel_id=novel.id, chapter_number=0, agent="passage_rewrite",
                    model=real_model or "", status=status,
                    input_tokens=int(in_tok or 0), output_tokens=int(out_tok or 0),
                    duration_ms=int((time.monotonic() - t0) * 1000),
                ))
                await s.commit()
        except Exception:
            logger.warning("LLM 用量记账失败（已忽略）", exc_info=True)
    return (content or "").strip()
