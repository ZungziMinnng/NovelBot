"""RPG 数值系统：定义解析、条件求值、状态应用。

这个模块是整套 RPG 的地基——「数值在动、跨过某条线解锁新东西」全靠它。
两条底线：模型提议的改动一律被 min/max 夹住，定义里没有的键一律拒绝。
AI 给 -999 也只能扣到下界，而且要留一条 warning 让玩家看见。
"""
import unittest

from app.models.rpg import RpgItem, RpgModule, RpgNpc, RpgSession
from app.services.rpg_state import (
    ON_ZERO_DEAD, ON_ZERO_FLAG,
    apply_flags, apply_inventory, apply_npc_notes, apply_relations, apply_state_delta,
    apply_stats, check_condition, check_zero, clamp, def_map, for_check_stats,
    init_relation, init_stats, mark_met, match_npc, note_visited, starting_inventory,
    tier_list, tier_of, visible_defs,
    FLAG_LIMIT, NOTE_CHARS, NOTE_LIMIT, TIER_LABEL_CHARS, TIER_NOTE_CHARS, VISITED_LIMIT,
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
        "npc_notes": {},
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


class TierTests(unittest.TestCase):
    """数值的「影响」分档。

    守的是两件事：存量模组（一个 tiers 都没写）读出来和以前一模一样；
    以及「乱填的表也得匹配到对的那一档」——作者页不强制排序也不强制无重复。
    """

    def test_a_def_without_tiers_yields_nothing(self):
        # 存量模组的回归线：没写过影响的定义必须一个标签都不带
        self.assertIsNone(tier_of({"name": "精力", "max": 100}, 62))
        self.assertEqual(tier_list({"name": "精力", "max": 100}), [])

    def test_malformed_tiers_do_not_raise(self):
        self.assertIsNone(tier_of({"tiers": "冷淡"}, 62))
        self.assertIsNone(tier_of({"tiers": [None, "x", 3]}, 62))

    def test_the_band_is_the_highest_one_at_or_below_the_value(self):
        spec = {"tiers": [
            {"at": 0, "label": "冷淡"}, {"at": 21, "label": "客气"}, {"at": 61, "label": "亲近"},
        ]}
        self.assertEqual(tier_of(spec, 62)["label"], "亲近")
        self.assertEqual(tier_of(spec, 61)["label"], "亲近")
        self.assertEqual(tier_of(spec, 60)["label"], "客气")
        self.assertEqual(tier_of(spec, 0)["label"], "冷淡")

    def test_a_value_below_every_band_gets_no_label(self):
        # 下界是负数、或者作者第一档从 10 起：这时候不该硬塞一个档进去
        spec = {"tiers": [{"at": 10, "label": "有点意思"}]}
        self.assertIsNone(tier_of(spec, 9))
        self.assertEqual(tier_of(spec, 10)["label"], "有点意思")

    def test_bands_filled_in_out_of_order_still_match_correctly(self):
        # 编辑器不强制排序。按填写顺序取「第一个够得上的」会匹配到 0 那一档
        spec = {"tiers": [
            {"at": 61, "label": "亲近"}, {"at": 0, "label": "冷淡"}, {"at": 21, "label": "客气"},
        ]}
        self.assertEqual(tier_of(spec, 62)["label"], "亲近")
        self.assertEqual(tier_of(spec, 30)["label"], "客气")

    def test_one_blank_row_does_not_take_the_whole_table_down(self):
        # 新增一档还没填数字是常态，不能因此整张表失效
        spec = {"tiers": [{"at": 0, "label": "冷淡"}, {"at": "", "label": ""}, {"at": 61, "label": "亲近"}]}
        self.assertEqual(tier_of(spec, 62)["label"], "亲近")
        self.assertEqual(len(tier_list(spec)), 2)

    def test_a_blank_at_is_not_treated_as_zero(self):
        # 0 是个合法的下界。拿 0 兜底的话「还没填」会变成一个永远匹配得上的最低档
        spec = {"tiers": [{"at": "", "label": "还没填"}, {"at": 61, "label": "亲近"}]}
        self.assertEqual(len(tier_list(spec)), 1)
        self.assertIsNone(tier_of(spec, 10))

    def test_labels_and_notes_are_trimmed_here_so_readers_do_not_each_set_a_cap(self):
        spec = {"tiers": [{"at": 0, "label": "冷" * 20, "note": "话" * 50}]}
        got = tier_list(spec)[0]
        self.assertEqual(len(got["label"]), TIER_LABEL_CHARS)
        self.assertEqual(len(got["note"]), TIER_NOTE_CHARS)

    def test_an_uncapped_stat_still_gets_its_band(self):
        # 资金没有 max。分档和 /max 那套逻辑得完全不相干
        self.assertEqual(tier_of({"max": None, "tiers": [{"at": 1000, "label": "阔绰"}]}, 3000)["label"], "阔绰")


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


class TimeConditionTests(unittest.TestCase):
    """时段与天数的门槛。地点入口写「白天才开」、世界书写「鬼只在夜里出来」。"""

    def test_a_listed_slot_passes_and_the_others_do_not(self):
        sess = _sess(slot="晚", day=1, time_slots=["早", "中", "晚"])
        self.assertTrue(check_condition({"slots": ["晚"]}, sess)[0])
        ok, why = check_condition({"slots": ["早", "中"]}, sess)
        self.assertFalse(ok)
        # 原因串直接给玩家看，要带上现在是什么时段，否则他不知道该等多久
        self.assertIn("晚", why)

    def test_a_bang_prefix_means_anything_but_that(self):
        # 与 flags 完全同义，作者和编辑器都不用学新东西
        sess = _sess(slot="晚", day=1, time_slots=["早", "中", "晚"])
        self.assertFalse(check_condition({"slots": ["!晚"]}, sess)[0])
        self.assertTrue(check_condition({"slots": ["!早"]}, sess)[0])

    def test_without_a_clock_the_clause_fails_rather_than_passes(self):
        # 放行会让「只有晚上开」的门永远开着，而作者根本查不出来。
        # 同 relations 分支「名字对不上就算不成立」的理由
        ok, why = check_condition({"slots": ["晚"]}, _sess(slot="", time_slots=[]))
        self.assertFalse(ok)
        self.assertIn("没有设定时段", why)

    def test_day_thresholds_default_to_at_least(self):
        self.assertTrue(check_condition({"day": {"op": ">=", "value": 3}}, _sess(day=3))[0])
        self.assertFalse(check_condition({"day": {"op": ">=", "value": 4}}, _sess(day=3))[0])
        # 不给 op 就是 >=，和 stats 的 rule 一个形状
        self.assertTrue(check_condition({"day": {"value": 3}}, _sess(day=3))[0])
        self.assertTrue(check_condition({"day": {"op": "==", "value": 3}}, _sess(day=3))[0])

    def test_time_and_other_clauses_all_have_to_hold(self):
        sess = _sess(slot="晚", day=1, stats={"精力": 10, "资金": 0})
        cond = {"slots": ["晚"], "stats": {"精力": {"op": ">=", "value": 50}}}
        self.assertFalse(check_condition(cond, sess)[0])


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


class NpcNoteTests(unittest.TestCase):
    """GM 边玩边记的 NPC 近况。自由键值，没有任何一个键是作者定义过的。"""

    def test_a_new_key_appends_and_the_same_key_overwrites(self):
        sess = _sess(npc_notes={"3": {"伤势": "左肩中刀"}})
        apply_npc_notes(sess, 3, {"伤势": "左肩已包扎", "身上带着": "猎枪"})
        self.assertEqual(sess.npc_notes["3"], {"伤势": "左肩已包扎", "身上带着": "猎枪"})

    def test_null_removes_one_note_and_leaves_the_others_alone(self):
        sess = _sess(npc_notes={"3": {"伤势": "左肩中刀", "会": "开锁"}})
        apply_npc_notes(sess, 3, {"伤势": None})
        self.assertEqual(sess.npc_notes["3"], {"会": "开锁"})

    def test_a_refreshed_note_survives_the_cap_because_it_moves_to_the_end(self):
        # 这条用例锁的是「别照抄 apply_flags 的淘汰规则」：dict 重新赋值不挪位置，
        # 于是每轮都在刷新的「伤势」会永远停在下标 0，先被砍的正是唯一要紧的那条
        sess = _sess(npc_notes={"3": {"伤势": "左肩中刀", **{f"杂{i}": "x" for i in range(NOTE_LIMIT - 1)}}})
        apply_npc_notes(sess, 3, {"伤势": "开始发炎", "刚记的": "y"})
        self.assertIn("伤势", sess.npc_notes["3"])
        self.assertNotIn("杂0", sess.npc_notes["3"])
        self.assertEqual(len(sess.npc_notes["3"]), NOTE_LIMIT)

    def test_the_oldest_untouched_note_is_dropped_past_the_limit(self):
        sess = _sess(npc_notes={"3": {f"旧{i}": "x" for i in range(NOTE_LIMIT)}})
        warnings = apply_npc_notes(sess, 3, {"最新的一条": "y"})
        self.assertEqual(len(sess.npc_notes["3"]), NOTE_LIMIT)
        self.assertIn("最新的一条", sess.npc_notes["3"])
        self.assertNotIn("旧0", sess.npc_notes["3"])
        self.assertTrue(warnings)

    def test_a_value_that_is_not_a_string_is_flattened_rather_than_stored_raw(self):
        # 裸字典交给 React 当子节点会把整页白屏，NpcSheet 上面没有 error boundary
        sess = _sess()
        apply_npc_notes(sess, 3, {"伤势": ["左肩", "右腿"], "来历": {"村子": "北边"}})
        for value in sess.npc_notes["3"].values():
            self.assertIsInstance(value, str)

    def test_an_over_long_value_is_trimmed_instead_of_dropped(self):
        sess = _sess()
        apply_npc_notes(sess, 3, {"来历": "很长的故事" * 50})
        self.assertLessEqual(len(sess.npc_notes["3"]["来历"]), NOTE_CHARS + 1)

    def test_two_npcs_keep_their_own_notes(self):
        sess = _sess(npc_notes={"3": {"伤势": "左肩中刀"}})
        apply_npc_notes(sess, 4, {"伤势": "毫发无伤"})
        self.assertEqual(sess.npc_notes["3"]["伤势"], "左肩中刀")
        self.assertEqual(sess.npc_notes["4"]["伤势"], "毫发无伤")

    def test_a_null_table_clears_that_person_entirely(self):
        sess = _sess(npc_notes={"3": {"伤势": "左肩中刀"}, "4": {"会": "开锁"}})
        apply_npc_notes(sess, 3, None)
        self.assertNotIn("3", sess.npc_notes)
        self.assertIn("4", sess.npc_notes)

    def test_a_malformed_table_warns_instead_of_swallowing_it(self):
        sess = _sess()
        self.assertTrue(apply_npc_notes(sess, 3, "这不是字典"))


class StartingInventoryTests(unittest.TestCase):
    """开局背包 = 模组的开局背包 + 定义里勾了「开局就有」的道具。

    这一条接的就是「在模组页定义好了道具，开局身上却什么都没有」。两边都不加
    的话，作者定义的道具和玩家背包之间没有任何桥，只能靠 GM 每局现编一件。
    """

    @staticmethod
    def _item(name, start_with=True):
        return RpgItem(module_id=1, name=name, start_with=start_with)

    def test_a_module_with_neither_source_starts_empty(self):
        """存量模组的回归线：没有开局背包、没有勾过的道具，就是空手开局。"""
        self.assertEqual(starting_inventory(_module(), []), [])

    def test_a_flagged_item_lands_in_the_bag(self):
        bag = starting_inventory(_module(), [self._item("铁钥匙")])
        self.assertEqual([row["name"] for row in bag], ["铁钥匙"])
        self.assertEqual(bag[0]["qty"], 1)

    def test_an_unflagged_item_stays_out(self):
        """没勾的不进背包——不然「开局就有」这个勾等于没有。"""
        self.assertEqual(starting_inventory(_module(), [self._item("龙鳞", False)]), [])

    def test_the_kit_and_the_flags_are_added_together(self):
        """两边合起来而不是二选一：作者会拿开局背包放剧情道具、拿勾放补给。"""
        module = _module(default_inventory=[{"name": "母亲的遗物", "qty": 1}])
        bag = starting_inventory(module, [self._item("铁钥匙")])
        self.assertEqual([row["name"] for row in bag], ["母亲的遗物", "铁钥匙"])

    def test_the_same_item_written_two_ways_is_one_row(self):
        """撞名时开局背包那份赢：它写了数量，比定义默认的一件更具体。

        没有这条的话，定义里写「治伤药水」、开局背包里写「治伤药水 」（粘贴时
        带了个空格）会给玩家并排显示两条一样的，数量还是分开算的。
        """
        module = _module(default_inventory=[{"name": "治伤药水 ", "qty": 3}])
        bag = starting_inventory(module, [self._item("治伤药水")])
        self.assertEqual(len(bag), 1)
        self.assertEqual(bag[0]["qty"], 3)
        self.assertEqual(bag[0]["name"], "治伤药水")

    def test_a_row_without_a_name_is_skipped(self):
        """空名字的行丢掉：背包里会出现一个点不动的空条。"""
        module = _module(default_inventory=[{"name": "  "}, {"name": "火把", "qty": 1}, "烂数据"])
        bag = starting_inventory(module, [self._item(""), self._item("铁钥匙")])
        self.assertEqual([row["name"] for row in bag], ["火把", "铁钥匙"])

    def test_a_hand_written_row_keeps_its_note_and_a_derived_one_does_not_get_one(self):
        """开局背包那行是作者手写的，note 要原样带走；定义来的那件不伪造 note，
        侧栏显示说明时本来就先看定义里的 description（比这儿能写的长）。"""
        module = _module(default_inventory=[{"name": "火把", "qty": 1, "note": "还在烧"}])
        bag = starting_inventory(module, [self._item("铁钥匙")])
        self.assertEqual(bag[0]["note"], "还在烧")
        self.assertEqual(bag[1]["note"], "")


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

    def test_notes_are_addressed_by_name_because_the_model_cannot_hold_ids(self):
        apply_state_delta(
            self.module, self.sess, {"npc_notes": {"赫 敏": {"伤势": "左肩中刀"}}}, self.npcs,
        )
        self.assertEqual(self.sess.npc_notes["3"]["伤势"], "左肩中刀")

    def test_an_unknown_name_warns_without_losing_the_rest_of_the_turn(self):
        warnings = apply_state_delta(self.module, self.sess, {
            "stats": {"精力": -5},
            "npc_notes": {"谁啊": {"伤势": "左肩中刀"}},
        }, self.npcs)
        self.assertEqual(self.sess.stats["精力"], 95)
        self.assertTrue(any("谁啊" in w for w in warnings))

    def test_a_malformed_note_table_does_not_take_the_relations_down_with_it(self):
        warnings = apply_state_delta(self.module, self.sess, {
            "relations": {"赫敏": {"好感": 2}},
            "npc_notes": {"赫敏": "这不是字典"},
        }, self.npcs)
        self.assertEqual(self.sess.npc_states["3"]["好感"], 2)
        self.assertTrue(warnings)

    def test_notes_for_someone_who_is_not_in_the_scene_are_refused_with_a_warning(self):
        # 剧情里随口提一句「赫敏」不该让隔壁镇的她凭空多出一条伤：
        # 近况是长期事实，会一直画在角色卡上、每轮注入她的设定块
        warnings = apply_state_delta(
            self.module, self.sess, {"npc_notes": {"赫敏": {"伤势": "左肩中刀"}}},
            self.npcs, note_npcs=[],
        )
        self.assertEqual(self.sess.npc_notes, {})
        self.assertTrue(any("赫敏" in w for w in warnings))

    def test_garbage_delta_is_ignored(self):
        self.assertEqual(apply_state_delta(self.module, self.sess, None), [])
        self.assertEqual(apply_state_delta(self.module, self.sess, "什么都不是"), [])

    def test_staying_put_leaves_the_location_alone(self):
        self.sess.location = "地窖"
        apply_state_delta(self.module, self.sess, {"location": "  "})
        self.assertEqual(self.sess.location, "地窖")

    def test_the_model_moving_you_lights_up_where_you_landed(self):
        apply_state_delta(self.module, self.sess, {"location": "地窖"})
        self.assertEqual(self.sess.visited, ["地窖"])

    def test_staying_put_does_not_touch_the_fog(self):
        self.sess.visited = ["出租屋"]
        apply_state_delta(self.module, self.sess, {"location": "  "})
        self.assertEqual(self.sess.visited, ["出租屋"])


class VisitedTests(unittest.TestCase):
    """去过哪儿。地图的迷雾就靠这一张名单散开。"""

    def test_the_first_visit_is_recorded_and_a_second_one_does_not_duplicate_it(self):
        sess = _sess()
        note_visited(sess, "魔法商店")
        note_visited(sess, "魔法商店")
        self.assertEqual(sess.visited, ["魔法商店"])

    def test_a_sloppily_spaced_name_is_the_same_place(self):
        # 模型写「魔法 商店」很常见，不归一化就会同一个地方记两遍
        sess = _sess(visited=["魔法商店"])
        note_visited(sess, " 魔法 商店 ")
        self.assertEqual(len(sess.visited), 1)

    def test_the_list_is_reassigned_so_the_json_column_goes_dirty(self):
        # 原地 append 不会被 SQLAlchemy 标脏，那样走完一步刷新页面迷雾就回去了
        sess = _sess(visited=["出租屋"])
        before = sess.visited
        note_visited(sess, "地窖")
        self.assertIsNot(sess.visited, before)

    def test_the_place_you_have_not_been_back_to_is_the_one_that_falls_off(self):
        # 结算模型能把你「移动」到任何一个它现编的地名上，所以有上限。
        # 淘汰的必须是最久没回去的那个——起点那个镇子不该被现编的地名挤掉
        sess = _sess(visited=["起点镇"])
        for i in range(VISITED_LIMIT):
            note_visited(sess, f"野地{i}")
        self.assertEqual(len(sess.visited), VISITED_LIMIT)
        self.assertNotIn("起点镇", sess.visited)

        sess = _sess(visited=["起点镇"])
        for i in range(VISITED_LIMIT - 1):
            note_visited(sess, f"野地{i}")
            note_visited(sess, "起点镇")     # 每次都回家
        self.assertIn("起点镇", sess.visited)

    def test_a_blank_name_is_not_recorded(self):
        sess = _sess(visited=["出租屋"])
        note_visited(sess, "  ")
        note_visited(sess, None)
        self.assertEqual(sess.visited, ["出租屋"])


class MatchNpcTests(unittest.TestCase):
    """按名字找人。模型只会写「赫敏」，作者填的是「赫敏格兰杰」。

    放宽的底线是**宁可认不出，不能认错人**：认不出只是这一条改动落空加一条
    warning，认错人会把好感加到别人头上，而且没人看得出来。
    """

    def setUp(self):
        self.hermione = RpgNpc(id=3, module_id=1, name="赫敏格兰杰")
        self.ron = RpgNpc(id=4, module_id=1, name="罗恩韦斯莱")

    def test_the_full_name_matches(self):
        self.assertIs(match_npc("赫敏格兰杰", [self.hermione, self.ron]), self.hermione)

    def test_the_given_name_alone_matches(self):
        self.assertIs(match_npc("赫敏", [self.hermione, self.ron]), self.hermione)

    def test_the_family_name_alone_matches(self):
        self.assertIs(match_npc("格兰杰", [self.hermione, self.ron]), self.hermione)

    def test_a_separator_in_the_middle_does_not_break_it(self):
        self.assertIs(match_npc("赫敏·格兰杰", [self.hermione, self.ron]), self.hermione)
        author = RpgNpc(id=5, module_id=1, name="赫敏·格兰杰")
        self.assertIs(match_npc("赫敏格兰杰", [author]), author)

    def test_two_people_who_both_fit_match_nobody(self):
        a = RpgNpc(id=6, module_id=1, name="村民甲")
        b = RpgNpc(id=7, module_id=1, name="村民乙")
        self.assertIsNone(match_npc("村民", [a, b]))

    def test_one_character_is_too_short_to_guess_from(self):
        li = RpgNpc(id=8, module_id=1, name="李铁柱")
        self.assertIsNone(match_npc("李", [li]))

    def test_an_unrelated_name_does_not_match(self):
        self.assertIsNone(match_npc("哈利", [self.hermione, self.ron]))

    def test_a_blank_name_does_not_match(self):
        self.assertIsNone(match_npc("  ", [self.hermione]))
        self.assertIsNone(match_npc("·", [self.hermione]))


if __name__ == "__main__":
    unittest.main()
