import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.chapter import Chapter
from app.models.memory import Memory, Outline
from app.models.character import Character
from app.models.novel import Novel
from app.services import llm_client, vector_store
from app.config import settings


CHAPTER_SUMMARY_PROMPT = """请将以下章节内容压缩为100字以内的摘要，保留关键情节转折、人物行动和重要信息，去掉环境描写和对话细节。

章节内容：
{content}

只输出摘要文本，不要任何前缀。"""


CHARACTER_UPDATE_PROMPT = """根据以下章节内容，更新角色状态。对每个出现的角色，提取：位置变化、目标变化、新获得的信息、关系变化。

小说当前角色状态：
{character_states}

本章内容：
{content}

以 JSON 格式输出，格式为：
{{
  "角色名": {{
    "location": "当前位置",
    "current_goal": "当前目标",
    "known_secrets": ["知道的秘密列表"],
    "relationship_changes": {{"其他角色名": "关系描述"}}
  }}
}}

只输出 JSON，不要任何解释。"""


async def summarize_chapter(
    session: AsyncSession,
    chapter: Chapter,
    novel: Novel,
) -> str:
    """生成章节摘要并存储"""
    if not chapter.content.strip():
        return ""

    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
    prompt = CHAPTER_SUMMARY_PROMPT.format(content=chapter.content[:3000])
    summary = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.3,
        max_tokens=200,
    )

    # 保存摘要到章节
    chapter.summary = summary
    chapter.word_count = len(chapter.content)

    # 存入 Memory 表
    memory = Memory(
        novel_id=novel.id,
        chapter_id=chapter.id,
        memory_type="chapter_summary",
        content=summary,
        volume=chapter.volume,
        chapter_number=chapter.number,
    )
    session.add(memory)

    # 存入向量库
    vector_store.store_text(
        novel_id=novel.id,
        doc_id=f"chapter_{chapter.id}_summary",
        text=summary,
        metadata={
            "type": "chapter_summary",
            "volume": chapter.volume,
            "chapter_number": chapter.number,
        },
    )
    # 原文分段存入向量库（每500字一段）
    chunks = [chapter.content[i:i+500] for i in range(0, len(chapter.content), 500)]
    for idx, chunk in enumerate(chunks):
        vector_store.store_text(
            novel_id=novel.id,
            doc_id=f"chapter_{chapter.id}_chunk_{idx}",
            text=chunk,
            metadata={
                "type": "chapter_content",
                "volume": chapter.volume,
                "chapter_number": chapter.number,
            },
        )
    return summary


async def update_character_states(
    session: AsyncSession,
    chapter: Chapter,
    novel: Novel,
) -> None:
    """根据章节内容更新角色状态卡"""
    result = await session.execute(
        select(Character).where(Character.novel_id == novel.id)
    )
    characters = result.scalars().all()
    if not characters:
        return

    states_text = json.dumps(
        {c.name: c.current_state for c in characters},
        ensure_ascii=False,
        indent=2,
    )
    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
    prompt = CHARACTER_UPDATE_PROMPT.format(
        character_states=states_text,
        content=chapter.content[:3000],
    )
    try:
        raw = await llm_client.dispatch_chat_complete(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            api_format=api_format,
            temperature=0.2,
            max_tokens=800,
        )
        updates = json.loads(raw.strip())
        char_map = {c.name: c for c in characters}
        for name, state in updates.items():
            if name in char_map:
                char_map[name].current_state = state
    except Exception:
        pass  # 状态更新失败不阻塞流程


async def get_rolling_summary(
    session: AsyncSession,
    novel_id: int,
    current_chapter_number: int,
    max_summaries: int = 5,
) -> str:
    """获取最近 N 章摘要拼接"""
    result = await session.execute(
        select(Memory)
        .where(
            Memory.novel_id == novel_id,
            Memory.memory_type == "chapter_summary",
            Memory.chapter_number < current_chapter_number,
        )
        .order_by(Memory.chapter_number.desc())
        .limit(max_summaries)
    )
    memories = result.scalars().all()
    if not memories:
        return ""
    parts = [f"第{m.chapter_number}章摘要：{m.content}" for m in reversed(memories)]
    return "\n".join(parts)
