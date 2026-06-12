"""Outline Agent: 生成和管理故事大纲"""
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.novel import Novel
from app.models.character import Character
from app.models.memory import Outline
from app.models.volume import Volume
from app.services import llm_client
from app.prompts.loader import render

TARGET_LENGTH_PLAN = {
    "超短篇": (1, 10),
    "短篇": (3, 30),
    "中篇": (6, 60),
    "长篇": (10, 100),
}
MAX_INITIAL_CHAPTER_OUTLINES = 120


def _outline_max_tokens(chapter_count: int) -> int:
    if chapter_count <= 20:
        return 4096
    if chapter_count <= 60:
        return 8192
    if chapter_count <= 100:
        return 16384
    return 32768


async def generate_chapter_outlines(
    session: AsyncSession,
    novel: Novel,
    nsfw_mode: bool = False,
) -> list[Outline]:
    """根据小说基本信息生成章级大纲；开启分卷时生成卷级范围大纲。"""
    result = await session.execute(
        select(Character).where(Character.novel_id == novel.id)
    )
    characters = result.scalars().all()
    chars_summary = "\n".join(
        f"- {c.name}（{c.role}）：{c.description}" for c in characters
    )

    default_volumes, default_chapters = TARGET_LENGTH_PLAN.get(novel.target_length, (3, 30))
    total_chapters = novel.estimated_chapters if novel.estimated_chapters > 0 else default_chapters
    volume_count = default_volumes if novel.enable_volume_split else 1
    if novel.enable_volume_split and novel.estimated_chapters > 0:
        volume_count = max(default_volumes, min(20, (total_chapters + 49) // 50))
    chapter_count = total_chapters if novel.enable_volume_split else min(total_chapters, MAX_INITIAL_CHAPTER_OUTLINES)

    prompt = render(
        "outline.jinja2",
        title=novel.title,
        genre=novel.genre,
        target_length=novel.target_length,
        writing_style=novel.writing_style,
        premise=novel.premise,
        core_setting=novel.core_setting[:500],
        characters_summary=chars_summary or "（角色待定）",
        volume_count=volume_count,
        chapter_count=chapter_count,
        total_chapters=total_chapters,
        chapters_per_volume=max(1, chapter_count // volume_count),
        volume_mode=novel.enable_volume_split,
    )

    model, api_format = llm_client.get_agent_client("outline", novel.fast_model)
    raw = await llm_client.dispatch_chat_complete(
        messages=[
            {"role": "system", "content": "你是小说策划编辑，只输出可解析的大纲内容。"},
            {"role": "user", "content": prompt},
        ],
        model=model,
        api_format=api_format,
        temperature=0.7,
        max_tokens=_outline_max_tokens(volume_count if novel.enable_volume_split else chapter_count),
    )
    if not (raw or "").strip():
        raise RuntimeError("LLM 未返回大纲内容，可能是模型安全过滤、超时或供应商返回空响应。")

    if novel.enable_volume_split:
        outlines, volume_titles = _parse_volume_outlines(raw, novel.id, total_chapters)
    else:
        outlines, volume_titles = _parse_outlines(raw, novel.id)
    if not outlines:
        raise RuntimeError("LLM 返回了内容，但未能解析出任何大纲条目。")
    for number, title in volume_titles.items():
        existing = await session.execute(
            select(Volume).where(Volume.novel_id == novel.id, Volume.number == number)
        )
        volume = existing.scalar_one_or_none()
        if volume:
            volume.title = title
        else:
            session.add(Volume(novel_id=novel.id, number=number, title=title))
    for o in outlines:
        session.add(o)
    return outlines


def _parse_chapters(block: str, novel_id: int, volume: int, last_chapter: int) -> tuple[list[Outline], int]:
    outlines: list[Outline] = []
    pattern = re.compile(r"第(\d+)章[：:\s]+(.+)\n([\s\S]*?)(?=第\d+章|$)")
    matches = pattern.findall(block)

    for chapter_num_str, title, content in matches:
        chapter_num = int(chapter_num_str)
        if chapter_num <= last_chapter:
            chapter_num = last_chapter + 1
        last_chapter = chapter_num
        outlines.append(Outline(
            novel_id=novel_id,
            level="chapter",
            volume=volume,
            chapter_number=chapter_num,
            start_chapter=chapter_num,
            end_chapter=chapter_num,
            title=title.strip(),
            content=f"{title.strip()}\n{content.strip()}",
        ))
    return outlines, last_chapter


def _parse_outlines(raw: str, novel_id: int) -> tuple[list[Outline], dict[int, str]]:
    """解析大纲文本为 Outline 对象列表"""
    raw = raw.replace("\r\n", "\n")
    outlines: list[Outline] = []
    volume_titles: dict[int, str] = {}
    volume_pattern = re.compile(r"第(\d+)卷[：:\s]+(.+)")
    volume_matches = list(volume_pattern.finditer(raw))
    last_chapter = 0

    if volume_matches:
        for idx, match in enumerate(volume_matches):
            volume_num = int(match.group(1))
            title = match.group(2).strip()
            volume_titles[volume_num] = title if title.startswith(f"第{volume_num}卷") else f"第{volume_num}卷 {title}"
            start = match.end()
            end = volume_matches[idx + 1].start() if idx + 1 < len(volume_matches) else len(raw)
            parsed, last_chapter = _parse_chapters(raw[start:end], novel_id, volume_num, last_chapter)
            outlines.extend(parsed)
    else:
        parsed, last_chapter = _parse_chapters(raw, novel_id, 1, last_chapter)
        outlines.extend(parsed)
        if outlines:
            volume_titles[1] = "第1卷"

    if not outlines:
        # fallback: 按行分割
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        for i, line in enumerate(lines, 1):
            outlines.append(Outline(
                novel_id=novel_id,
                level="chapter",
                volume=1,
                chapter_number=i,
                start_chapter=i,
                end_chapter=i,
                title=f"第{i}章",
                content=line,
            ))
        if outlines:
            volume_titles[1] = "第1卷"
    return outlines, volume_titles


def _parse_volume_outlines(raw: str, novel_id: int, total_chapters: int) -> tuple[list[Outline], dict[int, str]]:
    raw = raw.replace("\r\n", "\n")
    outlines: list[Outline] = []
    volume_titles: dict[int, str] = {}
    volume_pattern = re.compile(r"第(\d+)卷[：:\s]+(.+)")
    matches = list(volume_pattern.finditer(raw))
    if not matches:
        return _parse_outlines(raw, novel_id)

    for idx, match in enumerate(matches):
        volume_num = int(match.group(1))
        title = match.group(2).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
        block = raw[start:end].strip()
        range_match = re.search(r"(?:覆盖章节|章节范围|范围)[：:\s]*第?(\d+)章?\s*[-~—至到]\s*第?(\d+)章?", block)
        if range_match:
            start_chapter = int(range_match.group(1))
            end_chapter = int(range_match.group(2))
        else:
            start_chapter = max(1, ((volume_num - 1) * total_chapters // len(matches)) + 1)
            end_chapter = max(start_chapter, volume_num * total_chapters // len(matches))

        volume_title = title if title.startswith(f"第{volume_num}卷") else f"第{volume_num}卷 {title}"
        volume_titles[volume_num] = volume_title
        outlines.append(Outline(
            novel_id=novel_id,
            level="volume",
            volume=volume_num,
            chapter_number=start_chapter,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            title=volume_title,
            content=block or volume_title,
        ))

    return outlines, volume_titles
