"""删章时回滚状态卡：删末尾章恢复到它生成之前，删中间章不动 current_state，经历条目都清掉。"""
import asyncio
import unittest

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
from app.models.character import Character
from app.models.novel import Novel
from app.models.user import User
from app.services import state_snapshot


class StateRewindOnDeleteTests(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    async def _setup(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        s = async_sessionmaker(engine, expire_on_commit=False)()
        user = User(username="a", password_hash="x")
        s.add(user)
        await s.flush()
        novel = Novel(title="书", user_id=user.id)
        s.add(novel)
        await s.flush()
        char = Character(novel_id=novel.id, name="林", current_state={"current_goal": "原目标"})
        s.add(char)
        await s.flush()
        chapters = []
        for n in (1, 2):
            # 模拟生成流程：先拍快照，再写正文、累积状态
            await state_snapshot.rollback_or_create(s, novel.id, n, 1)
            ch = Chapter(novel_id=novel.id, number=n, title=f"第{n}章", content=f"正文{n}")
            s.add(ch)
            chapters.append(ch)
            char.current_state = {"current_goal": f"第{n}章后的目标"}
            char.full_sheet = {"character_history": [
                *(char.full_sheet or {}).get("character_history", []),
                {"chapter": n, "content": f"第{n}章经历"},
            ]}
            await s.flush()
        return engine, s, novel, char, chapters

    def test_delete_latest_restores_state(self):
        async def scenario():
            engine, s, novel, char, (c1, c2) = await self._setup()
            try:
                rolled = await state_snapshot.rewind_deleted(s, novel.id, [c2])
                self.assertTrue(rolled)
                self.assertEqual(char.current_state, {"current_goal": "第1章后的目标"})
                self.assertEqual(
                    [e["chapter"] for e in char.full_sheet["character_history"]], [1],
                )
            finally:
                await s.close()
                await engine.dispose()
        self._run(scenario)

    def test_batch_delete_tail_restores_to_earliest(self):
        async def scenario():
            engine, s, novel, char, chapters = await self._setup()
            try:
                self.assertTrue(await state_snapshot.rewind_deleted(s, novel.id, chapters))
                self.assertEqual(char.current_state, {"current_goal": "原目标"})
                self.assertEqual(char.full_sheet["character_history"], [])
            finally:
                await s.close()
                await engine.dispose()
        self._run(scenario)

    def test_delete_middle_keeps_state(self):
        async def scenario():
            engine, s, novel, char, (c1, c2) = await self._setup()
            try:
                self.assertFalse(await state_snapshot.rewind_deleted(s, novel.id, [c1]))
                self.assertEqual(char.current_state, {"current_goal": "第2章后的目标"})
                self.assertEqual(
                    [e["chapter"] for e in char.full_sheet["character_history"]], [2],
                )
            finally:
                await s.close()
                await engine.dispose()
        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
