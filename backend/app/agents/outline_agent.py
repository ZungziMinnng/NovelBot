"""Outline Agent: 生成和管理故事大纲"""
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.novel import Novel
from app.models.character import Character
from app.models.memory import Outline
from app.services import llm_client
from app.prompts.loader import render

TARGET_LENGTH_CHAPTERS = {
    "短篇": 10,
    "中篇": 30,
    "长篇": 60,
}


async def generate_chapter_outlines(
    session: AsyncSession,
    novel: Novel,
) -> list[Outline]:
    """根据小说基本信息生成章级大纲"""
    result = await session.execute(
        select(Character).where(Character.novel_id == novel.id)
    )
    characters = result.scalars().all()
    chars_summary = "\n".join(
        f"- {c.name}（{c.role}）：{c.description}" for c in characters
    )

    chapter_count = TARGET_LENGTH_CHAPTERS.get(novel.target_length, 30)

    prompt = render(
        "outline.jinja2",
        title=novel.title,
        genre=novel.genre,
        target_length=novel.target_length,
        writing_style=novel.writing_style,
        premise=novel.premise,
        core_setting=novel.core_setting[:500],
        characters_summary=chars_summary or "（角色待定）",
        chapter_count=chapter_count,
    )

    model, api_format = llm_client.get_agent_client("outline", novel.fast_model)
    raw = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.7,
        max_tokens=4096,
    )

    outlines = _parse_outlines(raw, novel.id)
    for o in outlines:
        session.add(o)
    return outlines


def _parse_outlines(raw: str, novel_id: int) -> list[Outline]:
    """解析大纲文本为 Outline 对象列表"""
    outlines = []
    pattern = re.compile(r"第(\d+)章[：:]\s*(.+)\n([\s\S]*?)(?=第\d+章|$)")
    matches = pattern.findall(raw)

    for chapter_num_str, title, content in matches:
        chapter_num = int(chapter_num_str)
        outlines.append(Outline(
            novel_id=novel_id,
            level="chapter",
            volume=1,
            chapter_number=chapter_num,
            title=title.strip(),
            content=f"{title.strip()}\n{content.strip()}",
        ))

    if not outlines:
        # fallback: 按行分割
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        for i, line in enumerate(lines, 1):
            outlines.append(Outline(
                novel_id=novel_id,
                level="chapter",
                volume=1,
                chapter_number=i,
                title=f"第{i}章",
                content=line,
            ))
    return outlines
