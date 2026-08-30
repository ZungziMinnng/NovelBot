"""伏笔/秘密提取测试：候选不落库、规整/去重/上限、模型未输出时不影响已有条目。"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread as _story_thread, glossary_entry  # noqa: F401
from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.story_thread import StoryThread
from app.services import summarizer


def _payload(threads):
    return {
        "day_offset": 0, "period": "", "summary": "本章摘要。", "importance": 3,
        "characters": [], "entities": [], "locations": [], "techniques": [], "factions": [],
        "threads": threads,
    }


class ThreadExtractionTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    async def _make_session(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return engine, async_sessionmaker(engine, expire_on_commit=False)()

    async def _seed(self, session, *, existing_threads=()):
        novel = Novel(title="测试")
        session.add(novel)
        await session.flush()
        chapter = Chapter(novel_id=novel.id, number=3, volume=1, content="第三章正文。")
        session.add(chapter)
        for t in existing_threads:
            session.add(StoryThread(novel_id=novel.id, **t))
        await session.flush()
        return novel, chapter

    def _patches(self, data, captured_prompt: list | None = None):
        async def fake_call_json(messages, model, api_format, **kwargs):
            if captured_prompt is not None:
                captured_prompt.append(messages[0]["content"])
            return data, 0, 0

        return (
            patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")),
            patch.object(summarizer, "call_json", fake_call_json),
            patch.object(summarizer.vector_store, "ensure_embedding_configured", AsyncMock()),
            patch.object(summarizer.vector_store, "astore_text", AsyncMock()),
        )

    async def _summarize(self, session, novel, chapter, data, captured_prompt=None):
        p1, p2, p3, p4 = self._patches(data, captured_prompt)
        with p1, p2, p3, p4:
            return await summarizer.summarize_and_discover(
                session, chapter, novel,
                known_char_names=[], known_entity_names=[], known_locations=[],
                known_tech_names=[], known_faction_names=[],
            )

    async def _threads(self, session, novel_id):
        return (await session.execute(
            select(StoryThread).where(StoryThread.novel_id == novel_id)
        )).scalars().all()

    def test_candidates_returned_not_persisted(self):
        async def scenario():
            engine, session = await self._make_session()
            try:
                novel, chapter = await self._seed(session)
                _, discovered, _, _ = await self._summarize(session, novel, chapter, _payload([
                    {"kind": "secret", "title": "月华顿悟谎言", "content": "主角实为获得系统突破，对外谎称观月华顿悟。", "importance": 9, "known_by": ["主角"]},
                    {"kind": "伏笔", "title": "逐出宗门", "content": "师尊将欺凌主角的弟子逐出宗门。", "importance": 4},
                ]))
                # 候选返回给前端，但不落库
                self.assertEqual(await self._threads(session, novel.id), [])
                cands = discovered["threads"]
                self.assertEqual(len(cands), 2)
                by_title = {c["title"]: c for c in cands}
                secret = by_title["月华顿悟谎言"]
                self.assertEqual(secret["kind"], "secret")
                self.assertEqual(secret["importance"], 5)  # clamp 到 1-5
                self.assertEqual(secret["known_by"], ["主角"])
                self.assertEqual(secret["source_chapter"], 3)
                fs = by_title["逐出宗门"]
                self.assertEqual(fs["kind"], "foreshadowing")  # 中文 kind 归一化
                self.assertEqual(fs["known_by"], [])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_dedup_against_existing_and_cap(self):
        async def scenario():
            engine, session = await self._make_session()
            try:
                novel, chapter = await self._seed(session, existing_threads=[
                    {"kind": "secret", "title": "月华顿悟谎言", "content": "已有条目", "source": "manual", "source_chapter": 2},
                ])
                _, discovered, _, _ = await self._summarize(session, novel, chapter, _payload([
                    {"kind": "secret", "title": "月华顿悟谎言", "content": "重复提取的同一事实。"},
                    {"kind": "foreshadowing", "title": "事实A", "content": "事实A内容。"},
                    {"kind": "foreshadowing", "title": "事实B", "content": "事实B内容。"},
                    {"kind": "foreshadowing", "title": "事实C", "content": "超出上限的第三条。"},
                ]))
                # 重复标题被去重，每章候选最多 2 条
                titles = sorted(c["title"] for c in discovered["threads"])
                self.assertEqual(titles, ["事实A", "事实B"])
                # 库内只剩原有的 1 条，未新增
                self.assertEqual([t.title for t in await self._threads(session, novel.id)], ["月华顿悟谎言"])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_confirmed_threads_suppress_reextraction(self):
        async def scenario():
            engine, session = await self._make_session()
            try:
                # 用户已确认过的本章 auto 条目：重新确认时不应再作为候选弹出
                novel, chapter = await self._seed(session, existing_threads=[
                    {"kind": "secret", "title": "已确认提取", "content": "上次生成已确认的事实", "source": "auto", "source_chapter": 3},
                ])
                captured: list[str] = []
                _, discovered, _, _ = await self._summarize(session, novel, chapter, _payload([
                    {"kind": "secret", "title": "已确认提取", "content": "上次生成已确认的事实"},
                    {"kind": "secret", "title": "新提取", "content": "重新生成后提取的新事实。"},
                ]), captured_prompt=captured)
                self.assertEqual([c["title"] for c in discovered["threads"]], ["新提取"])
                # 已确认条目保留在库中，且进提示词的已记录列表抑制重复提取
                self.assertEqual([t.title for t in await self._threads(session, novel.id)], ["已确认提取"])
                self.assertIn("已确认提取", captured[0])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_missing_threads_key_keeps_existing(self):
        async def scenario():
            engine, session = await self._make_session()
            try:
                novel, chapter = await self._seed(session, existing_threads=[
                    {"kind": "secret", "title": "旧提取", "content": "上次提取的事实", "source": "auto", "source_chapter": 3},
                ])
                data = _payload([])
                del data["threads"]
                _, discovered, _, _ = await self._summarize(session, novel, chapter, data)
                self.assertEqual(discovered["threads"], [])
                # 模型未按新格式输出时不删不改
                threads = await self._threads(session, novel.id)
                self.assertEqual([t.title for t in threads], ["旧提取"])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_invalid_items_skipped(self):
        async def scenario():
            engine, session = await self._make_session()
            try:
                novel, chapter = await self._seed(session)
                _, discovered, _, _ = await self._summarize(session, novel, chapter, _payload([
                    {"kind": "无效类型", "title": "A", "content": "内容"},
                    {"kind": "secret", "title": "B", "content": ""},
                    "不是字典",
                ]))
                self.assertEqual(discovered["threads"], [])
                self.assertEqual(await self._threads(session, novel.id), [])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())


if __name__ == "__main__":
    unittest.main()
