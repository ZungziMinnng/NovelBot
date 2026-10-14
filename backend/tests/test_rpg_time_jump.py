"""时间跳转：N 天后的哪个时段。只往后、跨天只结算一次、起跳点留给下一轮。"""
import unittest

from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgModule, RpgSession
from app.services.rpg_context import time_jump_block
from app.services.rpg_state import init_stats, jump_time

STAT_DEFS = [
    {"name": "精力", "initial": 100, "min": 0, "max": 100, "display": "条", "reset_daily": True},
]


def _module():
    return RpgModule(user_id=1, name="测试模组", stat_defs=STAT_DEFS, relation_stat_defs=[])


def _sess(**kwargs):
    base = {
        "stats": init_stats(STAT_DEFS), "time_slots": ["早", "中", "晚"],
        "slot": "早", "day": 1, "status": "alive",
    }
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


class JumpTimeTests(unittest.TestCase):
    def test_same_day_later_slot(self):
        sess = _sess()
        facts = jump_time(_module(), sess, days=0, slot="晚")
        self.assertEqual((sess.day, sess.slot), (1, "晚"))
        self.assertTrue(facts)
        self.assertEqual(sess.time_jump_from, "第 1 天 · 早")

    def test_same_day_not_later_is_rejected_and_changes_nothing(self):
        sess = _sess(slot="中")
        for slot in ("早", "中"):
            self.assertEqual(jump_time(_module(), sess, days=0, slot=slot), [])
        self.assertEqual((sess.day, sess.slot), (1, "中"))
        self.assertEqual(sess.time_jump_from or "", "")

    def test_days_later_any_slot_including_earlier_one(self):
        sess = _sess(slot="晚")
        jump_time(_module(), sess, days=3, slot="早")
        self.assertEqual((sess.day, sess.slot), (4, "早"))

    def test_bad_slot_and_out_of_range_days_are_rejected(self):
        sess = _sess()
        self.assertEqual(jump_time(_module(), sess, days=1, slot="子时"), [])
        self.assertEqual(jump_time(_module(), sess, days=31, slot="早"), [])
        self.assertEqual(jump_time(_module(), sess, days=-1, slot="早"), [])
        self.assertEqual((sess.day, sess.slot), (1, "早"))

    def test_no_clock_does_nothing(self):
        sess = _sess(time_slots=[], slot="")
        self.assertEqual(jump_time(RpgModule(user_id=1, name="x", stat_defs=[], relation_stat_defs=[]),
                                   sess, days=1, slot="早"), [])

    def test_multi_day_recovers_stats_once(self):
        sess = _sess()
        sess.stats = {"精力": 10}
        facts = jump_time(_module(), sess, days=5, slot="中")
        self.assertEqual(sess.stats["精力"], 70)
        self.assertEqual(sum("跨天恢复" in f for f in facts), 1)

    def test_jumping_from_the_last_slot_does_not_settle_twice(self):
        # advance_slot 那一格自己会跨天并恢复一次，跳转不能再补第二次
        sess = _sess(slot="晚")
        sess.stats = {"精力": 10}
        facts = jump_time(_module(), sess, days=2, slot="早")
        self.assertEqual((sess.day, sess.slot), (3, "早"))
        self.assertEqual(sum("跨天恢复" in f for f in facts), 1)

    def test_counters_reset_and_next_turn_is_told_about_the_jump(self):
        sess = _sess(slot_actions=2, slot_chats=3)
        jump_time(_module(), sess, days=2, slot="晚")
        self.assertEqual((sess.slot_actions, sess.slot_chats), (0, 0))
        block = time_jump_block(sess)
        self.assertIn("第 1 天 · 早", block)
        self.assertIn("第 3 天 · 晚", block)


if __name__ == "__main__":
    unittest.main()
