"""知情账：谁知道什么。

底线：
1. 一条都没登记时，提示词和以前逐字一致。
2. 知情的人卡上写「她知道」，不知情的人卡上写「她不知道，不许沾边」。
3. 玩家的秘密在【你】里带着知情名单。
4. 玩家查明（player_knows）后，NPC 自己的秘密不再标「玩家还不知道」。
"""
import unittest
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import sensitive_word, text_replace_backup, llm_usage  # noqa: F401
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgModule, RpgNpc, RpgSession
from app.services.rpg_state import (
    SECRET_LIMIT, add_secret, apply_secret_proposal, drop_secret, edit_secret,
    secret_stances, set_secret_stance,
)
from app.services.rpg_settlement import filter_secret_updates, secret_rows_for_prompt

STAT_DEFS = [{"name": "精力", "initial": 100, "min": 0, "max": 100}]
NAMES = {3: "韩曼宁", 7: "李婶"}


class SecretStateTests(unittest.TestCase):
    def test_add_edit_drop(self):
        sess = SimpleNamespace(day=2, secrets=[])
        row = add_secret(sess, " 我是 通缉犯 ", 0, [3, 3, 99], NAMES)
        self.assertEqual(row["content"], "我是 通缉犯")
        self.assertEqual(row["known_by"], [3, 99])
        self.assertTrue(row["player_knows"])
        self.assertEqual(row["names"], {"3": "韩曼宁"})

        self.assertTrue(edit_secret(sess, row["id"], NAMES, known_by=[3, 7]))
        self.assertEqual(sess.secrets[0]["names"], {"3": "韩曼宁", "7": "李婶"})
        self.assertFalse(edit_secret(sess, "nope", NAMES, content="x"))

        drop_secret(sess, row["id"])
        self.assertEqual(sess.secrets, [])

    def test_owner_is_never_in_known_by_and_player_secret_stays_known(self):
        sess = SimpleNamespace(day=1, secrets=[])
        row = add_secret(sess, "她偷了账本", 3, [3, 7], NAMES, player_knows=False)
        self.assertEqual(row["known_by"], [7])
        self.assertFalse(row["player_knows"])
        edit_secret(sess, row["id"], NAMES, player_knows=True)
        self.assertTrue(sess.secrets[0]["player_knows"])
        mine = add_secret(sess, "我有剑谱", 0, [], NAMES, player_knows=False)
        self.assertTrue(mine["player_knows"])

    def test_empty_and_full(self):
        sess = SimpleNamespace(day=1, secrets=[])
        self.assertIsNone(add_secret(sess, "  ", 0, [], NAMES))
        for i in range(SECRET_LIMIT):
            self.assertIsNotNone(add_secret(sess, f"事{i}", 0, [], NAMES))
        self.assertIsNone(add_secret(sess, "多的一条", 0, [], NAMES))

    def test_knows_vs_unaware(self):
        sess = SimpleNamespace(day=1, secrets=[])
        add_secret(sess, "玩家的底", 0, [3], NAMES)
        add_secret(sess, "李婶的事", 7, [], NAMES)
        st = secret_stances(sess, 3)
        self.assertEqual([r["content"] for r in st["knows"]], ["玩家的底"])
        self.assertEqual([r["content"] for r in st["unaware"]], ["李婶的事"])
        st = secret_stances(sess, 7)
        self.assertEqual([r["content"] for r in st["knows"]], ["李婶的事"])
        self.assertEqual([r["content"] for r in st["unaware"]], ["玩家的底"])

    def test_stance_moves_one_person_between_states(self):
        sess = SimpleNamespace(day=1, secrets=[])
        row = add_secret(sess, "玩家的底", 0, [], NAMES)
        self.assertTrue(set_secret_stance(sess, row["id"], 3, "suspects", NAMES))
        self.assertEqual(secret_stances(sess, 3)["suspects"][0]["content"], "玩家的底")
        self.assertTrue(set_secret_stance(sess, row["id"], 3, "misled", NAMES, "他只是个货郎"))
        st = secret_stances(sess, 3)
        self.assertEqual(st["suspects"], [])
        self.assertEqual(st["misled"][0][1], "他只是个货郎")
        self.assertFalse(set_secret_stance(sess, row["id"], 3, "misled", NAMES, ""))
        self.assertTrue(set_secret_stance(sess, row["id"], 3, "knows", NAMES))
        st = secret_stances(sess, 3)
        self.assertEqual((st["misled"], st["suspects"]), ([], []))
        self.assertEqual(len(st["knows"]), 1)
        self.assertEqual(sess.secrets[0]["misled"], {})
        # 主人自己不能被设成「被骗」
        own = add_secret(sess, "她的事", 7, [], NAMES)
        self.assertFalse(set_secret_stance(sess, own["id"], 7, "knows", NAMES))


NPCS = [SimpleNamespace(id=3, name="韩曼宁", keywords=""), SimpleNamespace(id=7, name="李婶", keywords="")]
NARRATION = "韩曼宁盯着他掌心的烙印，倒吸了一口凉气。李婶在一旁什么也没看见，只顾着端茶。"


class SecretProposalTests(unittest.TestCase):
    def setUp(self):
        self.sess = SimpleNamespace(day=1, secrets=[])
        self.row = add_secret(self.sess, "我掌心有通缉烙印", 0, [], NAMES)

    def run_filter(self, updates, pending=()):
        return filter_secret_updates({"secret_updates": updates}, NARRATION, self.sess.secrets, NPCS, 9, pending)

    def test_learn_needs_real_quote_and_known_secret(self):
        ok = {"op": "learn", "secret": 1, "who": "韩曼宁", "stance": "knows", "quote": "韩曼宁盯着他掌心的烙印"}
        self.assertEqual(len(self.run_filter([ok])), 1)
        self.assertEqual(self.run_filter([{**ok, "quote": "她早就知道了"}]), [])
        self.assertEqual(self.run_filter([{**ok, "secret": 5}]), [])
        self.assertEqual(self.run_filter([{**ok, "stance": "gossip"}]), [])
        self.assertEqual(self.run_filter([{**ok, "stance": "misled"}]), [])  # 缺 belief

    def test_duplicate_and_already_known_dropped(self):
        ok = {"op": "learn", "secret": 1, "who": "韩曼宁", "stance": "knows", "quote": "韩曼宁盯着他掌心的烙印"}
        first = self.run_filter([ok, ok])
        self.assertEqual(len(first), 1)
        self.assertEqual(self.run_filter([ok], pending=first), [])
        set_secret_stance(self.sess, self.row["id"], 3, "knows", NAMES)
        self.assertEqual(self.run_filter([ok]), [])

    def test_accept_applies_all_three_kinds(self):
        learn = self.run_filter([{"op": "learn", "secret": 1, "who": "李婶", "stance": "misled",
                                  "belief": "他只是个货郎", "quote": "李婶在一旁什么也没看见"}])[0]
        self.assertTrue(apply_secret_proposal(self.sess, learn, NAMES))
        self.assertEqual(self.sess.secrets[0]["misled"], {"7": "他只是个货郎"})
        new = self.run_filter([{"op": "new", "content": "李婶在偷藏账本", "owner": "李婶",
                                "known": ["你"], "quote": "只顾着端茶"}])[0]
        self.assertTrue(new["player_knows"])
        self.assertTrue(apply_secret_proposal(self.sess, new, NAMES))
        self.assertEqual(len(self.sess.secrets), 2)
        gone = self.run_filter([{"op": "retire", "secret": 1, "quote": "倒吸了一口凉气"}])[0]
        self.assertTrue(apply_secret_proposal(self.sess, gone, NAMES))
        self.assertEqual([r["content"] for r in self.sess.secrets], ["李婶在偷藏账本"])
        # 目标已被划掉：再点头也不会炸
        self.assertFalse(apply_secret_proposal(self.sess, gone, NAMES))

    def test_prompt_rows_numbered_with_state(self):
        set_secret_stance(self.sess, self.row["id"], 3, "suspects", NAMES)
        rows = secret_rows_for_prompt(self.sess, NPCS)
        self.assertEqual(rows[0]["n"], 1)
        self.assertIn("起疑：韩曼宁", rows[0]["state"])


class SecretInjectionTests(unittest.IsolatedAsyncioTestCase):
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
        self.aunt = RpgNpc(module_id=self.module.id, name="李婶", location="客厅", persona="热心")
        self.db.add_all([self.wife, self.aunt])
        await self.db.commit()
        self.names = {self.wife.id: "韩曼宁", self.aunt.id: "李婶"}
        self.sess = RpgSession(
            module_id=self.module.id, char_name="阿隼", stats={"精力": 100},
            location="客厅", slot="晚", npc_states={}, npc_notes={}, npc_activities={},
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

    async def test_nothing_registered_adds_nothing(self):
        system = await self._system()
        for word in ("你的秘密", "她知道的秘密", "她不知道的事"):
            self.assertNotIn(word, system)

    async def test_player_secret_split_by_who_knows(self):
        add_secret(self.sess, "我其实是通缉犯", 0, [self.wife.id], self.names)
        system = await self._system()
        self.assertIn("你的秘密", system)
        self.assertIn("知情：韩曼宁；其余人不知道", system)
        self.assertEqual(system.count("她知道的秘密"), 1)
        self.assertEqual(system.count("她不知道的事"), 1)
        # 同一句话：【你】一次 + 韩曼宁卡一次 + 李婶卡一次
        self.assertEqual(system.count("我其实是通缉犯"), 3)

    async def test_suspects_and_misled_get_their_own_wording(self):
        row = add_secret(self.sess, "我其实是通缉犯", 0, [], self.names)
        set_secret_stance(self.sess, row["id"], self.wife.id, "suspects", self.names)
        set_secret_stance(self.sess, row["id"], self.aunt.id, "misled", self.names, "他只是个货郎")
        system = await self._system()
        self.assertEqual(system.count("她隐约察觉、但没有证据的事"), 1)
        self.assertEqual(system.count("她深信的是：他只是个货郎"), 1)
        self.assertNotIn("她不知道的事", system)
        self.assertIn("隐约起疑：韩曼宁", system)
        self.assertIn("被骗、信的是假的：李婶", system)

    async def test_npc_secret_hidden_until_player_finds_out(self):
        row = add_secret(self.sess, "她在偷偷还债", self.wife.id, [], self.names, player_knows=False)
        self.assertIn("玩家还不知道，她被问起会遮掩", await self._system())
        edit_secret(self.sess, row["id"], self.names, player_knows=True)
        system = await self._system()
        self.assertIn("她在偷偷还债", system)
        self.assertNotIn("玩家还不知道，她被问起会遮掩", system)


if __name__ == "__main__":
    unittest.main()
