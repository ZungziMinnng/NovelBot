"""Full-text Review Agent: 全文审查，检测情节矛盾、角色不一致等全局问题"""
import asyncio
import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.character import Character
from app.services import llm_client

logger = logging.getLogger(__name__)

BATCH_SIZE = 20

ISSUE_TYPES = {
    "plot_contradiction": "情节矛盾",
    "character_inconsistency": "角色不一致",
    "forgotten_thread": "遗忘伏笔",
    "timeline_error": "时间线错误",
    "setting_violation": "设定违背",
    "other": "其他",
}


def _build_other_summaries(all_chapters: list[Chapter], batch_chapters: list[Chapter]) -> str:
    """为当前批次构建其余章节的摘要上下文。"""
    batch_ids = {ch.id for ch in batch_chapters}
    parts: list[str] = []
    for ch in all_chapters:
        if ch.id in batch_ids:
            continue
        summary = (ch.summary or "").strip()
        if not summary:
            summary = (ch.content or "")[:200] + "..."
        parts.append(f"第{ch.number}章 {ch.title or ''}：{summary}")
    return "\n".join(parts)


async def run_fulltext_review(
    session: AsyncSession,
    novel: Novel,
) -> tuple[list[dict], int, int, str]:
    """
    分批审查：每 BATCH_SIZE 章一批并行送审，汇总所有问题。
    每批附带其余章节的摘要作为上下文，确保能发现跨批次矛盾。
    返回 (issues[], input_tokens, output_tokens, model)
    """
    result = await session.execute(
        select(Chapter)
        .where(Chapter.novel_id == novel.id, Chapter.content != "")
        .order_by(Chapter.number)
    )
    chapters = result.scalars().all()
    if not chapters:
        return [], 0, 0, ""

    char_result = await session.execute(
        select(Character).where(Character.novel_id == novel.id)
    )
    chars = char_result.scalars().all()
    char_list = ""
    for c in chars:
        char_list += f"- {c.name}（{c.role}）：{c.description[:100] if c.description else '无描述'}\n"

    world_setting = (novel.core_setting or "")[:2000]
    model, api_format = llm_client.get_agent_client("review")

    batches = [chapters[i:i + BATCH_SIZE] for i in range(0, len(chapters), BATCH_SIZE)]

    if len(batches) == 1:
        issues, in_tok, out_tok = await _review_batch(
            novel, batches[0], chapters, char_list, world_setting, model, api_format,
        )
        return issues, in_tok, out_tok, model

    tasks = [
        _review_batch(novel, batch, chapters, char_list, world_setting, model, api_format)
        for batch in batches
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_issues: list[dict] = []
    total_in = 0
    total_out = 0
    for r in results:
        if isinstance(r, Exception):
            logger.error("分批审查某批失败: %s", r)
            continue
        issues, in_tok, out_tok = r
        all_issues.extend(issues)
        total_in += in_tok
        total_out += out_tok

    return all_issues, total_in, total_out, model


async def _review_batch(
    novel: Novel,
    batch_chapters: list[Chapter],
    all_chapters: list[Chapter],
    char_list: str,
    world_setting: str,
    model: str,
    api_format: str,
) -> tuple[list[dict], int, int]:
    """审查单批章节，返回 (issues[], input_tokens, output_tokens)"""
    text_parts = []
    total_words = 0
    for ch in batch_chapters:
        text_parts.append(f"=== 第{ch.number}章 {ch.title or ''} ===\n{ch.content}")
        total_words += ch.word_count or 0
    full_text = "\n\n".join(text_parts)

    start_num = batch_chapters[0].number
    end_num = batch_chapters[-1].number
    type_list = "\n".join(f"- {k}: {v}" for k, v in ISSUE_TYPES.items())

    other_summaries = _build_other_summaries(all_chapters, batch_chapters)

    system_prompt = (
        "你是一位专业的小说审稿编辑，擅长发现长篇小说中的全局性问题。"
        "你需要仔细阅读重点章节的全文，并结合其余章节的摘要，检查以下类型的问题：\n"
        f"{type_list}\n\n"
        "要求：\n"
        "1. 只报告确实存在的问题，不要捏造\n"
        "2. 每个问题注明涉及的章节号\n"
        "3. severity 分为 high/medium/low\n"
        "4. 特别注意重点章节与其余章节摘要之间的矛盾和不一致\n"
        "5. 如果没有发现问题，返回空数组 []\n"
        "6. 严格以 JSON 数组格式返回，不要其他文字"
    )

    other_section = ""
    if other_summaries:
        other_section = f"【其余章节摘要（供交叉比对）】\n{other_summaries}\n\n"

    user_prompt = (
        f"以下是《{novel.title}》的审查任务。重点审查第{start_num}~{end_num}章（全文），"
        f"共{len(batch_chapters)}章、约{total_words}字。\n\n"
        f"【角色名单】\n{char_list or '（无角色信息）'}\n\n"
        f"【世界观设定】\n{world_setting or '（无设定）'}\n\n"
        f"{other_section}"
        f"【重点章节全文（第{start_num}~{end_num}章）】\n{full_text}\n\n"
        "请审查以上内容，找出所有一致性问题。以 JSON 数组返回：\n"
        '[{"type": "issue_type", "severity": "high/medium/low", '
        '"chapters": [章节号], "description": "问题描述"}]'
    )

    raw, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=model,
        api_format=api_format,
        temperature=0.3,
        max_tokens=4096,
    )

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]

    try:
        issues = json.loads(raw)
        if not isinstance(issues, list):
            issues = []
    except json.JSONDecodeError:
        logger.warning("审查结果 JSON 解析失败，原文: %s", raw[:500])
        issues = [{"type": "other", "severity": "low", "chapters": [], "description": raw[:500]}]

    return issues, in_tok, out_tok
