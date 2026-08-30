"""关系里程碑抽取与回填测试：落库格式、幂等、字段规整。"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry  # noqa: F401
from app.models.chapter import Chapter
from app.models.memory import Memory
from app.models.novel import Novel
from app.services import summarizer

_KNOWN_EMPTY = dict(
    known_char_names=[], known_entity_names=[], known_locations=[],
    known_tech_names=[], known_faction_names=[],
)

_MILESTONE_PAYLOAD = {
    "day_offset": 0, "period": "", "importance": 3,
    "summary": "林砚向苏晚表白。",
    "characters": [], "entities": [], "locations": [], "techniques": [], "factions": [],
    "threads": [],
    "milestones": [
        {"characters": ["林砚", "苏晚"], "type": "表白", "description": "天台雨夜，林砚坦白身世后表白", "importance": 4},
    ],
}


class MilestoneExtractTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    async def _make_env(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)()
        novel = Novel(title="测试")
        session.add(novel)
        await session.flush()
        ch = Chapter(novel_id=novel.id, number=37, volume=1, content="天台雨夜，林砚向苏晚表白。")
        session.add(ch)
        await session.flush()
        return engine, session, novel, ch

    async def _milestones(self, session):
        return (await session.execute(
            select(Memory).where(Memory.memory_type == "relationship_milestone")
        )).scalars().all()

    def test_save_milestones_content_format(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env()
            try:
                await summarizer._save_milestones(
                    session, novel, ch, _MILESTONE_PAYLOAD["milestones"],
                )
                rows = await self._milestones(session)
                self.assertEqual(len(rows), 1)
                m = rows[0]
                self.assertEqual(m.content, "[表白] 林砚↔苏晚 | 第37章 | 天台雨夜，林砚坦白身世后表白")
                self.assertEqual(m.chapter_number, 37)
                self.assertEqual(m.importance, 4)
                self.assertEqual(m.chapter_id, ch.id)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_save_milestones_idempotent_on_reconfirm(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env()
            try:
                await summarizer._save_milestones(session, novel, ch, _MILESTONE_PAYLOAD["milestones"])
                await summarizer._save_milestones(session, novel, ch, _MILESTONE_PAYLOAD["milestones"])
                rows = await self._milestones(session)
                self.assertEqual(len(rows), 1)  # 先删后插，不翻倍
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_save_milestones_field_coercion(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env()
            try:
                await summarizer._save_milestones(session, novel, ch, [
                    {"characters": ["甲"], "type": "不存在的类型", "description": "契机", "importance": 99},
                    {"characters": [], "type": "初见", "description": "无角色应跳过"},
                    {"characters": ["乙"], "type": "初见", "description": ""},
                    "不是字典",
                ])
                rows = await self._milestones(session)
                self.assertEqual(len(rows), 1)
                self.assertTrue(rows[0].content.startswith("[其他] 甲"))
                self.assertEqual(rows[0].importance, 5)  # 99 → 夹取到 5
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_save_milestones_non_list_noop(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env()
            try:
                await summarizer._save_milestones(session, novel, ch, _MILESTONE_PAYLOAD["milestones"])
                # 模型未按新格式输出（无 milestones 键）→ 不删不改
                await summarizer._save_milestones(session, novel, ch, None)
                rows = await self._milestones(session)
                self.assertEqual(len(rows), 1)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_summarize_and_discover_saves_milestones(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env()
            try:
                async def fake_call_json(messages, model, api_format, **kw):
                    return _MILESTONE_PAYLOAD, 100, 50

                with patch.object(summarizer.vector_store, "ensure_embedding_configured", AsyncMock()), \
                     patch.object(summarizer.vector_store, "astore_text", AsyncMock()), \
                     patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    summary, discovered, _, _ = await summarizer.summarize_and_discover(
                        session, ch, novel, **_KNOWN_EMPTY,
                    )
                self.assertIn("表白", summary)
                rows = await self._milestones(session)
                self.assertEqual(len(rows), 1)
                self.assertIn("林砚↔苏晚", rows[0].content)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_backfill_extracts_and_reruns_idempotent(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env()
            try:
                async def fake_call_json(messages, model, api_format, **kw):
                    return {"milestones": _MILESTONE_PAYLOAD["milestones"]}, 10, 5

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    n1 = await summarizer.backfill_milestones_for_chapter(session, novel, ch)
                    n2 = await summarizer.backfill_milestones_for_chapter(session, novel, ch)
                self.assertEqual((n1, n2), (1, 1))
                rows = await self._milestones(session)
                self.assertEqual(len(rows), 1)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_backfill_empty_chapter_skips(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env()
            try:
                ch.content = ""
                n = await summarizer.backfill_milestones_for_chapter(session, novel, ch)
                self.assertEqual(n, 0)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())


if __name__ == "__main__":
    unittest.main()
