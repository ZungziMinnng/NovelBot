"""删除小说的级联完整性。

foreign_keys=ON 之后，任何"有 novel_id 外键但 Novel 上没声明级联关系"的表都会让
删除整本书失败。这个模块盯两件事：
1. memories.chapter_id 指向 chapters，ORM 看不出先后依赖，必须先置空（曾导致 14 本书全删不掉）
2. 所有带 novel_id 的表都能被清干净，加新表时漏挂级联会在这里暴露
"""
import asyncio
import unittest

from sqlalchemy import delete as sql_delete, func, inspect, select, text, update as sql_update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (  # noqa: F401
    novel as _novel, chapter as _chapter, character as _character, memory as _memory,
    model_library, writer_preset, prompt_rule, world_entity, location, api_provider,
    novel_note, faction, technique, volume as _volume, worldview_change, world_rule,
    story_thread, glossary_entry, user as _user, llm_usage, text_replace_backup,
    tavern, sensitive_word,
)
from app.models.chapter import Chapter
from app.models.llm_usage import LlmUsage
from app.models.location import Location
from app.models.memory import Memory
from app.models.novel import Novel
from app.models.user import User


class NovelDeleteCascadeTests(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    async def _setup(self):
        """建库时开 foreign_keys，与生产 database.py 的 PRAGMA 保持一致。"""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        session = async_sessionmaker(engine, expire_on_commit=False)()
        await session.execute(text("PRAGMA foreign_keys=ON"))
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.flush()
        novel = Novel(title="书", user_id=user.id)
        session.add(novel)
        await session.flush()
        return engine, session, novel

    async def _delete_novel(self, db, novel):
        """复刻 routes/novels.py delete_novel 的清理顺序。"""
        novel_id = novel.id
        await db.execute(sql_delete(LlmUsage).where(LlmUsage.novel_id == novel_id))
        await db.execute(
            sql_update(Location).where(Location.novel_id == novel_id).values(parent_id=None)
        )
        await db.execute(
            sql_update(Memory).where(Memory.novel_id == novel_id).values(chapter_id=None)
        )
        await db.delete(novel)
        await db.commit()

    def test_memory_pointing_at_chapter_does_not_block_delete(self):
        """回归：memory.chapter_id 非空时曾报 FOREIGN KEY constraint failed。"""
        async def scenario():
            engine, session, novel = await self._setup()
            try:
                chapter = Chapter(novel_id=novel.id, number=1, title="第一章", content="正文")
                session.add(chapter)
                await session.flush()
                session.add(Memory(
                    novel_id=novel.id, chapter_id=chapter.id,
                    memory_type="summary", content="摘要",
                ))
                await session.commit()

                await self._delete_novel(session, novel)

                for model in (Novel, Chapter, Memory):
                    left = (await session.execute(select(func.count()).select_from(model))).scalar()
                    self.assertEqual(left, 0, f"{model.__tablename__} 有残留")
                self.assertEqual(
                    (await session.execute(text("PRAGMA foreign_key_check"))).fetchall(), []
                )
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_every_novel_scoped_table_is_covered(self):
        """新增带 novel_id 的表若忘了挂级联，在这里就会失败而不是等用户点删除。"""
        async def scenario():
            engine, session, novel = await self._setup()
            try:
                await session.commit()
                mapped = {
                    m.class_.__tablename__: m.class_
                    for m in Novel.__mapper__.registry.mappers
                    if "novel_id" in inspect(m.class_).columns
                }
                cascaded = {
                    rel.mapper.class_.__tablename__
                    for rel in Novel.__mapper__.relationships
                    if "delete" in (rel.cascade or "")
                }
                # 这两张表故意不走 ORM 级联，由 delete_novel 手动清理
                manual = {"llm_usage", "text_replace_backups"}
                missing = set(mapped) - cascaded - manual
                self.assertEqual(
                    missing, set(),
                    f"这些表有 novel_id 但既没级联也没手动清理，删除整本书会失败：{sorted(missing)}",
                )
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
