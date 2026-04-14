import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.memory import Outline
from app.services import vector_store, summarizer


async def build_generation_context(
    session: AsyncSession,
    novel: Novel,
    chapter_number: int,
    volume: int = 1,
    scene_hint: str = "",
) -> dict:
    """
    组装生成章节所需的全部上下文，返回结构化 dict。
    各 Agent 从这个 dict 中取自己需要的部分。
    """
    ctx = {}

    # 1. 核心设定（世界观，始终携带）
    ctx["core_setting"] = novel.core_setting[:1000] if novel.core_setting else ""

    # 2. 角色状态卡（结构化，节约 token）
    result = await session.execute(
        select(Character).where(Character.novel_id == novel.id)
    )
    characters = result.scalars().all()
    ctx["characters"] = [
        {
            "name": c.name,
            "role": c.role,
            "description": c.description,
            "sheet": c.full_sheet,
            "state": c.current_state,
        }
        for c in characters
    ]

    # 3. 大纲：当前章节目标
    outline_result = await session.execute(
        select(Outline).where(
            Outline.novel_id == novel.id,
            Outline.level == "chapter",
            Outline.volume == volume,
            Outline.chapter_number == chapter_number,
        )
    )
    outline = outline_result.scalar_one_or_none()
    ctx["chapter_outline"] = outline.content if outline else ""

    # 4. 最近章节摘要（滚动窗口）
    ctx["rolling_summary"] = await summarizer.get_rolling_summary(
        session, novel.id, chapter_number, max_summaries=5
    )

    # 5. RAG 检索相关历史场景
    query = scene_hint or ctx["chapter_outline"] or f"第{chapter_number}章"
    retrieved = vector_store.search_similar(novel.id, query, top_k=3)
    ctx["rag_context"] = "\n\n".join(retrieved)

    # 6. 即时上下文：上一章末尾 500 字
    prev_result = await session.execute(
        select(Chapter).where(
            Chapter.novel_id == novel.id,
            Chapter.number == chapter_number - 1,
            Chapter.volume == volume,
        )
    )
    prev_chapter = prev_result.scalar_one_or_none()
    ctx["recent_text"] = prev_chapter.content[-500:] if prev_chapter else ""

    # 7. 元信息
    ctx["novel_title"] = novel.title
    ctx["genre"] = novel.genre
    ctx["writing_style"] = novel.writing_style
    ctx["chapter_number"] = chapter_number
    ctx["volume"] = volume

    return ctx


def format_context_for_writer(ctx: dict, instruction: str = "", target_words: int = 800) -> str:
    """将 context dict 格式化为 Writer Agent 的 Prompt 输入"""
    chars_text = ""
    for c in ctx.get("characters", []):
        state = c.get("state", {})
        chars_text += f"【{c['name']}·{c['role']}】{c['description']}\n"
        if state:
            chars_text += f"  当前状态：{json.dumps(state, ensure_ascii=False)}\n"

    parts = []
    if ctx.get("core_setting"):
        parts.append(f"=== 世界观设定 ===\n{ctx['core_setting']}")
    if chars_text:
        parts.append(f"=== 角色状态 ===\n{chars_text.strip()}")
    if ctx.get("chapter_outline"):
        parts.append(f"=== 本章大纲 ===\n{ctx['chapter_outline']}")
    if ctx.get("rolling_summary"):
        parts.append(f"=== 近期剧情摘要 ===\n{ctx['rolling_summary']}")
    if ctx.get("rag_context"):
        parts.append(f"=== 相关历史场景（参考）===\n{ctx['rag_context']}")
    if ctx.get("recent_text"):
        parts.append(f"=== 上章结尾 ===\n{ctx['recent_text']}")

    user_instruction = f"\n用户要求：{instruction}" if instruction else ""

    task = (
        f"\n=== 写作任务 ===\n"
        f"请为《{ctx.get('novel_title', '')}》写第{ctx.get('volume', 1)}卷"
        f"第{ctx.get('chapter_number', 1)}章，"
        f"风格：{ctx.get('writing_style', '')}，"
        f"目标字数约 {target_words} 字。"
        f"{user_instruction}\n"
        f"直接输出正文内容，不要输出章节标题或任何前缀。"
    )
    parts.append(task)
    return "\n\n".join(parts)
