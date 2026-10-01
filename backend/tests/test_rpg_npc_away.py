"""「已离开」：剧情写她走了、没说去哪，她就不在任何地方。

和空串（放她回作息表）不是一回事：她的常驻地点正好就是玩家这儿的时候，
「回作息表」等于原地不动。AWAY 推时段不清、调度不挪，只有剧情写她回来
或者修改器才放她回来。
"""
import unittest

from app.agents.rpg_turn import _place_block
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgLocation, RpgModule, RpgNpc, RpgSession
from app.services.rpg_context import here_npcs, npc_place
from app.services.rpg_state import AWAY, advance_slot, apply_state_delta, apply_tweak


def _npc(npc_id=3, name="赫敏", location="校长办公室", **kwargs):
    return RpgNpc(id=npc_id, module_id=1, name=name, location=location, **kwargs)


def _sess(**kwargs):
    base = {
        "location": "校长办公室", "slot": "中", "day": 1,
        "npc_places": {}, "npc_notes": {}, "npc_states": {}, "npc_followers": [],
        "stats": {}, "inventory": [], "flags": [], "chronicle": [],
    }
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


def _module():
    return RpgModule(id=1, name="魔法学院", time_slots=["早", "中", "晚"],
                     stat_defs=[], relation_stat_defs=[])


class AwayTests(unittest.TestCase):
    def test_away_is_nowhere_even_if_home_is_here(self):
        # 她常驻的就是玩家这儿——写空串只会让她原地不动，AWAY 才真的让她走
        npc = _npc()
        sess = _sess(npc_places={"3": AWAY})
        self.assertEqual(npc_place(npc, sess.slot, sess.npc_places), "")
        self.assertEqual(here_npcs([npc], sess.location, sess.slot, sess.npc_places), [])

    def test_away_beats_following(self):
        npc = _npc()
        sess = _sess(npc_places={"3": AWAY}, npc_followers=[3])
        self.assertEqual(
            npc_place(npc, sess.slot, sess.npc_places, sess.npc_followers, sess.location), "",
        )

    def test_the_story_can_send_her_away_and_she_stops_following(self):
        npc = _npc()
        sess = _sess(npc_followers=[3])
        apply_state_delta(_module(), sess, {"npc_places": {"赫敏": AWAY}}, [npc], move_npcs=[npc])
        self.assertEqual(sess.npc_places, {"3": AWAY})
        self.assertNotIn(3, sess.npc_followers or [])

    def test_advancing_the_slot_keeps_her_away(self):
        # 有作息表的人，普通剧情覆盖推时段会清掉；AWAY 不清
        npc = _npc(slot_locations={"晚": "校长办公室"})
        sess = _sess(npc_places={"3": AWAY})
        advance_slot(_module(), sess, [npc])
        self.assertEqual(sess.slot, "晚")
        self.assertEqual(sess.npc_places, {"3": AWAY})
        self.assertEqual(here_npcs([npc], sess.location, sess.slot, sess.npc_places), [])

    def test_the_story_brings_her_back(self):
        npc = _npc()
        sess = _sess(npc_places={"3": AWAY})
        apply_state_delta(
            _module(), sess, {"npc_places": {"赫敏": "校长办公室"}}, [npc], move_npcs=[npc],
            places=["校长办公室"],
        )
        self.assertEqual(sess.npc_places, {"3": "校长办公室"})
        self.assertEqual(here_npcs([npc], sess.location, sess.slot, sess.npc_places), [npc])

    def test_the_tweak_panel_can_set_away(self):
        npc = _npc()
        sess = _sess(npc_followers=[3])
        notes = apply_tweak(
            _module(), sess, npc_places={"3": AWAY}, npcs=[npc],
            locations=[RpgLocation(module_id=1, name="校长办公室")],
        )
        self.assertEqual(notes, [])
        self.assertEqual(sess.npc_places, {"3": AWAY})
        self.assertNotIn(3, sess.npc_followers or [])

    def test_the_settle_prompt_says_she_is_away_and_how_to_write_it(self):
        npc = _npc()
        sess = _sess(npc_places={"3": AWAY})
        block = _place_block([npc], ["校长办公室"], sess)
        self.assertIn("赫敏 现在在 已离开", block)
        self.assertIn(AWAY, block)


if __name__ == "__main__":
    unittest.main()
