"""章节历史版本与日更统计。"""
import asyncio
import unittest
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import novel as _novel, chapter as _chapter, user as _user  # noqa: F401
from app.models.chapter import Chapter
from app.models.chapter_version import ChapterVersion
from app.models.novel import Novel
from app.models.user import User
from app.models.word_day import WordDay
from app.services import chapter_versions, word_stats


class _Base(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    async def _setup(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)()
        user = User(username="a", password_hash="x")
        session.add(user)
        await session.flush()
        novel = Novel(title="书", user_id=user.id)
        session.add(novel)
        await session.flush()
        chapter = Chapter(novel_id=novel.id, number=1, content="第一版", word_count=3)
        session.add(chapter)
        await session.flush()
        return engine, session, novel, chapter

    async def _versions(self, s, chapter):
        return (await s.execute(
            select(ChapterVersion).where(ChapterVersion.chapter_id == chapter.id).order_by(ChapterVersion.id)
        )).scalars().all()


class ChapterVersionTests(_Base):
    def test_snapshot_skips_empty_and_duplicate(self):
        async def scenario():
            engine, s, novel, ch = await self._setup()
            try:
                await chapter_versions.snapshot(s, ch, "regenerate")
                await chapter_versions.snapshot(s, ch, "rewrite")  # 内容没变，不重复存
                ch.content = ""
                await chapter_versions.snapshot(s, ch, "rewrite")  # 空正文不存
                versions = await self._versions(s, ch)
                self.assertEqual([(v.content, v.reason) for v in versions], [("第一版", "regenerate")])
            finally:
                await s.close()
                await engine.dispose()
        self._run(scenario)

    def test_edit_snapshots_are_throttled(self):
        async def scenario():
            engine, s, novel, ch = await self._setup()
            try:
                await chapter_versions.snapshot(s, ch, "edit")
                ch.content = "第二版"
                await chapter_versions.snapshot(s, ch, "edit")  # 十分钟内的手改不再存
                self.assertEqual(len(await self._versions(s, ch)), 1)
                await chapter_versions.snapshot(s, ch, "rewrite")  # 别的原因不受节流
                self.assertEqual(len(await self._versions(s, ch)), 2)

                for v in await self._versions(s, ch):
                    v.created_at = datetime.utcnow() - timedelta(hours=1)
                ch.content = "第三版"
                await chapter_versions.snapshot(s, ch, "edit")
                self.assertEqual(len(await self._versions(s, ch)), 3)
            finally:
                await s.close()
                await engine.dispose()
        self._run(scenario)

    def test_keeps_at_most_max_versions(self):
        async def scenario():
            engine, s, novel, ch = await self._setup()
            try:
                for i in range(chapter_versions.MAX_VERSIONS + 5):
                    ch.content = f"版本{i}"
                    await chapter_versions.snapshot(s, ch, "rewrite")
                versions = await self._versions(s, ch)
                self.assertEqual(len(versions), chapter_versions.MAX_VERSIONS)
                self.assertEqual(versions[-1].content, f"版本{chapter_versions.MAX_VERSIONS + 4}")
                self.assertEqual(versions[0].content, "版本5")

                await chapter_versions.delete_for_chapters(s, [ch.id])
                self.assertEqual(await self._versions(s, ch), [])
            finally:
                await s.close()
                await engine.dispose()
        self._run(scenario)


class WordStatsTests(_Base):
    def test_net_growth_per_day(self):
        async def scenario():
            engine, s, novel, ch = await self._setup()
            try:
                # 章节原有 3 字；今天改成 10 字，再删到 8 字
                ch.word_count = 10
                await word_stats.record(s, novel.id, 7)
                ch.word_count = 8
                await word_stats.record(s, novel.id, -2)
                row = (await s.execute(select(WordDay))).scalar_one()
                self.assertEqual((row.base, row.total), (3, 8))

                s.add(WordDay(novel_id=novel.id, day=(date.today() - timedelta(days=2)).isoformat(), base=0, total=100))
                await s.flush()
                stats = await word_stats.recent(s, novel.id, days=7)
                self.assertEqual(stats["today"], 5)
                self.assertEqual(stats["total"], 105)
                self.assertEqual(len(stats["days"]), 7)
                self.assertEqual(stats["days"][-3]["net"], 100)
                self.assertEqual(stats["days"][0]["net"], 0)
            finally:
                await s.close()
                await engine.dispose()
        self._run(scenario)

    def test_zero_delta_writes_nothing(self):
        async def scenario():
            engine, s, novel, ch = await self._setup()
            try:
                await word_stats.record(s, novel.id, 0)
                self.assertIsNone((await s.execute(select(WordDay))).scalar_one_or_none())
            finally:
                await s.close()
                await engine.dispose()
        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
