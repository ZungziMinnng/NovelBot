"""模组编辑器里的「帮我写」。

三件事要钉住：
1. 栏位是白名单。前端的联合类型和后端的 FIELD_SPECS 是手工对齐的，
   对不上时必须是一个 400，而不是 KeyError 变成 500。
2. 这一栏空不空决定「从零写」还是「在原文上改」，两条路都得走通。
3. creator_note 不给生成入口——那一栏有「永不进 prompt」的硬规矩。
"""
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_assist
from app.api.routes.rpg import assist_module_field
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgModule
from app.models.user import User
from app.schemas.rpg import RpgAssistIn


class FieldSpecTests(unittest.TestCase):
    def test_creator_note_has_no_entry(self):
        """它是「AI 看不到的介绍」，既不当输入也不给生成入口。"""
        self.assertNotIn("creator_note", rpg_assist.FIELD_SPECS)

    def test_every_spec_is_complete(self):
        for field, spec in rpg_assist.FIELD_SPECS.items():
            with self.subTest(field=field):
                label, guidance, max_chars = spec
                self.assertTrue(label.strip())
                self.assertTrue(guidance.strip())
                self.assertGreater(max_chars, 0)


class AssistFieldTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, field, content, context=None):
        seen = {}

        async def fake(messages, **_kwargs):
            seen["prompt"] = messages[0]["content"]
            return "  写好的内容  "

        with patch.object(rpg_assist.llm_client, "dispatch_chat_complete", fake):
            with patch.object(
                rpg_assist.llm_client, "get_agent_client", return_value=("m", "openai")
            ) as pick:
                text = await rpg_assist.assist_field(field, content, context or {}, "7")
        seen["model_args"] = pick.call_args.args
        seen["text"] = text
        return seen

    async def test_an_empty_field_is_generated_from_scratch(self):
        seen = await self._run("worldview", "")
        self.assertEqual(seen["text"], "写好的内容")
        self.assertIn("从零写出", seen["prompt"])
        self.assertIn("世界观", seen["prompt"])

    async def test_an_existing_field_is_rewritten_in_place(self):
        seen = await self._run("worldview", "原来写的东西")
        self.assertIn("原来写的东西", seen["prompt"])
        self.assertIn("保留原有的核心设定", seen["prompt"])
        self.assertNotIn("从零写出", seen["prompt"])

    async def test_context_is_passed_through_and_blank_entries_dropped(self):
        seen = await self._run(
            "opening_scene", "", {"世界观": "海边小镇", "题材": "   "}
        )
        self.assertIn("海边小镇", seen["prompt"])
        self.assertNotIn("题材", seen["prompt"])

    async def test_long_context_is_truncated(self):
        seen = await self._run("opening_scene", "", {"世界观": "海" * 5000})
        self.assertNotIn("海" * (rpg_assist.CONTEXT_CHARS + 1), seen["prompt"])

    async def test_it_uses_the_narration_model(self):
        # 这是写世界观和人设的创作活，不该走那个便宜的裁决模型
        seen = await self._run("worldview", "")
        self.assertEqual(seen["model_args"], ("writer", "7"))


class AssistRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = User(username="alice", password_hash="x")
        self.db.add(self.user)
        await self.db.commit()
        self.module = RpgModule(
            user_id=self.user.id, name="测试模组", stat_defs=[], relation_stat_defs=[],
        )
        self.db.add(self.module)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_an_unknown_field_is_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            await assist_module_field(
                self.module.id, RpgAssistIn(field="creator_note"), self.user, self.db
            )
        self.assertEqual(caught.exception.status_code, 400)

    async def test_a_misconfigured_model_becomes_a_400(self):
        """resolve_model_ref 配错时抛 ValueError，不能变成 500 白屏。"""
        async def boom(*_args, **_kwargs):
            raise ValueError("模型没配好")

        with patch.object(rpg_assist, "assist_field", boom):
            with self.assertRaises(HTTPException) as caught:
                await assist_module_field(
                    self.module.id, RpgAssistIn(field="worldview"), self.user, self.db
                )
        self.assertEqual(caught.exception.status_code, 400)

    async def test_it_returns_the_text_without_touching_the_module(self):
        """生成的东西不落库：作者点「用这个」之后才由表单自己保存。"""
        async def fake(*_args, **_kwargs):
            return "海边有个小镇"

        with patch.object(rpg_assist, "assist_field", fake):
            out = await assist_module_field(
                self.module.id, RpgAssistIn(field="worldview"), self.user, self.db
            )
        self.assertEqual(out.text, "海边有个小镇")
        async with self.sessions() as fresh:
            module = await fresh.get(RpgModule, self.module.id)
            self.assertEqual(module.worldview, "")


if __name__ == "__main__":
    unittest.main()
