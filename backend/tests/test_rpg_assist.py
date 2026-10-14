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
from app.api.routes.rpg import _REFINE_MAX_NPCS, assist_module_field, refine_module_npcs
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgModule, RpgNpc
from app.models.user import User
from app.schemas.rpg import RpgAssistIn, RpgNpcRefineIn


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


class RefineInstructionTests(unittest.IsolatedAsyncioTestCase):
    """额外要求追加在渲染好的 prompt 后面——模板作者可以覆写，写进模板会被旧模板吃掉。"""

    async def _prompt(self, instruction):
        seen = {}

        async def fake(messages, **_kwargs):
            seen["prompt"] = messages[0]["content"]
            return "改好的"

        with patch.object(rpg_assist.llm_client, "dispatch_chat_complete", fake), \
             patch.object(rpg_assist.llm_client, "get_agent_client", return_value=("m", "openai")):
            await rpg_assist.assist_field("npc_persona", "旧性格", {}, "7", instruction=instruction)
        return seen["prompt"]

    async def test_requirement_is_appended_last(self):
        prompt = await self._prompt("写得更冷一点")
        self.assertTrue(prompt.rstrip().endswith("写得更冷一点"))
        self.assertIn("额外要求", prompt)

    async def test_no_requirement_leaves_prompt_alone(self):
        self.assertNotIn("额外要求", await self._prompt(""))

    async def test_long_requirement_is_capped(self):
        prompt = await self._prompt("啰" * 800)
        self.assertNotIn("啰" * (rpg_assist.INSTRUCTION_CHARS + 1), prompt)


class RefineRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = User(username="alice", password_hash="x")
        self.other = User(username="carol", password_hash="x")
        self.db.add_all([self.user, self.other])
        await self.db.commit()
        self.module = RpgModule(user_id=self.user.id, name="测试模组", model_ref="7",
                                stat_defs=[], relation_stat_defs=[])
        self.other_module = RpgModule(user_id=self.other.id, name="别人的",
                                      stat_defs=[], relation_stat_defs=[])
        self.db.add_all([self.module, self.other_module])
        await self.db.commit()
        self.a = RpgNpc(module_id=self.module.id, name="阿岚", persona="旧性格",
                        appearance="旧外貌", description="旧身份")
        self.b = RpgNpc(module_id=self.module.id, name="石三", persona="闷",
                        appearance="高", description="铁匠")
        self.outsider = RpgNpc(module_id=self.other_module.id, name="外人")
        self.db.add_all([self.a, self.b, self.outsider])
        await self.db.commit()
        model = patch.object(rpg_assist.llm_client, "get_agent_client", return_value=("m", "openai"))
        model.start()
        self.addCleanup(model.stop)

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _refine(self, ids, fields, fake=None):
        async def default(field, content, context, model_ref, instruction=""):
            return content + "+改"

        with patch.object(rpg_assist, "assist_field", fake or default):
            return await refine_module_npcs(
                self.module.id, RpgNpcRefineIn(npc_ids=ids, fields=fields), self.user, self.db,
            )

    async def test_one_item_per_npc_and_field_in_request_order(self):
        out = await self._refine([self.b.id, self.a.id], ["appearance", "persona"])
        self.assertEqual(
            [(i.npc_id, i.field) for i in out.items],
            [(self.b.id, "appearance"), (self.b.id, "persona"),
             (self.a.id, "appearance"), (self.a.id, "persona")],
        )
        self.assertEqual((out.items[0].original, out.items[0].text), ("高", "高+改"))
        # 端点不落库：写回是作者勾完再走 PATCH 的事
        async with self.sessions() as fresh:
            npc = await fresh.get(RpgNpc, self.a.id)
            self.assertEqual((npc.persona, npc.appearance), ("旧性格", "旧外貌"))

    async def test_one_failure_does_not_kill_the_batch(self):
        async def flaky(field, content, context, model_ref, instruction=""):
            if content == "旧性格":
                raise RuntimeError("供应商抽风")
            return "改好了"

        out = await self._refine([self.a.id, self.b.id], ["persona"], flaky)
        self.assertIn("供应商抽风", out.items[0].error)
        self.assertEqual(out.items[0].text, "")
        self.assertEqual((out.items[1].text, out.items[1].error), ("改好了", ""))

    async def test_empty_reply_becomes_item_error(self):
        async def empty(*_args, **_kwargs):
            return ""

        out = await self._refine([self.a.id], ["persona"], empty)
        self.assertIn("没返回内容", out.items[0].error)

    async def test_unknown_field_is_400(self):
        with self.assertRaises(HTTPException) as caught:
            await self._refine([self.a.id], ["creator_note"])
        self.assertEqual(caught.exception.status_code, 400)

    async def test_npc_from_another_module_is_404(self):
        with self.assertRaises(HTTPException) as caught:
            await self._refine([self.a.id, self.outsider.id], ["persona"])
        self.assertEqual(caught.exception.status_code, 404)

    async def test_too_many_npcs_is_400(self):
        with self.assertRaises(HTTPException) as caught:
            await self._refine(list(range(9000, 9000 + _REFINE_MAX_NPCS + 1)), ["persona"])
        self.assertEqual(caught.exception.status_code, 400)

    async def test_misconfigured_model_is_one_400(self):
        """配错模型在开头那次探测就抛，不该变成 N 条 item 各报一遍。"""
        with patch.object(rpg_assist.llm_client, "get_agent_client",
                          side_effect=ValueError("模型没配好")):
            with self.assertRaises(HTTPException) as caught:
                await refine_module_npcs(
                    self.module.id, RpgNpcRefineIn(npc_ids=[self.a.id], fields=["persona"]),
                    self.user, self.db,
                )
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
