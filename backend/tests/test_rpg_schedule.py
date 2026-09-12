"""角色的作息表：把「这个人在哪儿」按时段取。

这一批改的是「在场」的**取值方式**，不是再加一条在场规则。所以这里钉两件事：

1. 有时段、表里有值 → 按表走；
2. 没时段、表里没这个时段、表本身是空的 → 落回常驻地点，和加这个功能之前
   逐字一致。老库拿到 '{}'，行为必须一个字节都不变。

认错人的代价和 match_npc 那条一样高：把不在场的人当在场，他的外貌会被标成
「已见过」，之后再也不注入；反过来则是一个明明站在跟前的人不进提示词。
"""
import unittest

from app.models.rpg import RpgNpc
from app.services.rpg_context import here_npcs, npc_place, onstage_npcs, world_npcs


def _npc(npc_id=1, name="赫敏", location="格兰芬多塔", **kwargs):
    return RpgNpc(id=npc_id, module_id=1, name=name, location=location, **kwargs)


class NpcPlaceTests(unittest.TestCase):
    def test_no_schedule_falls_back_to_the_home_location(self):
        npc = _npc(slot_locations={})
        self.assertEqual(npc_place(npc, "早"), "格兰芬多塔")
        self.assertEqual(npc_place(npc, ""), "格兰芬多塔")

    def test_a_scheduled_slot_wins(self):
        npc = _npc(slot_locations={"早": "大礼堂", "晚": "寝室"})
        self.assertEqual(npc_place(npc, "早"), "大礼堂")
        self.assertEqual(npc_place(npc, "晚"), "寝室")

    def test_a_slot_missing_from_the_table_falls_back(self):
        npc = _npc(slot_locations={"早": "大礼堂"})
        self.assertEqual(npc_place(npc, "中"), "格兰芬多塔")

    def test_a_blank_entry_falls_back(self):
        # 作者把某一格清空了，等于没写，不该变成「这个人不存在」
        npc = _npc(slot_locations={"早": "   "})
        self.assertEqual(npc_place(npc, "早"), "格兰芬多塔")

    def test_no_slot_means_the_table_is_not_consulted(self):
        # 模组没设时段时 sess.slot 是空串。这时作息表整个不参与——
        # 不这么办的话，一个从没配过时钟的模组会因为角色卡里填过一栏而改变行为
        npc = _npc(slot_locations={"早": "大礼堂"})
        self.assertEqual(npc_place(npc, ""), "格兰芬多塔")

    def test_a_non_dict_slot_locations_does_not_explode(self):
        # 老库、手改过的库、或者迁移之前写坏的值
        npc = _npc()
        npc.slot_locations = None
        self.assertEqual(npc_place(npc, "早"), "格兰芬多塔")

    def test_a_home_less_npc_lives_off_the_table_alone(self):
        # 没有固定落脚点的人（学生、行商）：常驻地点留空、每一格都填。
        # 常驻地点是「这一格没填」的替补，全填满就一次都不会读到它——
        # 界面提示里那句「常驻地点空着没关系」按的就是这条
        npc = _npc(location="", slot_locations={"早": "大礼堂", "中": "图书馆", "晚": "公共休息室"})
        for slot, at in (("早", "大礼堂"), ("中", "图书馆"), ("晚", "公共休息室")):
            with self.subTest(slot=slot):
                self.assertEqual(npc_place(npc, slot), at)

    def test_a_gap_leaves_a_home_less_npc_nowhere(self):
        # 常驻地点空着又漏了一格，那一格她哪儿都不是：侧栏不出现、也不算在场。
        # 不是「留在上一个时段的地方」——作息表没有记忆
        npc = _npc(location="", slot_locations={"早": "大礼堂"})
        self.assertEqual(npc_place(npc, "中"), "")

    def test_slot_names_are_trimmed_not_lowercased(self):
        # 时段名是作者自己写的，只去首尾空格、不做 norm——slot_table 和
        # advance_slot 也是这么比的，三处必须一致
        npc = _npc(slot_locations={"早": "大礼堂"})
        self.assertEqual(npc_place(npc, " 早 "), "大礼堂")


class HereNpcsTests(unittest.TestCase):
    """here_npcs 是「在场」唯一的那一份定义，作息表必须在这里生效。"""

    def test_a_scheduled_npc_is_here(self):
        npc = _npc(slot_locations={"晚": "校长办公室"})
        self.assertEqual(here_npcs([npc], "校长办公室", "晚"), [npc])
        self.assertEqual(here_npcs([npc], "格兰芬多塔", "晚"), [])

    def test_without_a_slot_the_home_location_still_rules(self):
        npc = _npc(slot_locations={"晚": "校长办公室"})
        self.assertEqual(here_npcs([npc], "格兰芬多塔", ""), [npc])
        self.assertEqual(here_npcs([npc], "校长办公室", ""), [])

    def test_an_empty_location_is_still_nobody(self):
        npc = _npc(slot_locations={"晚": "校长办公室"})
        self.assertEqual(here_npcs([npc], "", "晚"), [])

    def test_the_protagonist_template_never_counts(self):
        npc = _npc(role="protagonist", slot_locations={"晚": "校长办公室"})
        self.assertEqual(here_npcs([npc], "校长办公室", "晚"), [])
        self.assertEqual(world_npcs([npc]), [])


class OnstageNpcsTests(unittest.TestCase):
    def test_a_scheduled_npc_is_onstage(self):
        npc = _npc(slot_locations={"晚": "校长办公室"})
        self.assertEqual(onstage_npcs([npc], "校长办公室", "", "晚"), [npc])

    def test_someone_away_but_mentioned_is_still_injected(self):
        # 「注入」和「在场」是两件事，作息表只动前者的名单来源，不动这条底线
        npc = _npc(
            slot_locations={"晚": "校长办公室"}, keywords="万事通",
        )
        self.assertEqual(onstage_npcs([npc], "地窖", "赫敏说过什么", "晚"), [npc])
        self.assertEqual(onstage_npcs([npc], "地窖", "万事通呢", "晚"), [npc])
        self.assertEqual(onstage_npcs([npc], "地窖", "没人提他", "晚"), [])


if __name__ == "__main__":
    unittest.main()
