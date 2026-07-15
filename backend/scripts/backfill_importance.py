"""一次性回填脚本：用 AI 给「已存在」的记忆/实体打重要性分（1-5）。

把分数回填到 SQL 的 importance 列，并同步刷新 ChromaDB metadata
（摘要只改标签、不重新嵌入；实体走 reindex 重建）。可重复运行，幂等（仅覆盖分数）。

用法（在 backend 目录下）：
    python -m scripts.backfill_importance --novel <id>
    python -m scripts.backfill_importance --novel all
"""
import argparse
import asyncio
import json
import logging

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.novel import Novel
from app.models.memory import Memory
from app.models.world_entity import WorldEntity
from app.models.location import Location
from app.models.faction import Faction
from app.models.technique import Technique
from app.models.novel_note import NovelNote
# 确保所有被 relationship 引用的 mapper 都已注册（否则首次查询 Novel 会报 Volume 等找不到）
from app.models import (  # noqa: F401
    chapter,
    character,
    model_library,
    writer_preset,
    api_provider,
    volume,
    worldview_change,
)
from app.prompts.loader import render
from app.services import llm_client, vector_store
from app.services.entity_embeddings import (
    reindex_all_entities,
    _entity_text,
    _location_text,
    _faction_text,
    _technique_text,
)
from app.services.llm_json import repair_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill_importance")


async def _score_one(content: str, type_label: str, model: str, api_format: str) -> int:
    """调 LLM 给一条内容打 1-5 分，失败回退中性分 3。"""
    if not content.strip():
        return 3
    prompt = render("importance_score.jinja2", mem_type=type_label, content=content[:2000])
    try:
        raw = await llm_client.dispatch_chat_complete(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            api_format=api_format,
            temperature=0.2,
            max_tokens=100,
        )
        data = json.loads(repair_json(raw))
        imp = int(round(float(data.get("importance", 3))))
        return max(1, min(5, imp))
    except Exception:
        log.warning("打分失败，回退为 3：%s", content[:40], exc_info=True)
        return 3


async def _backfill_summaries(session, novel: Novel, model: str, api_format: str) -> int:
    rows = (await session.execute(
        select(Memory).where(
            Memory.novel_id == novel.id,
            Memory.memory_type == "chapter_summary",
        )
    )).scalars().all()
    for m in rows:
        imp = await _score_one(m.content, "章节剧情梗概", model, api_format)
        m.importance = imp
        if m.embedding_id:
            await vector_store.aupdate_metadata(
                novel.id,
                m.embedding_id,
                {
                    "type": "chapter_summary",
                    "volume": m.volume,
                    "chapter_number": m.chapter_number,
                    "importance": imp,
                },
            )
        log.info("摘要 #%d (第%d章) → importance=%d", m.id, m.chapter_number, imp)
    await session.commit()
    return len(rows)


async def _backfill_entities(session, novel: Novel, model: str, api_format: str) -> dict:
    counts: dict[str, int] = {}

    entities = (await session.execute(
        select(WorldEntity).where(WorldEntity.novel_id == novel.id)
    )).scalars().all()
    for e in entities:
        e.importance = await _score_one(_entity_text(e), "道具/系统设定", model, api_format)
    counts["entity"] = len(entities)

    locations = (await session.execute(
        select(Location).where(Location.novel_id == novel.id)
    )).scalars().all()
    loc_map = {loc.id: loc for loc in locations}
    for loc in locations:
        parent_name = loc_map[loc.parent_id].name if loc.parent_id and loc.parent_id in loc_map else ""
        loc.importance = await _score_one(_location_text(loc, parent_name), "地点设定", model, api_format)
    counts["location"] = len(locations)

    factions = (await session.execute(
        select(Faction).where(Faction.novel_id == novel.id)
    )).scalars().all()
    for f in factions:
        f.importance = await _score_one(_faction_text(f), "势力设定", model, api_format)
    counts["faction"] = len(factions)

    techniques = (await session.execute(
        select(Technique).where(Technique.novel_id == novel.id)
    )).scalars().all()
    for t in techniques:
        t.importance = await _score_one(_technique_text(t), "功法设定", model, api_format)
    counts["technique"] = len(techniques)

    notes = (await session.execute(
        select(NovelNote).where(NovelNote.novel_id == novel.id)
    )).scalars().all()
    for n in notes:
        n.importance = await _score_one(f"{n.title}\n{n.content}", "补充设定", model, api_format)
    counts["note"] = len(notes)

    await session.commit()

    # 实体（道具/系统/地点/势力/功法）的向量 metadata 通过整体重建刷新（已含 importance）。
    # 重建需调嵌入服务，失败时只警告：SQL 分数已落库，待嵌入恢复后单独重跑 reindex 即可。
    try:
        await reindex_all_entities(session, novel.id)
    except Exception:
        log.warning("实体向量重建失败（SQL 分数已落库，嵌入服务恢复后可重跑）", exc_info=True)
    # 补充设定笔记不在 reindex 范围内，单独刷新其向量标签（仅改标签、不重新嵌入）
    for n in notes:
        if n.content.strip():
            try:
                await vector_store.aupdate_metadata(
                    novel.id,
                    f"note_{n.id}",
                    {"type": "novel_note", "note_id": n.id, "importance": n.importance},
                )
            except Exception:
                log.warning("笔记 #%d 向量标签刷新失败（SQL 已落库）", n.id, exc_info=True)

    return counts


async def _backfill_novel(session, novel: Novel, override_model: str = "") -> None:
    if override_model:
        model, api_format = override_model, llm_client.get_model_api_format(override_model)
    else:
        model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
    log.info("=== 开始回填小说 #%d《%s》 model=%s fmt=%s ===", novel.id, novel.title, model, api_format)
    n_sum = await _backfill_summaries(session, novel, model, api_format)
    ent_counts = await _backfill_entities(session, novel, model, api_format)
    log.info("=== 小说 #%d 完成：摘要 %d 条，实体 %s ===", novel.id, n_sum, ent_counts)


async def _reindex_only_novel(session, novel: Novel) -> None:
    """跳过打分，只用已落库的 SQL importance 重建实体向量标签（嵌入服务恢复后补刷用）。"""
    log.info("=== 仅重建实体向量 小说 #%d《%s》 ===", novel.id, novel.title)
    await reindex_all_entities(session, novel.id)
    notes = (await session.execute(
        select(NovelNote).where(NovelNote.novel_id == novel.id)
    )).scalars().all()
    for n in notes:
        if n.content.strip():
            await vector_store.aupdate_metadata(
                novel.id,
                f"note_{n.id}",
                {"type": "novel_note", "note_id": n.id, "importance": n.importance},
            )
    log.info("=== 小说 #%d 实体向量重建完成 ===", novel.id)


async def main() -> None:
    parser = argparse.ArgumentParser(description="AI 回填记忆/实体的重要性分（1-5）")
    parser.add_argument("--novel", required=True, help="小说 id，或 all 表示全部")
    parser.add_argument("--model", default="", help="覆盖打分用的 chat 模型（默认用 memory 类别解析）")
    parser.add_argument("--reindex-only", action="store_true", help="跳过打分，仅用已有 SQL 分数重建实体向量标签")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        if args.novel == "all":
            novels = (await session.execute(select(Novel))).scalars().all()
        else:
            novel = await session.get(Novel, int(args.novel))
            novels = [novel] if novel else []

        if not novels:
            log.error("未找到小说：%s", args.novel)
            return

        for novel in novels:
            if args.reindex_only:
                await _reindex_only_novel(session, novel)
            else:
                await _backfill_novel(session, novel, args.model)


if __name__ == "__main__":
    asyncio.run(main())
