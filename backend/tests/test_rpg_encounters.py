"""幕后往事：两个不在玩家跟前的 NPC 碰上了，之间发生了什么。

底线：
1. 模组没开就一个字都不多问，调度输出和以前一样。
2. 碰没碰上由引擎核：两人这一格挪完之后得在同一处，而且不在玩家跟前。
3. 当事人和撞见的人卡上有这件事，并被告知玩家还不知道、可以瞒；别人卡上没有。
"""
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.database import Base
from app.models import sensitive_word, text_replace_backup, llm_usage  # noqa: F401
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgLocation, RpgModule, RpgNpc, RpgSession
from app.services.rpg_state import npc_offscreen_of, set_npc_bond

STAT_DEFS = [{"name": "精力", "initial": 100, "min": 0, "max": 100}]


class EncounterTests(unittest.IsolatedAsyncioTestCase):
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

    async def _setup(self, *npcs, encounters=True, location="客厅"):
        """npcs 是 (名字, 常驻地点, ai_scheduled)。"""
        async with self.sessions() as db:
            module = RpgModule(
                user_id=1, name="小区", stat_defs=STAT_DEFS, relation_stat_defs=[],
                time_slots=["早", "中", "晚"], npc_encounters=encounters,
            )
            db.add(module)
            await db.commit()
            ids = []
            for name, place, scheduled in npcs:
                npc = RpgNpc(module_id=module.id, name=name, location=place,
                             persona="温和", ai_scheduled=scheduled)
                db.add(npc)
                await db.commit()
                ids.append(npc.id)
            db.add_all([RpgLocation(module_id=module.id, name=name)
                        for name in ("客厅", "暗间", "物业办公室")])
            sess = RpgSession(
                module_id=module.id, char_name="阿隼", stats={"精力": 100},
                location=location, slot="晚", day=4, status="alive",
                chronicle=[], npc_states={}, npc_activities={},
            )
            db.add(sess)
            await db.commit()
            return sess.id, ids

    async def _run(self, session_id, text):
        prompts = []

        async def fake_dispatch(messages=None, **kwargs):
            prompts.append(messages[0]["content"])
            return text

        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake_dispatch):
            await rpg_turn.idle_npc_activities(session_id, set())
        async with self.sessions() as db:
            return await db.get(RpgSession, session_id), prompts

    async def test_off_by_default_nothing_is_asked_or_kept(self):
        session_id, _ = await self._setup(("韩曼宁", "暗间", True), ("范建明", "暗间", True),
                                          encounters=False)
        sess, prompts = await self._run(
            session_id, "韩曼宁：在暗间整理衣服\n范建明：在暗间抽烟\n"
                        "相遇：韩曼宁＋范建明｜暗间｜两人抱在一起｜关系：秘密情人",
        )
        self.assertNotIn("相遇", prompts[0])
        self.assertEqual(sess.npc_offscreen or [], [])
        self.assertEqual(sess.npc_bonds or [], [])
        # 相遇行被摘掉，不会落进近况
        self.assertEqual(len(sess.npc_activities), 2)

    async def test_a_meeting_in_the_same_place_is_kept_with_a_witness(self):
        session_id, (wife, man, guard) = await self._setup(
            ("韩曼宁", "暗间", True), ("范建明", "暗间", True), ("保安", "暗间", False),
        )
        sess, prompts = await self._run(
            session_id, "韩曼宁：在暗间整理衣服\n范建明：在暗间抽烟\n"
                        "**相遇**：韩曼宁＋范建明｜暗间｜他拉住她的手，她没有挣开｜关系：暗生好感",
        )
        self.assertIn("暗间：韩曼宁、范建明", prompts[0])
        [row] = sess.npc_offscreen
        self.assertEqual((row["a"], row["b"], row["place"]), (wife, man, "暗间"))
        self.assertEqual(row["witnesses"], [guard])
        self.assertFalse(row["exposed"])
        [bond] = sess.npc_bonds
        self.assertEqual(bond["label"], "暗生好感")
        self.assertEqual(len(npc_offscreen_of(sess, guard)), 1)
        # 近况照记，相遇行本身不进近况
        self.assertEqual(sess.npc_activities[str(wife)], "在暗间整理衣服")

    async def test_two_people_in_different_places_did_not_meet(self):
        session_id, _ = await self._setup(("韩曼宁", "暗间", True), ("范建明", "物业办公室", True))
        sess, _ = await self._run(
            session_id, "韩曼宁：在暗间整理衣服\n范建明：在物业办公室看监控\n"
                        "相遇：韩曼宁＋范建明｜暗间｜两人说了几句话",
        )
        self.assertEqual(sess.npc_offscreen or [], [])

    async def test_a_meeting_in_front_of_the_player_is_not_offscreen(self):
        # 玩家就在客厅：那是正文的事，不是幕后
        session_id, _ = await self._setup(("韩曼宁", "客厅", True), ("范建明", "客厅", True))
        sess, _ = await self._run(
            session_id, "韩曼宁：在客厅看电视\n范建明：在客厅喝茶\n"
                        "相遇：韩曼宁＋范建明｜客厅｜两人对视了一眼",
        )
        self.assertEqual(sess.npc_offscreen or [], [])

    async def test_bond_keeps_its_label_when_told_unchanged(self):
        session_id, (wife, man) = await self._setup(("韩曼宁", "暗间", True), ("范建明", "暗间", True))
        await self._run(session_id, "相遇：韩曼宁＋范建明｜暗间｜他递给她一杯水｜关系：暗生好感")
        sess, _ = await self._run(session_id, "相遇：韩曼宁＋范建明｜暗间｜两人没说话｜关系：不变")
        self.assertEqual([b["label"] for b in sess.npc_bonds], ["暗生好感"])
        self.assertEqual(len(sess.npc_offscreen), 2)


class BondStateTests(unittest.TestCase):
    def test_a_changed_label_is_hidden_again(self):
        from types import SimpleNamespace
        a, b = SimpleNamespace(id=3, name="韩曼宁"), SimpleNamespace(id=7, name="范建明")
        sess = SimpleNamespace(day=4, slot="晚", npc_bonds=[])
        set_npc_bond(sess, b, a, "朋友")
        sess.npc_bonds[0]["exposed"] = True
        set_npc_bond(sess, a, b, "秘密情人")
        [bond] = sess.npc_bonds
        self.assertEqual((bond["a"], bond["b"], bond["label"]), (3, 7, "秘密情人"))
        self.assertFalse(bond["exposed"])


class EncounterInjectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.module = RpgModule(user_id=1, name="小区", stat_defs=STAT_DEFS)
        self.db.add(self.module)
        await self.db.commit()
        self.wife = RpgNpc(module_id=self.module.id, name="韩曼宁", location="客厅", persona="温和")
        self.other = RpgNpc(module_id=self.module.id, name="李婶", location="客厅", persona="热心")
        self.db.add_all([self.wife, self.other])
        await self.db.commit()
        row = {"id": "x", "day": 4, "slot": "晚", "place": "暗间", "a": self.wife.id, "b": 99,
               "names": {str(self.wife.id): "韩曼宁", "99": "范建明"},
               "content": "他拉住她的手，她没有挣开", "witnesses": [], "exposed": False}
        self.sess = RpgSession(
            module_id=self.module.id, char_name="阿隼", stats={"精力": 100},
            location="客厅", slot="晚", npc_states={}, npc_notes={}, npc_activities={},
            npc_offscreen=[row],
            npc_bonds=[{"a": self.wife.id, "b": 99, "names": row["names"], "label": "暗生好感",
                        "day": 4, "slot": "晚", "exposed": False}],
        )
        self.db.add(self.sess)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _system(self):
        from app.services.rpg_context import build_rpg_messages
        messages, _diag = await build_rpg_messages(
            self.db, self.module, self.sess, [], "你今晚去哪了？", None, None
        )
        return messages[0]["content"]

    async def test_she_knows_and_is_told_to_hide_it(self):
        system = await self._system()
        self.assertIn("和范建明：暗生好感（玩家还不知道）", system)
        self.assertIn("他拉住她的手，她没有挣开（玩家还不知道）", system)
        self.assertIn("撒谎", system)
        # 只挂在她自己的卡上：李婶那张卡后面不该跟着这件事
        self.assertEqual(system.count("他拉住她的手"), 1)

    async def test_exposed_rows_lose_the_secret_note(self):
        self.sess.npc_offscreen = [{**self.sess.npc_offscreen[0], "exposed": True}]
        self.sess.npc_bonds = [{**self.sess.npc_bonds[0], "exposed": True}]
        system = await self._system()
        self.assertIn("和范建明：暗生好感", system)
        self.assertNotIn("玩家还不知道", system)
