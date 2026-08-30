"""GET /novels/{id}/overview 聚合接口的测试。"""
import asyncio
import unittest

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user  # noqa: F401
from app.api.routes.novels import novel_overview
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.novel import Novel
from app.models.user import User
from app.models.volume import Volume


class NovelOverviewTests(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    def test_counts_and_characters(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                user = User(username="u1", password_hash="x")
                session.add(user)
                await session.flush()
                novel = Novel(title="测试", user_id=user.id)
                session.add(novel)
                await session.flush()
                session.add_all([
                    Volume(novel_id=novel.id, number=1, title="第一卷"),
                    Volume(novel_id=novel.id, number=2, title="第二卷"),
                    Chapter(novel_id=novel.id, number=1, volume=1, content="a" * 100, word_count=100),
                    Chapter(novel_id=novel.id, number=2, volume=1, content="b" * 200, word_count=200),
                    Chapter(novel_id=novel.id, number=3, volume=2, content="c" * 300, word_count=300),
                    Character(novel_id=novel.id, name="沈放", role="配角"),
                    Character(novel_id=novel.id, name="裴云霁", role="主角"),
                ])
                await session.flush()

                data = await novel_overview(novel.id, user, db=session)
                self.assertEqual(data["volume_count"], 2)
                self.assertEqual(data["chapter_count"], 3)
                self.assertEqual(data["total_words"], 600)
                # 主角排前
                self.assertEqual(data["characters"], [
                    {"name": "裴云霁", "role": "主角"},
                    {"name": "沈放", "role": "配角"},
                ])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)

    def test_volume_fallback_from_chapters(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                user = User(username="u1", password_hash="x")
                session.add(user)
                await session.flush()
                novel = Novel(title="老书无卷表", user_id=user.id)
                session.add(novel)
                await session.flush()
                session.add_all([
                    Chapter(novel_id=novel.id, number=1, volume=1, content="a", word_count=1),
                    Chapter(novel_id=novel.id, number=2, volume=3, content="b", word_count=1),
                ])
                await session.flush()

                data = await novel_overview(novel.id, user, db=session)
                self.assertEqual(data["volume_count"], 2)
                self.assertEqual(data["chapter_count"], 2)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)

    def test_missing_novel_404(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                with self.assertRaises(HTTPException):
                    await novel_overview(999, User(id=1, username="u1", password_hash="x"), db=session)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
