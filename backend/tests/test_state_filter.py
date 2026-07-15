import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry  # noqa: F401
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.location import Location
from app.models.novel import Novel
from app.models.world_entity import WorldEntity
from app.services import summarizer
from app.services.summarizer import _filter_mentioned, _char_titles


class FilterMentionedTests(unittest.TestCase):
    def test_keeps_only_named(self):
        c1 = Character(name="张三")
        c2 = Character(name="李四")
        out = _filter_mentioned([c1, c2], "张三拔剑而起。")
        self.assertEqual([c.name for c in out], ["张三"])

    def test_title_alias_matches(self):
        c = Character(name="李四", current_state={"titles": ["国师"]})
        out = _filter_mentioned([c], "国师缓缓睁开双眼。", _char_titles)
        self.assertEqual(len(out), 1)

    def test_empty_or_invalid_names_skipped(self):
        c = Character(name="", current_state={"titles": [None, ""]})
        self.assertEqual(_filter_mentioned([c], "随便什么正文", _char_titles), [])


class _DbTestBase(unittest.TestCase):
    async def _make_env(self, content):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)()
        novel = Novel(title="测试")
        session.add(novel)
        await session.flush()
        ch = Chapter(novel_id=novel.id, number=1, volume=1, content=content)
        session.add(ch)
        await session.flush()
        return engine, session, novel, ch


class UpdateCharacterStatesFilterTests(_DbTestBase):
    def test_only_mentioned_states_sent(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env("张三挥剑斩向妖兽。")
            try:
                session.add_all([
                    Character(novel_id=novel.id, name="张三", current_state={"境界": "筑基"}),
                    Character(novel_id=novel.id, name="李四", current_state={"境界": "金丹"}),
                ])
                await session.flush()

                async def fake_call_json(messages, model, api_format, **kw):
                    fake_call_json.captured = "\n".join(m["content"] for m in messages)
                    return {}, 10, 5

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    ok, _, _, _, _, _ = await summarizer.update_character_states(session, ch, novel)
                self.assertTrue(ok)
                self.assertIn("张三", fake_call_json.captured)
                self.assertNotIn("金丹", fake_call_json.captured)  # 李四的状态没发
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(scenario())

    def test_no_mention_skips_llm_call(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env("一段与任何角色无关的风景描写。")
            try:
                session.add(Character(novel_id=novel.id, name="张三", current_state={}))
                await session.flush()

                async def fail_call_json(*a, **kw):
                    raise AssertionError("不应发起 LLM 调用")

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fail_call_json):
                    result = await summarizer.update_character_states(session, ch, novel)
                self.assertEqual(result, (True, "", 0, 0, [], []))
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(scenario())

    def test_instruction_mention_counts(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env("正文里没有名字。")
            try:
                session.add(Character(novel_id=novel.id, name="张三", current_state={}))
                await session.flush()

                async def fake_call_json(messages, model, api_format, **kw):
                    return {}, 10, 5

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    ok, _, _, _, _, _ = await summarizer.update_character_states(
                        session, ch, novel, instruction="本章张三登场",
                    )
                self.assertTrue(ok)
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(scenario())


class UpdateEntityLocationStatesFilterTests(_DbTestBase):
    def test_only_mentioned_sent_and_skip_when_none(self):
        async def scenario():
            engine, session, novel, ch = await self._make_env("张三握紧青锋剑冲入山谷。")
            try:
                session.add_all([
                    WorldEntity(novel_id=novel.id, name="青锋剑", type="item", current_state={"owner": "张三"}),
                    WorldEntity(novel_id=novel.id, name="玄天鼎", type="item", current_state={"owner": "李四"}),
                    Location(novel_id=novel.id, name="青云山", type="山脉", current_state={}),
                ])
                await session.flush()

                async def fake_call_json(messages, model, api_format, **kw):
                    fake_call_json.captured = "\n".join(m["content"] for m in messages)
                    return {"entities": {}, "locations": {}}, 10, 5

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    r = await summarizer.update_entity_location_states(session, ch, novel)
                self.assertTrue(r["entity"]["ok"])
                self.assertIn("青锋剑", fake_call_json.captured)
                self.assertNotIn("玄天鼎", fake_call_json.captured)
                self.assertNotIn("青云山", fake_call_json.captured)  # 地点未点名也不发

                # 全部未点名 → 直接跳过调用
                ch2 = Chapter(novel_id=novel.id, number=2, volume=1, content="无关内容。")
                session.add(ch2)
                await session.flush()

                async def fail_call_json(*a, **kw):
                    raise AssertionError("不应发起 LLM 调用")

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fail_call_json):
                    r2 = await summarizer.update_entity_location_states(session, ch2, novel)
                self.assertEqual((r2["input_tokens"], r2["output_tokens"]), (0, 0))
                self.assertTrue(r2["entity"]["ok"])
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
