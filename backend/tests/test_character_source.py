"""从正文发现的角色：角色卡取来源章正文段落、状态只给新角色补算。"""
import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry  # noqa: F401
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.novel import Novel
from app.agents.character_agent import mention_paragraphs
from app.prompts.loader import render
from app.services import summarizer


class MentionParagraphsTests(unittest.TestCase):
    def test_picks_named_paragraph_and_next(self):
        content = "清晨的风很冷。\n秦雅穿着深紫色睡裙倚在门口。\n“乖儿子，听妈妈的话。”\n窗外下起了雨。"
        out = mention_paragraphs(content, "秦雅")
        self.assertIn("深紫色睡裙", out)
        self.assertIn("乖儿子", out)  # 紧随其后的对话段不带名字也要带上
        self.assertNotIn("清晨的风", out)
        self.assertNotIn("窗外下起了雨", out)

    def test_no_mention_returns_empty(self):
        self.assertEqual(mention_paragraphs("一段风景描写。", "秦雅"), "")
        self.assertEqual(mention_paragraphs("", "秦雅"), "")

    def test_respects_limit(self):
        content = "\n".join(f"秦雅第{i}次出场，" + "描写" * 50 for i in range(20))
        self.assertLessEqual(len(mention_paragraphs(content, "秦雅", limit=500)), 500)


class CharacterTemplateTests(unittest.TestCase):
    _base = dict(
        genre="都市", writing_style="", core_setting="", name="秦雅", role="配角",
        age="33", description="秦朗的母亲", premise="", given={},
    )

    def test_source_text_rendered_with_priority_rule(self):
        out = render("character.jinja2", **self._base, source_text="秦雅穿着深紫色睡裙。")
        self.assertIn("秦雅穿着深紫色睡裙。", out)
        self.assertIn("必须以正文为准", out)

    def test_source_block_absent_without_text(self):
        out = render("character.jinja2", **self._base, source_text="")
        self.assertNotIn("正文中提到该角色的段落", out)


class OnlyIdsTests(unittest.TestCase):
    def test_only_listed_character_sent_and_updated(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                novel = Novel(title="测试")
                session.add(novel)
                await session.flush()
                ch = Chapter(novel_id=novel.id, number=1, volume=1, content="张三与李四在城门口争执。")
                old = Character(novel_id=novel.id, name="张三", current_state={"location": "城门"})
                new = Character(novel_id=novel.id, name="李四", current_state={"location": "故事起点"})
                session.add_all([ch, old, new])
                await session.flush()

                sent: list[str] = []

                async def fake_call_json(messages, model, api_format, **kw):
                    sent.append("\n".join(m["content"] for m in messages))
                    return {"张三": {"location": "酒楼"}, "李四": {"location": "城门"}}, 10, 5

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    ok, _, _, _, unmatched, ids = await summarizer.update_character_states(
                        session, ch, novel, only_ids={new.id},
                    )
                self.assertTrue(ok)
                self.assertEqual(ids, [new.id])
                self.assertEqual(new.current_state["location"], "城门")
                self.assertEqual(old.current_state["location"], "城门")  # 老角色不被同一章重复累积
                self.assertNotIn('"张三"', sent[0])  # 老角色状态不发给模型
                self.assertEqual(unmatched, ["张三"])
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
