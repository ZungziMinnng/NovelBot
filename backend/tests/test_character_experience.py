"""角色经历自动积累的测试。

覆盖：chapter_summary_day 天数解析、
角色状态更新端到端（经历落库带天数、同章重跑替换、无天数降级、"经历"键不进 current_state）、
写作上下文注入（最近10条截断、第X章·第X日格式）。
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
from app.services.context_builder import _HISTORY_INJECT_LIMIT, format_context_for_writer
from app.services.summarizer import chapter_summary_day


class ChapterSummaryDayTests(unittest.TestCase):
    def test_parses_day_from_tag(self):
        self.assertEqual(chapter_summary_day("【第5日·夜晚】张三突破。"), 5)
        self.assertEqual(chapter_summary_day("【第40日】旧爱被击毙。"), 40)

    def test_no_tag_returns_none(self):
        self.assertIsNone(chapter_summary_day("张三突破筑基。"))
        self.assertIsNone(chapter_summary_day(""))
        self.assertIsNone(chapter_summary_day(None))
        self.assertIsNone(chapter_summary_day("【夜晚】无天数标记。"))


def _fake_call_json(payload):
    async def fake(messages, model, api_format, **kw):
        return payload, 10, 5
    return fake


class ExperiencePersistTests(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    def test_experience_saved_with_day_and_not_in_state(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                novel = Novel(title="测试")
                session.add(novel)
                await session.flush()
                ch = Chapter(novel_id=novel.id, number=3, volume=1,
                             content="张三突破筑基。", summary="【第5日·夜晚】张三突破筑基。")
                session.add(ch)
                char = Character(novel_id=novel.id, name="张三", current_state={})
                session.add(char)
                await session.flush()

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json",
                                  _fake_call_json({"张三": {"realm": "筑基", "经历": "突破筑基"}})):
                    ok, _, _, _, _, _ = await summarizer.update_character_states(session, ch, novel)
                self.assertTrue(ok)
                self.assertEqual(char.full_sheet["character_history"],
                                 [{"chapter": 3, "content": "突破筑基", "day": 5}])
                self.assertEqual(char.current_state["realm"], "筑基")
                self.assertNotIn("经历", char.current_state)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)

    def test_same_chapter_rerun_replaces_entry(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                novel = Novel(title="测试")
                session.add(novel)
                await session.flush()
                ch = Chapter(novel_id=novel.id, number=2, volume=1,
                             content="张三下山。", summary="【第9日】张三下山。")
                session.add(ch)
                char = Character(novel_id=novel.id, name="张三", current_state={},
                                 full_sheet={"character_history": [
                                     {"chapter": 1, "content": "入宗拜师", "day": 1},
                                     {"chapter": 2, "content": "旧版经历", "day": 8},
                                 ]})
                session.add(char)
                await session.flush()

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json",
                                  _fake_call_json({"张三": {"经历": "奉命下山历练"}})):
                    ok, _, _, _, _, _ = await summarizer.update_character_states(session, ch, novel)
                self.assertTrue(ok)
                history = char.full_sheet["character_history"]
                self.assertEqual(len(history), 2)
                self.assertEqual(history[0], {"chapter": 1, "content": "入宗拜师", "day": 1})
                self.assertEqual(history[1], {"chapter": 2, "content": "奉命下山历练", "day": 9})
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)

    def test_missing_summary_day_omitted(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                novel = Novel(title="测试")
                session.add(novel)
                await session.flush()
                ch = Chapter(novel_id=novel.id, number=1, volume=1, content="张三入宗。")
                session.add(ch)
                char = Character(novel_id=novel.id, name="张三", current_state={})
                session.add(char)
                await session.flush()

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json",
                                  _fake_call_json({"张三": {"经历": "入宗拜师"}})):
                    ok, _, _, _, _, _ = await summarizer.update_character_states(session, ch, novel)
                self.assertTrue(ok)
                self.assertEqual(char.full_sheet["character_history"],
                                 [{"chapter": 1, "content": "入宗拜师"}])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)


class ExperienceInjectionTests(unittest.TestCase):
    def _ctx(self, history):
        return {
            "characters": [{
                "name": "裴云霁", "role": "主角", "description": "宗门长老",
                "full_sheet": {"character_history": history}, "state": {},
            }],
        }

    def test_recent_entries_rendered_with_day(self):
        history = [
            {"chapter": 3, "day": 5, "content": "旧爱林某入宗"},
            {"chapter": 15, "day": 40, "content": "查明林某为魔教细作并击毙"},
        ]
        _, chars_block, _ = format_context_for_writer(self._ctx(history))
        self.assertIn("经历（近期", chars_block)
        self.assertIn("第3章·第5日：旧爱林某入宗", chars_block)
        self.assertIn("第15章·第40日：查明林某为魔教细作并击毙", chars_block)

    def test_entry_without_day_rendered_with_chapter_only(self):
        _, chars_block, _ = format_context_for_writer(
            self._ctx([{"chapter": 7, "content": "闭关疗伤"}]))
        self.assertIn("第7章：闭关疗伤", chars_block)
        self.assertNotIn("第7章·", chars_block)

    def test_truncated_to_recent_limit(self):
        history = [{"chapter": i, "day": i, "content": f"经历{i}"} for i in range(1, 16)]
        _, chars_block, _ = format_context_for_writer(self._ctx(history))
        self.assertNotIn("经历5", chars_block)
        self.assertIn("经历6", chars_block)
        self.assertIn("经历15", chars_block)
        self.assertEqual(_HISTORY_INJECT_LIMIT, 10)

    def test_no_history_no_block(self):
        _, chars_block, _ = format_context_for_writer(self._ctx([]))
        self.assertNotIn("经历（近期", chars_block)


if __name__ == "__main__":
    unittest.main()
