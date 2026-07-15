import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry  # noqa: F401
from app.agents.character_agent import filter_discovered
from app.models.chapter import Chapter
from app.models.memory import Memory
from app.models.novel import Novel
from app.services import summarizer
from app.services.llm_json import JsonCallError

_KNOWN_EMPTY = dict(
    known_char_names=[], known_entity_names=[], known_locations=[],
    known_tech_names=[], known_faction_names=[],
)


class FilterDiscoveredTests(unittest.TestCase):
    def test_known_names_removed(self):
        chars, ents, locs, techs, facs = filter_discovered(
            {"characters": [{"name": "张三"}, {"name": "李四"}]},
            ["张三"], [], [], [], [],
        )
        self.assertEqual([c["name"] for c in chars], ["李四"])

    def test_cross_category_dedup_priority(self):
        chars, ents, locs, techs, facs = filter_discovered(
            {
                "characters": [{"name": "青莲"}],
                "entities": [{"name": "青莲", "type": "item"}],
            },
            [], [], [], [], [],
        )
        self.assertEqual(len(chars), 1)
        self.assertEqual(ents, [])

    def test_entity_type_normalized(self):
        _, ents, _, _, _ = filter_discovered(
            {"entities": [{"name": "剑", "type": "weapon"}]},
            [], [], [], [], [],
        )
        self.assertEqual(ents[0]["type"], "item")

    def test_non_list_values_ignored(self):
        result = filter_discovered({"characters": "不是列表"}, [], [], [], [], [])
        self.assertEqual(result, ([], [], [], [], []))


class SummarizeAndDiscoverTests(unittest.TestCase):
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
        ch = Chapter(novel_id=novel.id, number=1, volume=1, content="主角张三拔出了青锋剑。")
        session.add(ch)
        await session.flush()
        return engine, session, novel, ch

    def _vector_patches(self):
        return (
            patch.object(summarizer.vector_store, "ensure_embedding_configured", AsyncMock()),
            patch.object(summarizer.vector_store, "astore_text", AsyncMock()),
        )

    def test_success_persists_summary_and_returns_discovery(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env()
            try:
                async def fake_call_json(messages, model, api_format, **kw):
                    return {
                        "day_offset": 0, "period": "", "importance": 4,
                        "summary": "张三得到青锋剑。",
                        "characters": [{"name": "李四", "role": "配角", "description": "路人"}],
                        "entities": [], "locations": [], "techniques": [], "factions": [],
                    }, 100, 50

                v1, v2 = self._vector_patches()
                with v1, v2, \
                     patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    summary, discovered, in_tok, out_tok = await summarizer.summarize_and_discover(
                        session, ch, novel, **_KNOWN_EMPTY,
                    )
                self.assertIn("张三得到青锋剑", summary)
                self.assertIn("张三得到青锋剑", ch.summary)
                self.assertEqual(discovered["characters"][0]["name"], "李四")
                self.assertEqual((in_tok, out_tok), (100, 50))
                mem = (await session.execute(
                    select(Memory).where(Memory.memory_type == "chapter_summary")
                )).scalars().all()
                self.assertEqual(len(mem), 1)
                self.assertEqual(mem[0].importance, 4)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_call_failure_falls_back_to_pure_summary(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env()
            try:
                async def failing_call_json(*a, **kw):
                    raise JsonCallError("坏输出", input_tokens=10, output_tokens=5)

                async def fake_dispatch(messages, model=None, api_format=None, **kw):
                    return '{"day_offset": 0, "period": "", "summary": "纯摘要路径。", "importance": 3}', 20, 8

                v1, v2 = self._vector_patches()
                with v1, v2, \
                     patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer.llm_client, "dispatch_chat_complete_with_usage", fake_dispatch), \
                     patch.object(summarizer, "call_json", failing_call_json):
                    summary, discovered, in_tok, out_tok = await summarizer.summarize_and_discover(
                        session, ch, novel, **_KNOWN_EMPTY,
                    )
                self.assertIsNone(discovered)
                self.assertIn("纯摘要路径", summary)
                self.assertEqual((in_tok, out_tok), (30, 13))  # 失败调用 + 降级调用累加
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_truncated_summary_falls_back(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env()
            try:
                async def truncated_call_json(*a, **kw):
                    return {"summary": "这段摘要没有结尾标点被截断了", "characters": [{"name": "李四"}]}, 10, 5

                async def fake_dispatch(messages, model=None, api_format=None, **kw):
                    return '{"day_offset": 0, "period": "", "summary": "完整的摘要。", "importance": 3}', 20, 8

                v1, v2 = self._vector_patches()
                with v1, v2, \
                     patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer.llm_client, "dispatch_chat_complete_with_usage", fake_dispatch), \
                     patch.object(summarizer, "call_json", truncated_call_json):
                    summary, discovered, _, _ = await summarizer.summarize_and_discover(
                        session, ch, novel, **_KNOWN_EMPTY,
                    )
                self.assertIsNone(discovered)
                self.assertIn("完整的摘要", summary)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_empty_chapter_skips(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env()
            try:
                ch.content = ""
                summary, discovered, in_tok, out_tok = await summarizer.summarize_and_discover(
                    session, ch, novel, **_KNOWN_EMPTY,
                )
                self.assertEqual((summary, discovered, in_tok, out_tok), ("", None, 0, 0))
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())


if __name__ == "__main__":
    unittest.main()
