"""小说设定 → RPG 向导素材。真查内存库，确认取什么、不取什么。

「平行线、全部初始化」是硬要求：current_state、剧情设计、结局不能漏进素材。
"""
import asyncio
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user  # noqa: F401
from app.models.character import Character
from app.models.novel import Novel
from app.models.world_rule import WorldRule
from app.services import novel_to_rpg


def _run(scenario):
    async def wrapper():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)()
        try:
            return await scenario(session)
        finally:
            await session.close()
            await engine.dispose()
    return asyncio.run(wrapper())


class BuildNovelSourceTests(unittest.TestCase):
    def test_only_initial_settings_are_included(self):
        async def scenario(db):
            novel = Novel(
                title="雨夜", genre="悬疑", premise="港口失踪案", core_setting="雨城，终年下雨",
                plot_design="第十章主角死亡", ending="主角成为凶手",
            )
            db.add(novel)
            await db.flush()
            db.add_all([
                Character(
                    novel_id=novel.id, name="老陈", role="配角", description="码头工头",
                    full_sheet={"性格": "沉默"}, current_state={"goal": "已经叛变"},
                ),
                Character(novel_id=novel.id, name="林夏", role="主角"),
                WorldRule(novel_id=novel.id, kind="rule", title="宵禁", content="夜里不得出门"),
                WorldRule(novel_id=novel.id, kind="rule", title="停用规则", content="不该出现", enabled=False),
            ])
            await db.flush()
            return await novel_to_rpg.build_novel_source(db, novel)

        text, notes = _run(scenario)
        self.assertIn("雨城，终年下雨", text)
        self.assertIn("沉默", text)
        self.assertIn("宵禁", text)
        self.assertNotIn("已经叛变", text)
        self.assertNotIn("第十章主角死亡", text)
        self.assertNotIn("主角成为凶手", text)
        self.assertNotIn("不该出现", text)
        self.assertEqual(notes, [])
        self.assertLess(text.index("林夏"), text.index("老陈"))

    def test_empty_novel_yields_only_title(self):
        async def scenario(db):
            novel = Novel(title="空书")
            db.add(novel)
            await db.flush()
            return await novel_to_rpg.build_novel_source(db, novel)

        text, _ = _run(scenario)
        self.assertEqual(text, "## 基本信息\n书名：空书")

    def test_too_many_characters_are_capped_and_reported(self):
        async def scenario(db):
            novel = Novel(title="群像")
            db.add(novel)
            await db.flush()
            db.add_all(
                Character(novel_id=novel.id, name=f"角色{i}", role="配角")
                for i in range(novel_to_rpg.MAX_CHARACTERS + 3)
            )
            await db.flush()
            return await novel_to_rpg.build_novel_source(db, novel)

        text, notes = _run(scenario)
        self.assertEqual(text.count("- 角色"), novel_to_rpg.MAX_CHARACTERS)
        self.assertEqual(len(notes), 1)
        self.assertIn("只取了前", notes[0])


if __name__ == "__main__":
    unittest.main()
