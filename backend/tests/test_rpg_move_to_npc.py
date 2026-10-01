"""「去往赫敏处」：去处是个人，落点是她此刻在哪儿。外加修改器挪主角。"""
import unittest

from app.agents.rpg_turn import parse_company
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgLocation, RpgModule, RpgNpc, RpgSession
from app.services.rpg_state import AWAY, apply_tweak


def _sess(**kwargs):
    base = {
        "location": "家", "slot": "中", "day": 1,
        "npc_places": {"3": "照相馆"}, "npc_notes": {}, "npc_states": {}, "npc_followers": [],
        "stats": {}, "inventory": [], "flags": {}, "chronicle": [], "visited": [],
    }
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


class MoveToNpcTests(unittest.TestCase):
    def setUp(self):
        self.locations = [RpgLocation(module_id=1, name=n) for n in ("家", "照相馆", "药店")]
        self.npcs = [
            RpgNpc(id=3, module_id=1, name="韩曼宁", location="药店"),
            RpgNpc(id=4, module_id=1, name="赫敏", location="家"),
        ]

    def _to(self, content, **kwargs):
        return parse_company(content, self.locations, self.npcs, _sess(**kwargs)).move_to

    def test_going_to_where_the_npc_is(self):
        for content in ("去往韩曼宁处", "去找韩曼宁", "我去曼宁那儿", "到韩曼宁身边去", "去韩曼宁那边看看"):
            with self.subTest(content=content):
                self.assertEqual(self._to(content), "照相馆")

    def test_not_a_move_to_the_npc(self):
        for content in (
            "韩曼宁去照相馆干嘛",   # 问句
            "别去找韩曼宁",          # 否定
            "让赫敏去找韩曼宁",      # 动身的是赫敏
            "去韩曼宁家",            # 另一个地方
            "我想起韩曼宁",          # 没动身
        ):
            with self.subTest(content=content):
                self.assertEqual(self._to(content), "")

    def test_npc_gone_or_already_here(self):
        self.assertEqual(self._to("去找韩曼宁", npc_places={"3": AWAY}), "")
        # 她不在登记地点（照相馆没登记也一样）
        self.assertEqual(self._to("去找韩曼宁", npc_places={"3": "月球"}), "")

    def test_a_registered_place_still_wins(self):
        self.assertEqual(self._to("去药店"), "药店")


class TweakPlayerLocationTests(unittest.TestCase):
    def test_moves_the_player_and_marks_the_scene_break(self):
        module = RpgModule(id=1, name="m", stat_defs=[], relation_stat_defs=[])
        locs = [RpgLocation(module_id=1, name=n) for n in ("家", "照相馆")]
        sess = _sess(scene_break_from="")
        notes = apply_tweak(module, sess, location="照相馆", locations=locs)
        self.assertEqual((notes, sess.location, sess.scene_break_from), ([], "照相馆", "家"))
        self.assertIn("照相馆", sess.visited)
        notes = apply_tweak(module, sess, location="月球", locations=locs)
        self.assertEqual(sess.location, "照相馆")
        self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
