"""RPG 数值系统：定义解析、条件求值、状态应用。

这个模块是整套 RPG 的地基——「数值在动、跨过某条线解锁新东西」全靠它。
两条底线：模型提议的改动一律被 min/max 夹住，定义里没有的键一律拒绝。
AI 给 -999 也只能扣到下界，而且要留一条 warning 让玩家看见。
"""
import unittest

from app.models.rpg import RpgModule, RpgNpc, RpgSession
from app.services.rpg_state import (
    ON_ZERO_DEAD, ON_ZERO_FLAG,
    apply_flags, apply_inventory, apply_relations, apply_state_delta, apply_stats,
    check_condition, check_zero, clamp, def_map, for_check_stats, init_relation,
    init_stats, mark_met, visible_defs, FLAG_LIMIT,
)

STAT_DEFS = [
    {"name": "精力", "initial": 100, "min": 0, "max": 100, "for_check": True, "display": "条"},
    {"name": "资金", "initial": 300, "min": 0, "max": None, "display": "数字"},
    {"name": "怀疑度", "initial": 0, "min": 0, "max": 100, "display": "隐藏"},
]
RELATION_DEFS = [
    {"name": "好感", "initial": 0, "min": -100, "max": 100},
    {"name": "信任", "initial": 10, "min": 0, "max": 100},
]


def _module(**kwargs):
    base = {"stat_defs": STAT_DEFS, "relation_stat_defs": RELATION_DEFS}
    base.update(kwargs)
    return RpgModule(user_id=1, name="测试模组", **base)


def _sess(**kwargs):
    base = {
        "stats": init_stats(STAT_DEFS),
        "inventory": [],
        "flags": {},
        "npc_states": {},
        "location": "",
        "status": "alive",
    }
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


class DefTests(unittest.TestCase):
    def test_def_map_drops_nameless_rows_instead_of_raising(self):
        # 模组作者填一半就去开局是很正常的事
        defs = [{"name": "精力"}, {"initial": 5}, "不是字典", {"name": "  "}]
        self.assertEqual(list(def_map(defs)), ["精力"])

    def test_init_stats_clamps_the_authors_own_numbers(self):
        stats = init_stats([{"name": "精力", "initial": 999, "max": 100}])
        self.assertEqual(stats, {"精力": 100})

    def test_no_max_means_no_ceiling(self):
        self.assertEqual(clamp({"min": 0, "max": None}, 999999), 999999)

    def test_for_check_filters_out_money(self):
        self.assertEqual(for_check_stats(STAT_DEFS), ["精力"])

    def test_hidden_stats_stay_out_of_the_panel(self):
        self.assertEqual([d["name"] for d in visible_defs(STAT_DEFS)], ["精力", "资金"])


class RelationInitTests(unittest.TestCase):
    def test_every_character_gets_their_own_copy(self):
        self.assertEqual(init_relation(RELATION_DEFS), {"好感": 0, "信任": 10})

    def test_a_character_can_override_the_starting_point(self):
        # 青梅竹马开局好感就该比陌生人高
        got = init_relation(RELATION_DEFS, {"好感": 40})
        self.assertEqual(got, {"好感": 40, "信任": 10})

    def test_overrides_outside_the_definition_do_not_come_back(self):
        # 模组改了定义之后，角色卡上的旧键不该复活
        got = init_relation(RELATION_DEFS, {"好感": 40, "羞耻": 80})
        self.assertNotIn("羞耻", got)

    def test_overrides_are_clamped_too(self):
        self.assertEqual(init_relation(RELATION_DEFS, {"好感": 999})["好感"], 100)


class ConditionTests(unittest.TestCase):
    """一处写完三处共用：世界书 / 动作按钮 / 地点入口。"""

    def setUp(self):
        self.sess = _sess(
            stats={"精力": 30, "资金": 300},
            flags={"已经拿到钥匙": True},
            inventory=[{"name": "铁 钥匙", "qty": 1}],
            npc_states={"3": {"好感": 62}},
        )
        self.npcs = [RpgNpc(id=3, module_id=1, name="赫敏")]

    def test_empty_condition_always_passes(self):
        for cond in (None, {}, "不是字典"):
            self.assertTrue(check_condition(cond, self.sess)[0])

    def test_stat_thresholds(self):
        self.assertTrue(check_condition({"stats": {"精力": {"op": ">=", "value": 20}}}, self.sess)[0])
        ok, why = check_condition({"stats": {"精力": {"op": ">=", "value": 50}}}, self.sess)
        self.assertFalse(ok)
        # 原因串直接给玩家看，所以要是人话
        self.assertIn("精力", why)
        self.assertIn("30", why)

    def test_all_clauses_must_hold(self):
        # 语义唯一：条件是附加约束，列出来的每一条都要满足
        cond = {
            "stats": {"精力": {"op": ">=", "value": 20}},
            "flags": ["从没立过的旗"],
        }
        self.assertFalse(check_condition(cond, self.sess)[0])

    def test_relation_thresholds_read_that_characters_own_numbers(self):
        cond = {"relations": [{"npc": "赫敏", "stat": "好感", "op": ">=", "value": 50}]}
        self.assertTrue(check_condition(cond, self.sess, self.npcs)[0])
        cond["relations"][0]["value"] = 80
        self.assertFalse(check_condition(cond, self.sess, self.npcs)[0])

    def test_a_misspelled_character_name_fails_loudly(self):
        # 静默放行会让这条词条每轮都注入，比直接不生效难查得多
        cond = {"relations": [{"npc": "赫米昂", "stat": "好感", "op": ">=", "value": 1}]}
        ok, why = check_condition(cond, self.sess, self.npcs)
        self.assertFalse(ok)
        self.assertIn("找不到角色", why)

    def test_flag_negation(self):
        self.assertTrue(check_condition({"flags": ["已经拿到钥匙"]}, self.sess)[0])
        self.assertFalse(check_condition({"flags": ["!已经拿到钥匙"]}, self.sess)[0])
        self.assertTrue(check_condition({"flags": ["!门已经开了"]}, self.sess)[0])

    def test_item_match_ignores_spacing(self):
        # 模型写「铁 钥匙」很常见
        self.assertTrue(check_condition({"items": ["铁钥匙"]}, self.sess)[0])
        ok, why = check_condition({"items": ["撬棍"]}, self.sess)
        self.assertFalse(ok)
        self.assertIn("撬棍", why)


class ApplyStatsTests(unittest.TestCase):
    def test_a_hostile_number_is_clamped_and_reported(self):
        module, sess = _module(), _sess()
        warnings = apply_stats(module, sess, {"精力": -999})
        self.assertEqual(sess.stats["精力"], 0)
        self.assertTrue(warnings)
        self.assertIn("0", warnings[0])

    def test_the_ceiling_holds_too(self):
        module, sess = _module(), _sess(stats={"精力": 90})
        apply_stats(module, sess, {"精力": 50})
        self.assertEqual(sess.stats["精力"], 100)

    def test_an_invented_stat_is_refused_not_silently_added(self):
        # 模型很爱自创「疲劳度」
        module, sess = _module(), _sess()
        warnings = apply_stats(module, sess, {"疲劳度": -10})
        self.assertNotIn("疲劳度", sess.stats)
        self.assertIn("疲劳度", warnings[0])

    def test_uncapped_stats_grow_freely(self):
        module, sess = _module(), _sess()
        apply_stats(module, sess, {"资金": 100000})
        self.assertEqual(sess.stats["资金"], 100300)


class ApplyRelationsTests(unittest.TestCase):
    def test_two_characters_move_independently(self):
        module = _module()
        sess = _sess(npc_states={
            "1": init_relation(RELATION_DEFS), "2": init_relation(RELATION_DEFS)
        })
        apply_relations(module, sess, 1, {"好感": 5})
        self.assertEqual(sess.npc_states["1"]["好感"], 5)
        self.assertEqual(sess.npc_states["2"]["好感"], 0)

    def test_negative_floor_is_the_definitions_own(self):
        module, sess = _module(), _sess(npc_states={"1": {"好感": -95}})
        apply_relations(module, sess, 1, {"好感": -50})
        self.assertEqual(sess.npc_states["1"]["好感"], -100)

    def test_met_survives_a_relation_change(self):
        module, sess = _module(), _sess(npc_states={"1": {"met": True, "好感": 0}})
        apply_relations(module, sess, 1, {"好感": 3})
        self.assertTrue(sess.npc_states["1"]["met"])


class MarkMetTests(unittest.TestCase):
    def test_marks_only_what_is_new(self):
        sess = _sess(npc_states={"1": {"met": True}})
        mark_met(sess, [1, 2])
        self.assertTrue(sess.npc_states["2"]["met"])


class InventoryTests(unittest.TestCase):
    def test_same_item_merges_across_sloppy_spacing(self):
        sess = _sess(inventory=[{"name": "铁钥匙", "qty": 1}])
        apply_inventory(sess, [{"name": "铁 钥匙", "qty": 2}])
        self.assertEqual(len(sess.inventory), 1)
        self.assertEqual(sess.inventory[0]["qty"], 3)

    def test_running_out_removes_the_row(self):
        sess = _sess(inventory=[{"name": "火把", "qty": 1}])
        apply_inventory(sess, [{"name": "火把", "qty": -1}])
        self.assertEqual(sess.inventory, [])

    def test_spending_what_you_do_not_have_warns(self):
        sess = _sess()
        warnings = apply_inventory(sess, [{"name": "火把", "qty": -1}])
        self.assertEqual(sess.inventory, [])
        self.assertIn("火把", warnings[0])

    def test_note_rides_along_on_pickup(self):
        sess = _sess()
        apply_inventory(sess, [{"name": "铁钥匙", "qty": 1, "note": "沾着锈"}])
        self.assertEqual(sess.inventory[0]["note"], "沾着锈")


class FlagTests(unittest.TestCase):
    def test_null_deletes_and_new_keys_append(self):
        sess = _sess(flags={"门开着": True})
        apply_flags(sess, {"门开着": None, "火把还亮着": True})
        self.assertEqual(sess.flags, {"火把还亮着": True})

    def test_the_oldest_flags_are_dropped_past_the_limit(self):
        # 模型很爱往里塞「刚刚打了个喷嚏」这种一次性状态
        sess = _sess(flags={f"旧{i}": True for i in range(FLAG_LIMIT)})
        warnings = apply_flags(sess, {"最新的一条": True})
        self.assertEqual(len(sess.flags), FLAG_LIMIT)
        self.assertIn("最新的一条", sess.flags)
        self.assertNotIn("旧0", sess.flags)
        self.assertTrue(warnings)


class ZeroTests(unittest.TestCase):
    def test_zero_can_end_the_run(self):
        module = _module(stat_defs=[{"name": "生命", "max": 100, "on_zero": ON_ZERO_DEAD}])
        sess = _sess(stats={"生命": 0})
        notes = check_zero(module, sess)
        self.assertEqual(sess.status, "dead")
        self.assertTrue(notes)

    def test_zero_can_just_raise_a_flag_for_the_story_to_pick_up(self):
        module = _module(stat_defs=[{"name": "精力", "max": 100, "on_zero": ON_ZERO_FLAG}])
        sess = _sess(stats={"精力": 0})
        check_zero(module, sess)
        self.assertTrue(sess.flags["精力耗尽"])
        self.assertEqual(sess.status, "alive")

    def test_the_flag_is_only_raised_once(self):
        module = _module(stat_defs=[{"name": "精力", "max": 100, "on_zero": ON_ZERO_FLAG}])
        sess = _sess(stats={"精力": 0})
        check_zero(module, sess)
        self.assertEqual(check_zero(module, sess), [])


class ApplyDeltaTests(unittest.TestCase):
    """模型提议的一整份改动。相互之间不能拖累。"""

    def setUp(self):
        self.module = _module()
        self.sess = _sess(npc_states={"3": init_relation(RELATION_DEFS)})
        self.npcs = [RpgNpc(id=3, module_id=1, name="赫敏")]

    def test_a_whole_turn_lands(self):
        warnings = apply_state_delta(self.module, self.sess, {
            "stats": {"精力": -20, "资金": 50},
            "relations": {"赫敏": {"好感": 3}},
            "inventory": [{"name": "铁钥匙", "qty": 1}],
            "flags": {"地窖门已开": True},
            "location": "地窖",
        }, self.npcs)
        self.assertEqual(warnings, [])
        self.assertEqual(self.sess.stats, {"精力": 80, "资金": 350, "怀疑度": 0})
        self.assertEqual(self.sess.npc_states["3"]["好感"], 3)
        self.assertEqual(self.sess.inventory[0]["name"], "铁钥匙")
        self.assertEqual(self.sess.location, "地窖")

    def test_relations_are_addressed_by_name_because_the_model_cannot_hold_ids(self):
        apply_state_delta(self.module, self.sess, {"relations": {"赫 敏": {"好感": 2}}}, self.npcs)
        self.assertEqual(self.sess.npc_states["3"]["好感"], 2)

    def test_an_unknown_character_warns_without_losing_the_rest(self):
        warnings = apply_state_delta(self.module, self.sess, {
            "stats": {"精力": -5},
            "relations": {"谁啊": {"好感": 2}},
        }, self.npcs)
        self.assertEqual(self.sess.stats["精力"], 95)
        self.assertIn("谁啊", warnings[0])

    def test_a_malformed_backpack_does_not_take_the_stats_down_with_it(self):
        warnings = apply_state_delta(self.module, self.sess, {
            "stats": {"精力": -5},
            "inventory": "这不是列表",
        })
        self.assertEqual(self.sess.stats["精力"], 95)
        self.assertTrue(any("背包" in w for w in warnings))

    def test_garbage_delta_is_ignored(self):
        self.assertEqual(apply_state_delta(self.module, self.sess, None), [])
        self.assertEqual(apply_state_delta(self.module, self.sess, "什么都不是"), [])

    def test_staying_put_leaves_the_location_alone(self):
        self.sess.location = "地窖"
        apply_state_delta(self.module, self.sess, {"location": "  "})
        self.assertEqual(self.sess.location, "地窖")


if __name__ == "__main__":
    unittest.main()
