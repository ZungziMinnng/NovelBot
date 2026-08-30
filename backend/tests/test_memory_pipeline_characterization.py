"""记忆更新段（orchestrator Node 5/6）的特征测试。

拆分重构前先给现有行为"拍照"：事件序列、projection_status、token 汇总、
新设定候选补入、失败降级路径都固定在断言里。拆分后本文件必须原样通过。
"""
import asyncio
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, llm_usage as _llm_usage  # noqa: F401
from app.models.chapter import Chapter
from app.models.llm_usage import LlmUsage
from app.models.memory import Memory
from app.models.novel import Novel
from app.agents import critic, memory_pipeline, orchestrator, writer
from app.agents import character_agent
from app.services import summarizer, entity_embeddings, llm_client


def _ctx() -> dict:
    return {
        "_all_character_names": ["主角"],
        "_all_system_names": ["已知实体名"],
        "_all_location_info": [],
        "_all_technique_names": [],
        "_all_faction_names": [],
    }


async def _fake_writer_stream(**kwargs):
    yield {"llm_payload": {"model": "writer-x"}}
    yield "正文第一段。"
    yield "正文第二段。"
    yield ("stop", 11, 22)


async def _fake_revision_stream(**kwargs):
    yield {"llm_payload": {"model": "writer-x"}}
    yield "修订后正文。"
    yield ("stop", 13, 24)


def _parse(raw_events: list[str]) -> list[dict]:
    return [json.loads(s[len("data: "):].strip()) for s in raw_events]


class MemoryPipelineCharacterizationTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    async def _make_session(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        return engine, maker

    async def _seed(self, session, *, enable_critic=False):
        novel = Novel(title="测试", enable_critic=enable_critic, enable_detail_review=False)
        session.add(novel)
        await session.commit()
        return novel

    def _patches(self, maker, *, summarize_side_effect=None, critic_results=None):
        async def fake_summarize_and_discover(session, chapter, novel, **kwargs):
            if summarize_side_effect:
                raise summarize_side_effect
            return "本章摘要。", {"characters": [{"name": "新角色"}]}, 10, 5

        async def fake_update_character_states(session, chapter, novel, **kwargs):
            return True, "", 7, 3, ["漏网角色", "已知实体名"], [1]

        async def fake_update_entity_location_states(session, chapter, novel, **kwargs):
            return {
                "entity": {"ok": True, "warning": "", "unmatched": [], "updated_ids": [2]},
                "location": {"ok": True, "warning": "", "unmatched": [], "updated_ids": []},
                "input_tokens": 4, "output_tokens": 2,
            }

        def fake_filter_discovered(discovered_raw, *args):
            return [{"name": "新角色", "role": "配角", "description": "d"}], [], [], [], []

        critic_queue = list(critic_results or [])

        async def fake_review_chapter(**kwargs):
            return critic_queue.pop(0)

        reembed = AsyncMock()
        return reembed, (
            patch.object(orchestrator, "build_generation_context", AsyncMock(return_value=_ctx())),
            patch.object(memory_pipeline, "AsyncSessionLocal", maker),
            patch.object(writer, "stream_chapter", _fake_writer_stream),
            patch.object(writer, "stream_chapter_revision", _fake_revision_stream),
            patch.object(critic, "review_chapter", fake_review_chapter),
            patch.object(llm_client, "get_agent_client", return_value=("ref", "openai")),
            patch.object(llm_client, "resolve_model_ref", return_value=("fast-x", None)),
            patch.object(summarizer, "summarize_and_discover", fake_summarize_and_discover),
            patch.object(summarizer, "update_character_states", fake_update_character_states),
            patch.object(summarizer, "update_entity_location_states", fake_update_entity_location_states),
            patch.object(character_agent, "filter_discovered", fake_filter_discovered),
            patch.object(entity_embeddings, "reembed_updated", reembed),
        )

    async def _generate(self, session, novel, maker, **patch_kwargs):
        reembed, patches = self._patches(maker, **patch_kwargs)
        raw = []
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            async for evt in orchestrator.run_chapter_generation(
                session, novel, chapter_number=3, volume=1,
                instruction="测试指令", target_words=1000,
            ):
                raw.append(evt)
        return _parse(raw), reembed

    def test_success_event_sequence_and_persistence(self):
        async def scenario():
            engine, maker = await self._make_session()
            session = maker()
            try:
                novel = await self._seed(session)
                events, reembed = await self._generate(session, novel, maker)

                names = [e["event"] for e in events]
                self.assertEqual(names, [
                    "stage",            # building_context
                    "agent_start",      # context 上下文组装
                    "agent_done",       # context（测试上下文无 _meta，0 个区块）
                    "stage",            # writing
                    "agent_start",      # writer
                    "llm_request",
                    "token", "token",
                    "llm_call",         # writer
                    "agent_done",       # writer
                    "stage",            # saving
                    "stage",            # updating_memory
                    "stage",            # updating_memory_summary
                    "agent_start",      # summarizer
                    "llm_call",         # summarizer
                    "agent_done",       # summarizer
                    "stage",            # updating_memory_characters
                    "agent_start",      # char_update
                    "llm_call",         # char_update
                    "agent_done",       # char_update
                    "stage",            # updating_memory_entities
                    "agent_start",      # entity_update
                    "llm_call",         # entity_update
                    "agent_done",       # entity_update
                    "projection_status",
                    "new_characters",
                    "agent_start",      # discovery 发现汇总
                    "agent_done",       # discovery
                    "total_usage",
                    "done",
                ])
                stages = [e["data"] for e in events if e["event"] == "stage"]
                self.assertEqual(stages, [
                    "building_context", "writing", "saving", "updating_memory",
                    "updating_memory_summary", "updating_memory_characters",
                    "updating_memory_entities",
                ])

                by_event = {e["event"]: e["data"] for e in events}
                self.assertEqual(by_event["projection_status"]["status"], {
                    "summary": "done",
                    "character_state": "done",
                    "entity_state": "done",
                    "location_state": "done",
                })
                done_by_agent = {
                    e["data"]["agent"]: e["data"] for e in events if e["event"] == "agent_done"
                }
                self.assertEqual(done_by_agent["summarizer"]["input_tokens"], 10)
                self.assertEqual(done_by_agent["summarizer"]["output_tokens"], 5)
                self.assertTrue(done_by_agent["summarizer"]["passed"])
                self.assertEqual(done_by_agent["char_update"]["input_tokens"], 7)
                self.assertEqual(done_by_agent["char_update"]["output_tokens"], 3)
                self.assertTrue(done_by_agent["char_update"]["passed"])
                self.assertEqual(done_by_agent["entity_update"]["input_tokens"], 4)
                self.assertEqual(done_by_agent["entity_update"]["output_tokens"], 2)
                self.assertTrue(done_by_agent["entity_update"]["passed"])
                self.assertEqual(done_by_agent["context"]["label"], "上下文组装（0 个区块）")
                self.assertEqual(done_by_agent["discovery"]["label"], "发现新设定：角色2")

                # 未匹配名补入候选：「漏网角色」补入，「已知实体名」被已知名单排除
                cand_names = [c["name"] for c in by_event["new_characters"]["candidates"]]
                self.assertEqual(cand_names, ["新角色", "漏网角色"])

                self.assertEqual(by_event["total_usage"], {
                    "input_tokens": 32, "output_tokens": 32,  # 11+21 / 22+10
                })

                chapter = (await session.execute(
                    select(Chapter).where(Chapter.novel_id == novel.id)
                )).scalar_one()
                self.assertEqual(chapter.content, "正文第一段。正文第二段。")
                self.assertEqual(chapter.model_used, "writer-x")
                self.assertEqual(by_event["done"], str(chapter.id))

                # 生成前快照已创建
                snap = (await session.execute(
                    select(Memory).where(Memory.memory_type == "state_snapshot")
                )).scalars().all()
                self.assertEqual(len(snap), 1)

                # LLM 用量记账：writer + summarizer + char_update + entity_update
                usage_agents = (await session.execute(
                    select(LlmUsage.agent).order_by(LlmUsage.id)
                )).scalars().all()
                self.assertEqual(usage_agents, ["writer", "summarizer", "char_update", "entity_update"])

                reembed.assert_awaited_once_with(
                    session, novel.id, char_ids=[1], entity_ids=[2], location_ids=[],
                )
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_critic_fail_then_revision_pass(self):
        async def scenario():
            engine, maker = await self._make_session()
            session = maker()
            try:
                novel = await self._seed(session, enable_critic=True)
                events, _ = await self._generate(
                    session, novel, maker,
                    critic_results=[
                        (False, "节奏太快", 5, 2, "critic-x"),
                        (True, "", 5, 2, "critic-x"),
                    ],
                )

                names = [e["event"] for e in events]
                self.assertEqual(names[:26], [
                    "stage",            # building_context
                    "agent_start",      # context 上下文组装
                    "agent_done",       # context
                    "stage",            # writing
                    "agent_start",      # writer 初稿
                    "llm_request",
                    "token", "token",
                    "llm_call",
                    "agent_done",
                    "stage",            # reviewing
                    "agent_start",      # critic
                    "llm_call",
                    "agent_done",       # critic 未通过
                    "critic_issues",
                    "original_draft",
                    "stage",            # revising_1
                    "agent_start",      # writer 修订
                    "llm_request",
                    "token",
                    "llm_call",
                    "agent_done",
                    "stage",            # reviewing（第二轮）
                    "agent_start",      # critic
                    "llm_call",
                    "agent_done",       # critic 通过
                ])
                self.assertEqual(names[26], "stage")  # saving
                self.assertEqual(names[-1], "done")

                stages = [e["data"] for e in events if e["event"] == "stage"]
                self.assertEqual(stages[:5], [
                    "building_context", "writing", "reviewing", "revising_1", "reviewing",
                ])

                by_event = {e["event"]: e["data"] for e in events}
                self.assertEqual(by_event["critic_issues"], {"issues_text": "节奏太快"})
                self.assertEqual(by_event["original_draft"], {"text": "正文第一段。正文第二段。"})

                critic_dones = [
                    e["data"] for e in events
                    if e["event"] == "agent_done" and e["data"]["agent"] == "critic"
                ]
                self.assertEqual([d["passed"] for d in critic_dones], [False, True])

                # 定稿为修订稿；token 合计含初稿+两次审稿+修订+记忆
                chapter = (await session.execute(
                    select(Chapter).where(Chapter.novel_id == novel.id)
                )).scalar_one()
                self.assertEqual(chapter.content, "修订后正文。")
                self.assertEqual(by_event["total_usage"], {
                    "input_tokens": 55,   # 11+5+13+5+21
                    "output_tokens": 60,  # 22+2+24+2+10
                })
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_summary_failure_degrades_gracefully(self):
        async def scenario():
            engine, maker = await self._make_session()
            session = maker()
            try:
                novel = await self._seed(session)
                events, _ = await self._generate(
                    session, novel, maker,
                    summarize_side_effect=RuntimeError("boom"),
                )

                by_event = {e["event"]: e["data"] for e in events}
                status = by_event["projection_status"]["status"]
                self.assertEqual(status["summary"], "failed:RuntimeError: boom")
                self.assertEqual(status["character_state"], "done")
                self.assertEqual(status["entity_state"], "done")

                warnings = [e["data"] for e in events if e["event"] == "warning"]
                self.assertEqual(warnings, ["摘要生成失败: boom"])

                # summarizer 的 llm_call 记为 error，后续步骤照常
                summarizer_calls = [
                    e["data"] for e in events
                    if e["event"] == "llm_call" and e["data"]["agent"] == "summarizer"
                ]
                self.assertEqual(summarizer_calls[0]["status"], "error")

                # 摘要失败 → 无发现结果，但状态更新的未匹配名仍补入候选
                cand_names = [c["name"] for c in by_event["new_characters"]["candidates"]]
                self.assertEqual(cand_names, ["漏网角色"])

                # 流程仍走完：章节已保存、done 事件发出
                self.assertIn("done", by_event)
                chapter = (await session.execute(
                    select(Chapter).where(Chapter.novel_id == novel.id)
                )).scalar_one()
                self.assertEqual(chapter.content, "正文第一段。正文第二段。")
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())


if __name__ == "__main__":
    unittest.main()
