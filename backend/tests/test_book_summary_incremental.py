import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry  # noqa: F401
from app.models.memory import Memory
from app.models.novel import Novel
from app.services import summarizer


class BookSummaryIncrementalTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    async def _make_session(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return engine, async_sessionmaker(engine, expire_on_commit=False)()

    async def _seed(self, session, *, book_summary="", chapters=()):
        novel = Novel(title="测试", book_summary=book_summary)
        session.add(novel)
        await session.flush()
        for num, content in chapters:
            session.add(Memory(
                novel_id=novel.id,
                memory_type="chapter_summary",
                content=content,
                chapter_number=num,
                volume=1,
            ))
        await session.flush()
        return novel

    def _patches(self, captured: list, reply="新的概要"):
        async def fake_dispatch(messages, model=None, api_format=None, **kwargs):
            captured.append(messages[0]["content"])
            return reply

        return (
            patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")),
            patch.object(summarizer.llm_client, "dispatch_chat_complete", fake_dispatch),
        )

    def test_incremental_path_uses_old_summary_and_window(self):
        async def scenario():
            engine, session = await self._make_session()
            try:
                novel = await self._seed(
                    session,
                    book_summary="旧概要：主角出山。",
                    chapters=[(i, f"第{i}章内容摘要") for i in range(1, 11)],
                )
                captured: list[str] = []
                p1, p2 = self._patches(captured)
                with p1, p2:
                    result = await summarizer.generate_book_summary(
                        session, novel, window=(6, 10),
                    )
                self.assertEqual(result, "新的概要")
                self.assertEqual(novel.book_summary, "新的概要")
                self.assertEqual(len(captured), 1)
                self.assertIn("旧概要：主角出山。", captured[0])
                self.assertIn("第6章内容摘要", captured[0])
                self.assertNotIn("第5章内容摘要", captured[0])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_no_old_summary_falls_back_to_full_rebuild(self):
        async def scenario():
            engine, session = await self._make_session()
            try:
                novel = await self._seed(
                    session,
                    book_summary="",
                    chapters=[(1, "第一章摘要"), (2, "第二章摘要")],
                )
                captured: list[str] = []
                p1, p2 = self._patches(captured)
                with p1, p2:
                    result = await summarizer.generate_book_summary(
                        session, novel, window=(1, 2),
                    )
                self.assertEqual(result, "新的概要")
                # 全量模板不含"现有全书概要"字样
                self.assertNotIn("现有全书概要", captured[0])
                self.assertIn("第一章摘要", captured[0])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_empty_window_falls_back_to_full_rebuild(self):
        async def scenario():
            engine, session = await self._make_session()
            try:
                novel = await self._seed(
                    session,
                    book_summary="旧概要",
                    chapters=[(1, "第一章摘要")],
                )
                captured: list[str] = []
                p1, p2 = self._patches(captured)
                with p1, p2:
                    await summarizer.generate_book_summary(
                        session, novel, window=(50, 54),
                    )
                self.assertEqual(len(captured), 1)
                self.assertNotIn("现有全书概要", captured[0])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_no_window_keeps_full_rebuild_behavior(self):
        async def scenario():
            engine, session = await self._make_session()
            try:
                novel = await self._seed(
                    session,
                    book_summary="旧概要",
                    chapters=[(1, "第一章摘要")],
                )
                captured: list[str] = []
                p1, p2 = self._patches(captured)
                with p1, p2:
                    result = await summarizer.generate_book_summary(session, novel)
                self.assertEqual(result, "新的概要")
                self.assertNotIn("现有全书概要", captured[0])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())


class BookSummaryMaxTokensTests(unittest.TestCase):
    def test_scales_every_50_chapters(self):
        f = summarizer._book_summary_max_tokens
        self.assertEqual(f(0), 2000)
        self.assertEqual(f(49), 2000)
        self.assertEqual(f(50), 2500)
        self.assertEqual(f(149), 3000)
        self.assertEqual(f(200), 4000)
        self.assertEqual(f(-5), 2000)


if __name__ == "__main__":
    unittest.main()
