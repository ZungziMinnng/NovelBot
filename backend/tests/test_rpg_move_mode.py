"""AI 调度挑去处的两种办法（RpgModule.npc_move_mode）。

底线：
1. 默认 "ai"：模型拿到「可去」自己挑，和以前一样。
2. "random"：引擎抽中一处，模型只拿到「这一格去了：某处」；她写的那句话不点别的地名，
   就挪过去。
3. 抽中了却写她在别处 → 整行丢掉，不挪也不记，侧栏和近况不能对不上。
4. 角色自己的 move_mode 盖过模组的，空串跟随模组。
5. 「已离开」的人只有 "random" 才带回来，而且必须真抽中了一个地方；"ai" 的照旧一直不在。
"""
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.database import Base
from app.models import sensitive_word, text_replace_backup, llm_usage  # noqa: F401
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgLocation, RpgModule, RpgNpc, RpgSession

STAT_DEFS = [{"name": "精力", "initial": 100, "min": 0, "max": 100}]


class _Base(unittest.IsolatedAsyncioTestCase):
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

    async def _setup(self, mode=None, own=""):
        async with self.sessions() as db:
            extra = {} if mode is None else {"npc_move_mode": mode}
            module = RpgModule(user_id=1, name="小区", stat_defs=STAT_DEFS,
                               relation_stat_defs=[], time_slots=["早", "中", "晚"], **extra)
            db.add(module)
            await db.commit()
            npc = RpgNpc(module_id=module.id, name="韩曼宁", location="暗间", persona="温和",
                         ai_scheduled=True, random_movement=True, move_mode=own)
            db.add(npc)
            db.add_all([RpgLocation(module_id=module.id, name=name)
                        for name in ("客厅", "暗间", "物业办公室")])
            sess = RpgSession(
                module_id=module.id, char_name="阿隼", stats={"精力": 100},
                location="客厅", slot="晚", day=4, status="alive",
                chronicle=[], npc_states={}, npc_activities={},
            )
            db.add(sess)
            await db.commit()
            return sess.id, npc.id

    async def _run(self, session_id, text):
        prompts = []

        async def fake_dispatch(messages=None, **kwargs):
            prompts.append(messages[0]["content"])
            return text

        # 抽签钉死成候选里最后一个：暗间排掉之后是 [客厅, 物业办公室]
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake_dispatch), \
             patch.object(rpg_turn.random, "choice", lambda xs: xs[-1]):
            await rpg_turn.idle_npc_activities(session_id, set(), from_clock=True)
        async with self.sessions() as db:
            return await db.get(RpgSession, session_id), prompts


class MoveModeTests(_Base):
    async def test_default_lets_the_model_pick(self):
        session_id, _ = await self._setup()
        _sess, prompts = await self._run(session_id, "韩曼宁：在暗间整理衣服")
        roster = prompts[0].split("=== 这些人")[1]
        self.assertIn("可去：", roster)
        self.assertNotIn("这一格去了：", roster)

    async def test_random_moves_her_where_the_draw_landed(self):
        session_id, npc_id = await self._setup("random")
        sess, prompts = await self._run(session_id, "韩曼宁：翻着登记簿跟保安闲聊")
        roster = prompts[0].split("=== 这些人")[1]
        self.assertIn("这一格去了：物业办公室", roster)
        self.assertNotIn("可去：", roster)
        self.assertEqual(sess.npc_places[str(npc_id)], "物业办公室")
        self.assertEqual(sess.npc_activities[str(npc_id)], "翻着登记簿跟保安闲聊")

    async def test_random_drops_a_line_that_puts_her_somewhere_else(self):
        session_id, npc_id = await self._setup("random")
        sess, _ = await self._run(session_id, "韩曼宁：在客厅看电视")
        self.assertNotIn(str(npc_id), sess.npc_places or {})
        self.assertEqual(sess.npc_activities or {}, {})

    async def test_her_own_choice_beats_the_module(self):
        session_id, npc_id = await self._setup("ai", own="random")
        sess, prompts = await self._run(session_id, "韩曼宁：翻着登记簿跟保安闲聊")
        self.assertIn("这一格去了：物业办公室", prompts[0].split("=== 这些人")[1])
        self.assertEqual(sess.npc_places[str(npc_id)], "物业办公室")

    async def _leave(self, session_id, npc_id):
        """剧情写她走了、没说去哪（rpg_state.AWAY）"""
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            sess.npc_places = {str(npc_id): "__away__"}
            await db.commit()

    async def test_random_draws_an_absent_npc_back(self):
        session_id, npc_id = await self._setup("random")
        await self._leave(session_id, npc_id)
        sess, prompts = await self._run(session_id, "韩曼宁：翻着登记簿跟保安闲聊")
        self.assertIn("这一格去了：物业办公室", prompts[0].split("=== 这些人")[1])
        self.assertEqual(sess.npc_places[str(npc_id)], "物业办公室")

    async def test_random_keeps_her_away_when_the_draw_has_nowhere_to_land(self):
        session_id, npc_id = await self._setup("random")
        await self._leave(session_id, npc_id)
        async with self.sessions() as db:
            npc = await db.get(RpgNpc, npc_id)
            npc.random_movement_places = ["早就删掉的地方"]
            await db.commit()
        sess, prompts = await self._run(session_id, "韩曼宁：翻着登记簿跟保安闲聊")
        self.assertEqual(prompts, [])
        self.assertEqual(sess.npc_places[str(npc_id)], "__away__")
        self.assertEqual(sess.npc_activities or {}, {})

    async def test_ai_mode_leaves_an_absent_npc_alone(self):
        session_id, npc_id = await self._setup("ai")
        await self._leave(session_id, npc_id)
        sess, prompts = await self._run(session_id, "韩曼宁：在暗间整理衣服")
        self.assertEqual(prompts, [])
        self.assertEqual(sess.npc_places[str(npc_id)], "__away__")
        self.assertEqual(sess.npc_activities or {}, {})

    async def test_she_can_opt_out_of_a_random_module(self):
        session_id, _ = await self._setup("random", own="ai")
        _sess, prompts = await self._run(session_id, "韩曼宁：在暗间整理衣服")
        roster = prompts[0].split("=== 这些人")[1]
        self.assertIn("可去：", roster)
        self.assertNotIn("这一格去了：", roster)


class TogetherHoldTests(_Base):
    """两个闲人在同一处时先一起待满 NPC_TOGETHER_SLOTS 格，再各自照常挪。"""

    TEXT = "韩曼宁：在暗间整理衣服\n周丽：在暗间整理衣服"

    async def _setup(self, mode="random", own=""):
        session_id, first = await super()._setup(mode, own)
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            npc = RpgNpc(module_id=sess.module_id, name="周丽", location="暗间", persona="爽朗",
                         ai_scheduled=True, random_movement=True)
            db.add(npc)
            await db.commit()
            self.key = f"{min(first, npc.id)}-{max(first, npc.id)}"
            return session_id, (first, npc.id)

    async def _next_slot(self, session_id, slot, day=4):
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            sess.slot, sess.day = slot, day
            await db.commit()

    async def test_they_stay_together_then_draw_again(self):
        session_id, _ = await self._setup()
        sess, prompts = await self._run(session_id, self.TEXT)
        self.assertNotIn("这一格去了：", prompts[0].split("=== 这些人")[1])
        self.assertEqual(sess.npc_places or {}, {})
        self.assertEqual(sess.npc_together, {self.key: {"count": 1, "last": "4|晚"}})

        # 同一格再调一次（回合那条路一格里可能不止一次）不算多待一格
        sess, _ = await self._run(session_id, self.TEXT)
        self.assertEqual(sess.npc_together[self.key]["count"], 1)

        await self._next_slot(session_id, "早", day=5)
        sess, prompts = await self._run(session_id, "韩曼宁：翻登记簿\n周丽：翻登记簿")
        roster = prompts[0].split("=== 这些人")[1]
        self.assertEqual(roster.count("这一格去了：物业办公室"), 2)
        self.assertEqual(sess.npc_together[self.key]["count"], 2)

    async def test_ledger_drops_the_pair_once_they_part(self):
        session_id, (_, second) = await self._setup()
        await self._run(session_id, self.TEXT)
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            sess.npc_places = {str(second): "物业办公室"}
            await db.commit()
        await self._next_slot(session_id, "早", day=5)
        sess, _ = await self._run(session_id, self.TEXT)
        self.assertEqual(sess.npc_together, {})

    async def test_ai_mode_holds_them_too(self):
        session_id, _ = await self._setup("ai")
        _sess, prompts = await self._run(session_id, self.TEXT)
        self.assertNotIn("可去：", prompts[0].split("=== 这些人")[1])
