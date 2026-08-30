"""回填关系里程碑接口测试：范围过滤、跨用户 404、单章失败跳过。"""
import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user  # noqa: F401
from app.models.chapter import Chapter
from app.models.memory import Memory
from app.models.novel import Novel
from app.models.user import User
from app.api.routes.admin import BackfillMilestonesIn, backfill_milestones
from app.services import summarizer


class BackfillRouteTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    async def _make_env(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)()
        alice = User(username="alice", password_hash="x")
        bob = User(username="bob", password_hash="x")
        session.add_all([alice, bob])
        await session.flush()
        novel = Novel(title="A的书", user_id=alice.id)
        session.add(novel)
        await session.flush()
        for n in range(1, 4):
            session.add(Chapter(novel_id=novel.id, number=n, volume=1, content=f"第{n}章正文。"))
        await session.flush()
        await session.commit()
        return engine, session, alice, bob, novel

    def test_range_filter_and_result(self):
        async def scenario():
            engine, session, alice, bob, novel = await self._make_env()
            try:
                async def fake_call_json(messages, model, api_format, **kw):
                    return {"milestones": [
                        {"characters": ["甲", "乙"], "type": "初见", "description": "初次相遇", "importance": 3},
                    ]}, 10, 5

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    r = await backfill_milestones(
                        novel.id, BackfillMilestonesIn(start_chapter=1, end_chapter=2),
                        alice, session,
                    )
                self.assertEqual(r["processed"], 2)
                self.assertEqual(r["extracted"], 2)
                self.assertEqual(r["failed"], [])
                rows = (await session.execute(
                    select(Memory).where(Memory.memory_type == "relationship_milestone")
                )).scalars().all()
                self.assertEqual(sorted(m.chapter_number for m in rows), [1, 2])  # 第3章不在范围内
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_cross_user_404(self):
        async def scenario():
            engine, session, alice, bob, novel = await self._make_env()
            try:
                with self.assertRaises(HTTPException) as ctx:
                    await backfill_milestones(
                        novel.id, BackfillMilestonesIn(start_chapter=1, end_chapter=3),
                        bob, session,
                    )
                self.assertEqual(ctx.exception.status_code, 404)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_single_chapter_failure_skipped(self):
        async def scenario():
            engine, session, alice, bob, novel = await self._make_env()
            try:
                calls = {"n": 0}

                async def flaky_call_json(messages, model, api_format, **kw):
                    calls["n"] += 1
                    if calls["n"] == 2:
                        raise RuntimeError("模型超时")
                    return {"milestones": [
                        {"characters": ["甲", "乙"], "type": "初见", "description": "初次相遇", "importance": 3},
                    ]}, 10, 5

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", flaky_call_json):
                    r = await backfill_milestones(
                        novel.id, BackfillMilestonesIn(start_chapter=1, end_chapter=3),
                        alice, session,
                    )
                self.assertEqual(r["processed"], 2)
                self.assertEqual(r["failed"], [2])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())


if __name__ == "__main__":
    unittest.main()
