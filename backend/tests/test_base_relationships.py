"""基础关系（base_relationships）三层关系模型的测试。

覆盖：初始状态含空字典、LLM 输出按键合并（新增/覆盖/保留）、
Writer 上下文按对象渲染三层且不混入当前状态、关系图接口输出 base 边。
"""
import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user  # noqa: F401
from app.agents.character_agent import init_character_state
from app.api.routes.characters import relationship_graph
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.novel import Novel
from app.models.user import User
from app.services import summarizer
from app.services.context_builder import format_context_for_writer


class InitStateTests(unittest.TestCase):
    def test_init_contains_empty_base_relationships(self):
        state = init_character_state(Character(name="张三"))
        self.assertEqual(state["base_relationships"], {})


class MergeBaseRelationshipsTests(unittest.TestCase):
    def test_merge_add_overwrite_keep(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                novel = Novel(title="测试")
                session.add(novel)
                await session.flush()
                ch = Chapter(novel_id=novel.id, number=1, volume=1, content="张三拜师。")
                session.add(ch)
                char = Character(novel_id=novel.id, name="张三", current_state={
                    "base_relationships": {"甲": "旧师尊", "乙": "结拜兄弟"},
                })
                session.add(char)
                await session.flush()

                async def fake_call_json(messages, model, api_format, **kw):
                    return {"张三": {
                        "base_relationships": {"甲": "新师尊", "丙": "义父", "丁": ""},
                    }}, 10, 5

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json):
                    ok, _, _, _, _, _ = await summarizer.update_character_states(session, ch, novel)
                self.assertTrue(ok)
                base = char.current_state["base_relationships"]
                self.assertEqual(base["甲"], "新师尊")      # 同键覆盖
                self.assertEqual(base["乙"], "结拜兄弟")    # 未提及保留（手动维护不被冲掉）
                self.assertEqual(base["丙"], "义父")        # 新键补入
                self.assertNotIn("丁", base)               # 空值不写入
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(scenario())


class ContextRenderTests(unittest.TestCase):
    def _ctx(self, state):
        return {
            "characters": [{
                "name": "裴云霁", "role": "主角", "description": "宗门长老",
                "full_sheet": {}, "state": state,
            }],
        }

    def test_three_layers_rendered_per_target(self):
        _, chars_block, _ = format_context_for_writer(self._ctx({
            "location": "山门",
            "base_relationships": {"沈放": "弟子和儿子"},
            "initial_relationships": {"沈放": "捡来的孩子", "顾长风": "同门师兄"},
            "relationship_changes": {"沈放": "因隐瞒身世关系紧张"},
        }))
        self.assertIn("沈放（基础：弟子和儿子；当前：因隐瞒身世关系紧张）", chars_block)
        # 有当前关系时不再重复初始关系；无当前时回退初始
        self.assertIn("顾长风（初始：同门师兄）", chars_block)
        # 视角说明
        self.assertIn("对方是裴云霁的什么人", chars_block)
        # 三个关系字典不混入「当前状态」JSON
        self.assertIn("当前状态", chars_block)
        self.assertNotIn("base_relationships", chars_block)
        self.assertNotIn("initial_relationships", chars_block)

    def test_legacy_state_without_base_key(self):
        _, chars_block, _ = format_context_for_writer(self._ctx({
            "initial_relationships": {"沈放": "捡来的孩子"},
        }))
        self.assertIn("沈放（初始：捡来的孩子）", chars_block)
        self.assertNotIn("基础：", chars_block)


class RelationshipGraphTests(unittest.TestCase):
    def test_base_edges_included(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                user = User(username="u1", password_hash="x")
                session.add(user)
                await session.flush()
                novel = Novel(title="测试", user_id=user.id)
                session.add(novel)
                await session.flush()
                session.add_all([
                    Character(novel_id=novel.id, name="裴云霁", current_state={
                        "base_relationships": {"沈放": "弟子和儿子"},
                    }),
                    Character(novel_id=novel.id, name="沈放", current_state={
                        "base_relationships": {"裴云霁": "师尊/娘亲"},
                        "relationship_changes": {"裴云霁": "关系紧张"},
                    }),
                ])
                await session.flush()

                graph = await relationship_graph(novel.id, user, session)
                self.assertEqual(len(graph["edges"]), 1)
                labels = graph["edges"][0]["labels"]
                base_labels = {l["from"]: l["desc"] for l in labels if l["type"] == "base"}
                # 双向视角各一条 base 边标签
                self.assertEqual(base_labels, {
                    "裴云霁": "弟子和儿子",
                    "沈放": "师尊/娘亲",
                })
                self.assertIn("current", {l["type"] for l in labels})
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
