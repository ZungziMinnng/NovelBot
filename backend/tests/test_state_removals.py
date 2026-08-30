"""状态删除通道（「移除」保留键）的测试。

覆盖：_apply_removals 纯函数的各字段类型分支、
角色状态更新端到端（同章又加又删按删处理、"移除"键不落库）。
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
from app.services.summarizer import _apply_removals


class ApplyRemovalsTests(unittest.TestCase):
    def test_list_field_exact_and_containment_match(self):
        merged = {"artifact": ["回魂丹", "玄天剑（微损）", "储物袋"]}
        _apply_removals(merged, {"artifact": ["回魂丹", "玄天剑"]})
        self.assertEqual(merged["artifact"], ["储物袋"])

    def test_dict_field_pops_matching_keys(self):
        merged = {"base_relationships": {"甲": "师尊", "乙": "结拜兄弟"}}
        _apply_removals(merged, {"base_relationships": ["甲"]})
        self.assertEqual(merged["base_relationships"], {"乙": "结拜兄弟"})

    def test_all_removes_whole_field(self):
        merged = {"injury": "重伤", "location": "山门"}
        _apply_removals(merged, {"injury": "全部"})
        self.assertEqual(merged, {"location": "山门"})

    def test_scalar_field_removed_on_match_kept_otherwise(self):
        merged = {"curse": "血咒", "goal": "夺回宗门"}
        _apply_removals(merged, {"curse": ["血咒"], "goal": ["无关目标"]})
        self.assertNotIn("curse", merged)
        self.assertEqual(merged["goal"], "夺回宗门")

    def test_missing_field_and_bad_input_silently_skipped(self):
        merged = {"location": "山门"}
        _apply_removals(merged, {"不存在的字段": "全部"})
        _apply_removals(merged, "不是字典")
        _apply_removals(merged, None)
        self.assertEqual(merged, {"location": "山门"})


class CharacterRemovalIntegrationTests(unittest.TestCase):
    def test_remove_wins_over_same_chapter_add_and_key_not_persisted(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                novel = Novel(title="测试")
                session.add(novel)
                await session.flush()
                ch = Chapter(novel_id=novel.id, number=1, volume=1, content="张三服下回魂丹，伤势痊愈。")
                session.add(ch)
                char = Character(novel_id=novel.id, name="张三", current_state={
                    "artifact": ["回魂丹"],
                    "injury": "重伤",
                })
                session.add(char)
                await session.flush()

                async def fake_call_json(messages, model, api_format, **kw):
                    return {"张三": {
                        "artifact": ["养气散", "回魂丹"],
                        "移除": {"artifact": ["回魂丹"], "injury": "全部"},
                    }}, 10, 5

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    ok, _, _, _, _, _ = await summarizer.update_character_states(session, ch, novel)
                self.assertTrue(ok)
                state = char.current_state
                # 同章又加又删：删除优先
                self.assertEqual(state["artifact"], ["养气散"])
                self.assertNotIn("injury", state)
                # "移除"键本身绝不落库
                self.assertNotIn("移除", state)
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
