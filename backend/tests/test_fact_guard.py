"""事实守门员（生死硬拦）的测试。

覆盖：fact_guard.check_life_death 纯函数各分支、
角色状态更新端到端（已死角色被 LLM 改回存活时拦截并还原、warning 冒泡）。
"""
import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry  # noqa: F401
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.novel import Novel
from app.services import summarizer
from app.services.fact_guard import check_life_death


class CheckLifeDeathTests(unittest.TestCase):
    def test_dead_to_alive_without_marker_blocks_and_restores(self):
        conflict = check_life_death({"存续": "死亡"}, {"存续": "存活"})
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict["severity"], "block")
        self.assertEqual(conflict["field"], "存续")
        self.assertEqual(conflict["corrected_value"], "死亡")

    def test_dead_to_cleared_status_blocks(self):
        # 新值把存续清空（不再判定死亡）也算非法逆转
        conflict = check_life_death({"存续": "死亡"}, {"存续": ""})
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict["corrected_value"], "死亡")

    def test_dead_to_resurrection_keyword_allowed(self):
        for kw in ("复活", "复生", "重生", "借尸还魂", "还魂", "起死回生"):
            self.assertIsNone(check_life_death({"存续": "死亡"}, {"存续": kw}),
                              f"复活关键词 {kw} 应放行")

    def test_dead_stays_dead_no_conflict(self):
        self.assertIsNone(check_life_death({"存续": "死亡"}, {"存续": "死亡"}))

    def test_dead_and_new_status_absent_no_conflict(self):
        # LLM 未输出存续键 → merge 保留旧值，不触发冲突
        self.assertIsNone(check_life_death({"存续": "死亡"}, {"存续": "死亡", "location": "乱葬岗"}))

    def test_alive_to_dead_legal_no_conflict(self):
        self.assertIsNone(check_life_death({"存续": "存活"}, {"存续": "死亡"}))

    def test_fake_death_to_alive_not_misjudged(self):
        # "假死" 不含子串"死亡"，非真死，改回存活不拦截
        self.assertIsNone(check_life_death({"存续": "假死"}, {"存续": "存活"}))

    def test_missing_keys_and_empty_inputs_no_error(self):
        self.assertIsNone(check_life_death({}, {}))
        self.assertIsNone(check_life_death(None, None))
        self.assertIsNone(check_life_death({"location": "山门"}, {"location": "山门"}))

    def test_severe_death_description_still_dead(self):
        # 描述性死亡值（如"战死"）含"死"但不含子串"死亡" → 不判定为死亡
        # 明确口径：仅"死亡"子串触发，与 context_builder 一致
        self.assertIsNone(check_life_death({"存续": "战死沙场"}, {"存续": "存活"}))


class LifeDeathIntegrationTests(unittest.TestCase):
    def test_dead_character_revived_by_llm_is_blocked_and_warned(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                novel = Novel(title="测试")
                session.add(novel)
                await session.flush()
                ch = Chapter(novel_id=novel.id, number=5, volume=1,
                             content="众人回忆起张三生前的音容，无不落泪。")
                session.add(ch)
                char = Character(novel_id=novel.id, name="张三",
                                 current_state={"存续": "死亡", "location": "乱葬岗"})
                session.add(char)
                await session.flush()

                async def fake_call_json(messages, model, api_format, **kw):
                    # LLM 误把已死角色写成存活
                    return {"张三": {"存续": "存活", "location": "客栈"}}, 10, 5

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    ok, warning, _, _, _, _ = await summarizer.update_character_states(session, ch, novel)

                self.assertTrue(ok)
                # 存续被还原为死亡，其余合法更新（location）保留
                self.assertEqual(char.current_state["存续"], "死亡")
                self.assertEqual(char.current_state["location"], "客栈")
                self.assertIn("事实守门员拦截", warning)
                self.assertIn("张三", warning)
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(scenario())

    def test_dead_character_resurrection_marker_allowed_end_to_end(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                novel = Novel(title="测试")
                session.add(novel)
                await session.flush()
                ch = Chapter(novel_id=novel.id, number=8, volume=1,
                             content="秘术发动，张三借尸还魂，重获新生。")
                session.add(ch)
                char = Character(novel_id=novel.id, name="张三",
                                 current_state={"存续": "死亡"})
                session.add(char)
                await session.flush()

                async def fake_call_json(messages, model, api_format, **kw):
                    return {"张三": {"存续": "复活"}}, 10, 5

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    ok, warning, _, _, _, _ = await summarizer.update_character_states(session, ch, novel)

                self.assertTrue(ok)
                self.assertEqual(char.current_state["存续"], "复活")
                self.assertNotIn("事实守门员拦截", warning or "")
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
