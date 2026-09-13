"""RPG 的滚动概要。**一份，全局**。

原先是一线一份：一份全局概要注入每条线，等于把你在密室里跟 A 说的话原样告诉 B。
那个理由随分线一起没了——历史统一成一条，模型本来就看得见全部（它得看得见，不然
接不上剧情），隔离改由 prompt 里的【场面】话术承担。所以这里钉的不再是「谁的概要
进谁的 prompt」，而是：窗口按唯一的指针切、指针只在真压出东西时才动。

顺带钉住那个最容易漏的地方：新列必须进快照表，否则读档之后概要里还留着「未来」的剧情。
"""
import unittest
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.api.routes.rpg import SNAPSHOT_DEFAULTS, SNAPSHOT_FIELDS
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgMessage, RpgModule, RpgSession
from app.services.rpg_context import history_window


def _sess(**kwargs):
    base = {"stats": {}, "location": "", "summary": "", "summarized_upto_id": 0}
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


class WindowTests(unittest.TestCase):
    def test_the_window_cuts_by_the_pointer(self):
        module = RpgModule(
            user_id=1, name="m", stat_defs=[], relation_stat_defs=[], context_turns=20,
        )
        sess = _sess(summarized_upto_id=2)
        history = [
            RpgMessage(id=i, session_id=1, role="user", content=str(i))
            for i in (1, 2, 3)
        ]
        # 压进概要的那两条不再发原文，指针之后的照发
        self.assertEqual([m.id for m in history_window(module, sess, history)], [3])

    def test_the_window_keeps_the_most_recent_turns(self):
        module = RpgModule(
            user_id=1, name="m", stat_defs=[], relation_stat_defs=[], context_turns=2,
        )
        sess = _sess()
        history = [
            RpgMessage(id=i, session_id=1, role="user", content=str(i))
            for i in range(1, 8)
        ]
        # context_turns=2 → 留最后 4 条
        self.assertEqual([m.id for m in history_window(module, sess, history)], [4, 5, 6, 7])

    def test_focus_window_only_keeps_messages_visible_to_that_npc(self):
        module = RpgModule(
            user_id=1, name="m", stat_defs=[], relation_stat_defs=[], context_turns=20,
        )
        sess = _sess(thread_upto={"7": 0})
        history = [
            RpgMessage(id=1, session_id=1, role="user", content="给老兵的秘密", present=[7]),
            RpgMessage(id=2, session_id=1, role="assistant", content="老兵听见了", present=[7]),
            RpgMessage(id=3, session_id=1, role="user", content="给老板娘的秘密", present=[9]),
            RpgMessage(id=4, session_id=1, role="assistant", content="老板娘听见了", present=[9]),
            RpgMessage(id=5, session_id=1, role="assistant", content="公开消息", present=None),
        ]
        self.assertEqual(
            [m.id for m in history_window(module, sess, history, 7)], [1, 2, 5]
        )
        self.assertEqual(
            [m.id for m in history_window(module, sess, history, 9)], [3, 4, 5]
        )
        self.assertEqual([m.id for m in history_window(module, sess, history)], [5])


class SummaryInjectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.module = RpgModule(user_id=1, name="测试模组", stat_defs=[], relation_stat_defs=[])
        self.db.add(self.module)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_the_summary_reaches_the_prompt(self):
        # 摘要是长期记忆的唯一载体。它要是没进 system，几十轮之前的剧情就断了
        from app.services.rpg_context import build_rpg_messages

        sess = RpgSession(
            module_id=self.module.id, char_name="阿隼", stats={}, location="",
            summary="你在密室里告诉老兵你杀了人",
        )
        self.db.add(sess)
        await self.db.commit()

        messages, _ = await build_rpg_messages(self.db, self.module, sess, [], "嗯")
        self.assertIn("你杀了人", messages[0]["content"])


class MaybeSummarizeTests(unittest.IsolatedAsyncioTestCase):
    """压缩本身：够不够条数、指针停在哪、失败了会不会拖垮这一轮。"""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patcher = patch.object(rpg_turn, "AsyncSessionLocal", self.sessions)
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.engine.dispose()

    async def _seed(self, count, context_turns=1):
        async with self.sessions() as db:
            module = RpgModule(
                user_id=1, name="测试模组", stat_defs=[], relation_stat_defs=[],
                context_turns=context_turns,
            )
            db.add(module)
            await db.commit()
            sess = RpgSession(module_id=module.id, char_name="阿隼", stats={}, location="")
            db.add(sess)
            await db.commit()
            db.add_all([
                RpgMessage(session_id=sess.id, role="user", content=f"第{i}句")
                for i in range(count)
            ])
            await db.commit()
            return sess.id

    async def _reload(self, session_id):
        async with self.sessions() as db:
            return await db.get(RpgSession, session_id)

    async def test_a_short_history_is_left_alone(self):
        session_id = await self._seed(2)
        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete") as call:
            self.assertFalse(await rpg_turn._maybe_summarize(session_id))
            call.assert_not_called()

    async def test_the_overflow_is_folded_into_the_summary(self):
        session_id = await self._seed(6)
        seen = {}

        async def fake(messages, **_kwargs):
            seen["prompt"] = messages[0]["content"]
            return "  老兵终于开口了  "

        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                self.assertTrue(await rpg_turn._maybe_summarize(session_id))

        sess = await self._reload(session_id)
        self.assertEqual(sess.summary, "老兵终于开口了")
        # 留最后 context_turns*2 = 2 条，压掉前 4 条，指针停在第 4 条上
        self.assertEqual(sess.summarized_upto_id, 4)
        self.assertIn("第0句", seen["prompt"])
        self.assertNotIn("第5句", seen["prompt"])

    async def test_the_next_round_only_folds_what_is_new(self):
        # 指针的用处：第二次压缩要从上次那里接着压，不能把已经折进概要的
        # 那几条再压一遍——那会让同一段往事在概要里越滚越重
        session_id = await self._seed(6)
        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", return_value="梗概"):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                await rpg_turn._maybe_summarize(session_id)
        async with self.sessions() as db:
            db.add_all([
                RpgMessage(session_id=session_id, role="user", content=f"后{i}句")
                for i in range(6)
            ])
            await db.commit()

        seen = {}

        async def fake(messages, **_kwargs):
            seen["prompt"] = messages[0]["content"]
            return "新梗概"

        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                self.assertTrue(await rpg_turn._maybe_summarize(session_id))
        self.assertNotIn("第0句", seen["prompt"])
        self.assertIn("后0句", seen["prompt"])

    async def test_the_summary_model_is_preferred_over_the_fast_one(self):
        session_id = await self._seed(6)
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            module = await db.get(RpgModule, sess.module_id)
            module.fast_model_ref = "12"
            module.summary_model_ref = "34"
            await db.commit()

        with patch.object(
            rpg_turn.llm_client, "dispatch_chat_complete", return_value="梗概"
        ):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ) as pick:
                await rpg_turn._maybe_summarize(session_id)
        self.assertEqual(pick.call_args.args, ("memory", "34"))

    async def test_an_empty_summary_model_falls_back_to_the_fast_one(self):
        # 老库这一列是空串，必须继续跟着裁决模型走，不能落到全局默认上
        session_id = await self._seed(6)
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            module = await db.get(RpgModule, sess.module_id)
            module.fast_model_ref = "12"
            await db.commit()

        with patch.object(
            rpg_turn.llm_client, "dispatch_chat_complete", return_value="梗概"
        ):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ) as pick:
                await rpg_turn._maybe_summarize(session_id)
        self.assertEqual(pick.call_args.args, ("memory", "12"))

    async def test_a_blank_reply_does_not_move_the_pointer(self):
        # 空回复照样推指针的话，被压掉的那几条从此谁也看不到了
        session_id = await self._seed(6)
        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", return_value="   "):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                self.assertFalse(await rpg_turn._maybe_summarize(session_id))
        sess = await self._reload(session_id)
        self.assertEqual(sess.summarized_upto_id, 0)

    async def test_global_summary_does_not_write_npc_slots(self):
        # 全局摘要与 NPC 摘要分开存储，生成全局摘要不能污染任何 NPC 槽位。
        session_id = await self._seed(6)
        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", return_value="梗概"):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                await rpg_turn._maybe_summarize(session_id)
        sess = await self._reload(session_id)
        self.assertEqual(sess.thread_summaries, {})
        self.assertEqual(sess.thread_upto, {})


    async def test_npc_summary_is_written_to_its_own_slot(self):
        session_id = await self._seed(6)
        async with self.sessions() as db:
            messages = (await db.execute(
                select(RpgMessage).where(RpgMessage.session_id == session_id)
            )).scalars().all()
            for message in messages:
                message.present = [7]
            await db.commit()
        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", return_value="姊楁"):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                self.assertTrue(await rpg_turn._maybe_summarize(session_id, 7))
        sess = await self._reload(session_id)
        self.assertEqual(sess.thread_summaries, {"7": "姊楁"})
        self.assertGreater(sess.thread_upto.get("7", 0), 0)

    async def test_global_summary_ignores_private_messages(self):
        session_id = await self._seed(8)
        async with self.sessions() as db:
            messages = (await db.execute(
                select(RpgMessage).where(RpgMessage.session_id == session_id)
            )).scalars().all()
            for index, message in enumerate(messages):
                message.content = f"private-{index}" if index < 4 else f"public-{index}"
                message.present = [7] if index < 4 else [7, 9]
            await db.commit()
        seen = {}

        async def fake(messages, **_kwargs):
            seen["prompt"] = messages[0]["content"]
            return "全局"

        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                self.assertTrue(await rpg_turn._maybe_summarize(session_id))
        self.assertNotIn("private-0", seen["prompt"])
        self.assertIn("public-4", seen["prompt"])


class SnapshotCoverageTests(unittest.TestCase):
    def test_the_summary_is_in_the_snapshot(self):
        """漏了不会报错，只会在读档之后留下一份还写着「未来」的概要。"""
        for field in (
            "summary", "summarized_upto_id", "thread_summaries", "thread_upto",
        ):
            with self.subTest(field=field):
                self.assertIn(field, SNAPSHOT_FIELDS)

    def test_every_snapshot_field_exists_on_the_model(self):
        for field in SNAPSHOT_FIELDS:
            with self.subTest(field=field):
                self.assertTrue(hasattr(RpgSession, field))


if __name__ == "__main__":
    unittest.main()
