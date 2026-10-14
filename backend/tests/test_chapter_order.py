"""调整章节顺序 / 插入新章：只动已确认之后的未确认章，按章号存的附属数据跟着走。"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (  # noqa: F401
    novel as _novel, chapter as _chapter, memory as _memory, story_thread,
    worldview_change, user as _user,
)
from app.models.author_note import AuthorNote
from app.models.chapter import Chapter
from app.models.memory import Memory, Outline
from app.models.novel import Novel
from app.models.story_thread import StoryThread
from app.models.user import User
from app.services import chapter_order


class ChapterOrderTests(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    async def _setup(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # 生产库的唯一索引由迁移建，这里补上，确认换号不会撞
            await conn.exec_driver_sql(
                "CREATE UNIQUE INDEX uq_chapters_novel_number ON chapters(novel_id, number)"
            )
        session = async_sessionmaker(engine, expire_on_commit=False)()
        user = User(username="a", password_hash="x")
        session.add(user)
        await session.flush()
        novel = Novel(title="书", user_id=user.id)
        session.add(novel)
        await session.flush()
        chapters = []
        for n in range(1, 5):
            ch = Chapter(
                novel_id=novel.id, number=n, title=f"第{n}章", content=f"正文{n}",
                status="confirmed" if n == 1 else "draft",
            )
            session.add(ch)
            chapters.append(ch)
        await session.flush()
        return engine, session, novel, chapters

    def test_reorder_moves_attached_records(self):
        async def scenario():
            engine, s, novel, (c1, c2, c3, c4) = await self._setup()
            try:
                c3.title = "作者起的名"
                s.add_all([
                    Outline(novel_id=novel.id, level="chapter", chapter_number=2, content="计划2"),
                    Outline(novel_id=novel.id, level="chapter", chapter_number=4, content="计划4"),
                    Memory(novel_id=novel.id, chapter_id=c2.id, chapter_number=2,
                           memory_type="chapter_summary", content="摘要2"),
                    Memory(novel_id=novel.id, chapter_id=None, chapter_number=2,
                           memory_type="state_snapshot", content="{}"),
                    StoryThread(novel_id=novel.id, kind="foreshadowing", title="伏笔", content="", source_chapter=4),
                    AuthorNote(novel_id=novel.id, chapter_number=3, content="这章要埋线"),
                ])
                await s.flush()

                moved = await chapter_order.reorder(s, novel.id, [c4.id, c2.id, c3.id])
                await s.commit()

                self.assertEqual((c1.number, c4.number, c2.number, c3.number), (1, 2, 3, 4))
                self.assertEqual(moved, {c4.id: 2, c2.id: 3, c3.id: 4})
                self.assertEqual(c4.title, "第2章")
                self.assertEqual(c2.title, "第3章")
                self.assertEqual(c3.title, "作者起的名")
                plans = {o.content: o.chapter_number for o in (await s.execute(select(Outline))).scalars()}
                self.assertEqual(plans, {"计划2": 3, "计划4": 2})
                mems = {m.memory_type: m.chapter_number for m in (await s.execute(select(Memory))).scalars()}
                self.assertEqual(mems, {"chapter_summary": 3, "state_snapshot": 3})
                thread = (await s.execute(select(StoryThread))).scalar_one()
                self.assertEqual(thread.source_chapter, 2)
                note = (await s.execute(select(AuthorNote))).scalar_one()
                self.assertEqual(note.chapter_number, 4)
            finally:
                await s.close()
                await engine.dispose()
        self._run(scenario)

    def test_reorder_rejects_confirmed_or_partial_list(self):
        async def scenario():
            engine, s, novel, (c1, c2, c3, c4) = await self._setup()
            try:
                with self.assertRaises(chapter_order.OrderError):
                    await chapter_order.reorder(s, novel.id, [c2.id, c1.id, c3.id, c4.id])
                with self.assertRaises(chapter_order.OrderError):
                    await chapter_order.reorder(s, novel.id, [c3.id, c2.id])
                self.assertEqual([c.number for c in (c1, c2, c3, c4)], [1, 2, 3, 4])
            finally:
                await s.close()
                await engine.dispose()
        self._run(scenario)

    def test_insert_shifts_tail_and_unwritten_outlines(self):
        async def scenario():
            engine, s, novel, (c1, c2, c3, c4) = await self._setup()
            try:
                s.add_all([
                    Outline(novel_id=novel.id, level="chapter", chapter_number=3, content="计划3"),
                    Outline(novel_id=novel.id, level="chapter", chapter_number=6, content="计划6"),
                    Outline(novel_id=novel.id, level="volume", chapter_number=0, content="卷"),
                    AuthorNote(novel_id=novel.id, chapter_number=8, content="远期提醒"),
                    AuthorNote(novel_id=novel.id, chapter_number=2, content="前面的"),
                ])
                await s.flush()
                new, moved = await chapter_order.insert_before(s, novel.id, c3.id)
                await s.commit()

                self.assertEqual(new.number, 3)
                self.assertEqual(new.title, "第3章")
                self.assertEqual((c2.number, c3.number, c4.number), (2, 4, 5))
                self.assertEqual(moved, {c3.id: 4, c4.id: 5})
                plans = {o.content: o.chapter_number for o in (await s.execute(select(Outline))).scalars()}
                self.assertEqual(plans, {"计划3": 4, "计划6": 7, "卷": 0})
                notes = {n.content: n.chapter_number for n in (await s.execute(select(AuthorNote))).scalars()}
                self.assertEqual(notes, {"远期提醒": 9, "前面的": 2})

                with self.assertRaises(chapter_order.OrderError):
                    await chapter_order.insert_before(s, novel.id, c1.id)
            finally:
                await s.close()
                await engine.dispose()
        self._run(scenario)

    def test_sync_vectors_updates_summary_metadata(self):
        async def scenario():
            with patch.object(chapter_order.vector_store, "aupdate_metadata", new=AsyncMock()) as upd:
                await chapter_order.sync_vectors(7, {11: 3})
            upd.assert_awaited_once_with(7, "chapter_11_summary", {"chapter_number": 3})
        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
