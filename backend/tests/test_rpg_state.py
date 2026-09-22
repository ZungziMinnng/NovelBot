"""RPG 数值系统：定义解析、条件求值、状态应用。

这个模块是整套 RPG 的地基——「数值在动、跨过某条线解锁新东西」全靠它。
两条底线：模型提议的改动一律被 min/max 夹住，定义里没有的键一律拒绝。
AI 给 -999 也只能扣到下界，而且要留一条 warning 让玩家看见。
"""
import unittest

from app.models.rpg import RpgItem, RpgModule, RpgNpc, RpgSession
from app.services.rpg_state import (
    ANY_NPC,
    ON_FULL_FLAG,
    ON_ZERO_DEAD, ON_ZERO_FLAG,
    apply_flags, apply_inventory, apply_npc_appearance, apply_npc_notes,
    apply_place_note, apply_relations,
    apply_state_delta,
    apply_stats, apply_tweak,
    check_condition, check_full, check_zero, clamp, def_map, for_check_stats,
    ensure_relation_states, init_relation, init_stats, mark_fired, mark_met, match_npc, note_visited, place_note,
    random_movement_ok,
    starting_inventory,
    tier_list, tier_of, visible_defs,
    APPEARANCE_CHARS, APPEARANCE_LIMIT, FLAG_LIMIT, NOTE_CHARS, NOTE_LIMIT,
    PLACE_CHARS, PLACE_LIMIT,
    TIER_LABEL_CHARS, TIER_NOTE_CHARS, VISITED_LIMIT,
    RANK_GAIN_MAX, cap_rank_gain, rank_stat_of,
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
        "flag_days": {},
        "npc_states": {},
        "npc_notes": {},
        "npc_appearance": {},
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
        spec = {"tiers": [{"at": 0, "label": "冷" * 20, "note": "话" * 200}]}
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


class EnsureRelationStateTests(unittest.TestCase):
    def test_missing_state_is_filled_from_npc_initial_values(self):
        sess = _sess(npc_states={})
        npc = RpgNpc(
            id=3, module_id=1, name="npc", relation_enabled=True,
            initial_state={RELATION_DEFS[0]["name"]: 42},
            relation_stat_names=[d["name"] for d in RELATION_DEFS],
        )

        self.assertTrue(ensure_relation_states(_module(), sess, [npc]))
        self.assertEqual(sess.npc_states["3"], {
            RELATION_DEFS[0]["name"]: 42,
            RELATION_DEFS[1]["name"]: 10,
        })

    def test_existing_values_are_preserved_and_disabled_npcs_are_skipped(self):
        sess = _sess(npc_states={"3": {RELATION_DEFS[0]["name"]: 77}})
        enabled = RpgNpc(id=3, module_id=1, name="enabled", relation_enabled=True)
        disabled = RpgNpc(id=4, module_id=1, name="disabled", relation_enabled=False)

        self.assertTrue(ensure_relation_states(_module(), sess, [enabled, disabled]))
        self.assertEqual(sess.npc_states["3"][RELATION_DEFS[0]["name"]], 77)
        self.assertEqual(sess.npc_states["3"][RELATION_DEFS[1]["name"]], 10)
        self.assertNotIn("4", sess.npc_states)


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

    def test_any_npc_threshold_passes_when_one_character_is_over(self):
        # 「不指定是谁」：任意一个角色达标就算成立，不必先挑一个人
        cond = {"relations": [{"npc": ANY_NPC, "stat": "好感", "op": ">=", "value": 50}]}
        self.assertTrue(check_condition(cond, self.sess, self.npcs)[0])
        cond["relations"][0]["value"] = 80
        ok, why = check_condition(cond, self.sess, self.npcs)
        self.assertFalse(ok)
        self.assertIn("好感", why)

    def test_any_npc_reads_whoever_it_is_given(self):
        """动作那一路只喂选中的对象，于是 ANY_NPC 就是「你选的那个人」。

        _action_gate 传的是 `[target]`，所以同一个写法在动作上不该再是「场上有
        别人达标就行」——那会让按钮对着 A 亮着，点下去判的是 B。
        """
        cond = {"relations": [{"npc": ANY_NPC, "stat": "好感", "op": ">=", "value": 50}]}
        lukewarm = [RpgNpc(id=9, module_id=1, name="路人")]
        states = dict(self.sess.npc_states)
        states["9"] = {"好感": 10}
        self.sess.npc_states = states
        self.assertFalse(check_condition(cond, self.sess, lukewarm)[0])
        # 换成那个达标的人，同一个条件就成立
        self.assertTrue(check_condition(cond, self.sess, self.npcs)[0])

    def test_any_npc_needs_someone_actually_tracking_that_stat(self):
        # 「没追踪」和「值等于 0」是两回事：一个没开关系数值的角色不该被当 0 算
        cond = {"relations": [{"npc": ANY_NPC, "stat": "好感", "op": ">=", "value": 0}]}
        untracked = [RpgNpc(id=7, module_id=1, name="过路人", relation_enabled=False)]
        self.assertFalse(check_condition(cond, self.sess, untracked)[0])

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


class MarkFiredTests(unittest.TestCase):
    """放过的一次性词条。只追加，重复调用不该长出重复 id。"""

    def test_it_appends_without_duplicating(self):
        sess = _sess(fired_entries=[7])
        mark_fired(sess, [7, 12])
        mark_fired(sess, [12])
        self.assertEqual(sess.fired_entries, [7, 12])

    def test_an_empty_list_leaves_it_alone(self):
        sess = _sess(fired_entries=[7])
        mark_fired(sess, [])
        self.assertEqual(sess.fired_entries, [7])


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


class NpcAppearanceTests(unittest.TestCase):
    """这一局被永久改写掉的外貌。合并语义同近况，淘汰规则**正好相反**。

    锁这条差异的是 test_a_full_table_keeps_the_old_ones_and_refuses_the_new：
    照抄近况那套「淘汰最久没更新的」，被扔掉的恰好是最早、也最要紧的那条
    （温眠第 3 天服下的那副药）。
    """

    def test_a_new_key_appends_and_the_same_key_overwrites(self):
        sess = _sess(npc_appearance={"3": {"胸部": "刚有起伏"}})
        apply_npc_appearance(sess, 3, {"胸部": "已定形", "左手": "齐腕断了"})
        self.assertEqual(sess.npc_appearance["3"], {"胸部": "已定形", "左手": "齐腕断了"})

    def test_null_removes_one_override_and_leaves_the_others_alone(self):
        sess = _sess(npc_appearance={"3": {"胸部": "已定形", "左手": "齐腕断了"}})
        apply_npc_appearance(sess, 3, {"左手": None})
        self.assertEqual(sess.npc_appearance["3"], {"胸部": "已定形"})

    def test_a_full_table_keeps_the_old_ones_and_refuses_the_new(self):
        # 和 NpcNoteTests 那条**故意相反**：近况满了扔最旧的，外貌满了扔最新的。
        # 外貌的每一条都是「这个人身上已经发生的永久改变」，没有一条会过期
        sess = _sess(npc_appearance={"3": {f"旧{i}": "x" for i in range(APPEARANCE_LIMIT)}})
        warnings = apply_npc_appearance(sess, 3, {"新的一处": "y"})
        self.assertEqual(len(sess.npc_appearance["3"]), APPEARANCE_LIMIT)
        self.assertNotIn("新的一处", sess.npc_appearance["3"])
        self.assertIn("旧0", sess.npc_appearance["3"])
        self.assertTrue(warnings)

    def test_a_full_table_still_lets_an_existing_key_be_fixed_or_removed(self):
        # 满员只拦新键。已有的一处措辞写错了得能改，否则除了读档没有别的办法
        sess = _sess(npc_appearance={"3": {f"旧{i}": "x" for i in range(APPEARANCE_LIMIT)}})
        apply_npc_appearance(sess, 3, {"旧0": "改过的说法"})
        self.assertEqual(sess.npc_appearance["3"]["旧0"], "改过的说法")
        apply_npc_appearance(sess, 3, {"旧0": None})
        self.assertNotIn("旧0", sess.npc_appearance["3"])

    def test_a_value_that_is_not_a_string_is_flattened_rather_than_stored_raw(self):
        sess = _sess()
        apply_npc_appearance(sess, 3, {"胸部": ["左", "右"], "脸": {"疤": "左颊"}})
        for value in sess.npc_appearance["3"].values():
            self.assertIsInstance(value, str)

    def test_an_over_long_value_is_trimmed_instead_of_dropped(self):
        sess = _sess()
        apply_npc_appearance(sess, 3, {"脸": "一道很长的疤" * 50})
        self.assertLessEqual(len(sess.npc_appearance["3"]["脸"]), APPEARANCE_CHARS + 1)

    def test_two_npcs_keep_their_own_overrides(self):
        sess = _sess(npc_appearance={"3": {"胸部": "已定形"}})
        apply_npc_appearance(sess, 4, {"左手": "齐腕断了"})
        self.assertEqual(sess.npc_appearance["3"]["胸部"], "已定形")
        self.assertEqual(sess.npc_appearance["4"]["左手"], "齐腕断了")

    def test_a_null_table_clears_that_person_entirely(self):
        sess = _sess(npc_appearance={"3": {"胸部": "已定形"}, "4": {"左手": "齐腕断了"}})
        apply_npc_appearance(sess, 3, None)
        self.assertNotIn("3", sess.npc_appearance)
        self.assertIn("4", sess.npc_appearance)

    def test_a_malformed_table_warns_instead_of_swallowing_it(self):
        sess = _sess()
        self.assertTrue(apply_npc_appearance(sess, 3, "这不是字典"))


class PlaceNoteTests(unittest.TestCase):
    """地点近况：这地方被玩家弄成什么样了，一个地方一句。

    它刻意**不是第四个记忆格**。记忆按格子分（玩家一格、每个 NPC 各一格），
    给地点再开一格意味着摘要次数翻倍，而且和玩家那一格大面积重叠——你在地窖
    干的事本来就写在你自己那一份里。「门被踹坏了」是事实，不是叙事。
    """

    def test_one_place_keeps_one_line_and_the_new_one_wins(self):
        sess = _sess(place_notes={"地窖": "门开着"})
        apply_place_note(sess, "地窖", "门被踹坏了，合不上")
        self.assertEqual(sess.place_notes, {"地窖": "门被踹坏了，合不上"})

    def test_an_empty_line_clears_it(self):
        # 玩家手动划掉走的就是这条路（GM 记错了「整间屋子烧没了」）
        sess = _sess(place_notes={"地窖": "门被踹坏了", "酒馆": "桌子掀了"})
        apply_place_note(sess, "地窖", "")
        self.assertEqual(sess.place_notes, {"酒馆": "桌子掀了"})

    def test_the_same_place_spelled_differently_is_still_the_same_place(self):
        # 不按 norm_name 比的话，「地窖」和「地窖 」会各占一格，两句话同时注入
        sess = _sess(place_notes={"地窖": "门开着"})
        apply_place_note(sess, " 地窖 ", "门被踹坏了")
        self.assertEqual(list(sess.place_notes.values()), ["门被踹坏了"])
        self.assertEqual(place_note(sess, "地窖"), "门被踹坏了")

    def test_an_over_long_line_is_trimmed_instead_of_dropped(self):
        sess = _sess()
        apply_place_note(sess, "地窖", "门被踹坏了" * 50)
        self.assertLessEqual(len(sess.place_notes["地窖"]), PLACE_CHARS + 1)

    def test_a_refreshed_place_survives_the_cap_because_it_moves_to_the_end(self):
        # 同 apply_npc_notes：dict 重新赋值不挪键的位置，于是每轮都在刷新的
        # 那个地方会永远停在下标 0，先被砍掉的正是你正站着的这间屋
        sess = _sess(place_notes={"地窖": "门开着", **{f"杂{i}": "x" for i in range(PLACE_LIMIT - 1)}})
        apply_place_note(sess, "地窖", "门被踹坏了")
        self.assertIn("地窖", sess.place_notes)
        apply_place_note(sess, "新地方", "刚到")
        self.assertIn("地窖", sess.place_notes)
        self.assertNotIn("杂0", sess.place_notes)
        self.assertEqual(len(sess.place_notes), PLACE_LIMIT)

    def test_a_place_that_was_never_written_reads_as_empty(self):
        self.assertEqual(place_note(_sess(), "地窖"), "")
        self.assertEqual(place_note(_sess(place_notes={"地窖": "x"}), ""), "")

    def test_a_malformed_value_is_refused_instead_of_stored_as_text(self):
        # 模型会把值写成嵌套字典。str() 一落库就是 "{'门': '坏了'}"，还会每轮
        # 注入【场面】块——那是格式错误，不是这地方的新样子
        sess = _sess(place_notes={"地窖": "门开着"})
        warnings = apply_place_note(sess, "地窖", {"门": "坏了"})
        self.assertTrue(warnings)
        self.assertEqual(sess.place_notes, {"地窖": "门开着"})

    def test_none_still_clears_the_note(self):
        # 玩家手动划掉走的就是这一条，不能被上面那道格式检查挡下来
        sess = _sess(place_notes={"地窖": "门被踹坏了"})
        self.assertEqual(apply_place_note(sess, "地窖", None), [])
        self.assertEqual(sess.place_notes, {})


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


class FlagDayTests(unittest.TestCase):
    """flag 立起来那天记在 flag_days 里，「某件事之后 N 天」全靠它。

    这是 AI 驱动的剧情里唯一能锚的时间点：没有写死的时间线，但「那件事发生在
    第几天」是引擎自己数的天，跟模型怎么写剧情无关。所以记的时机必须钉死。
    """

    def test_a_new_flag_records_today(self):
        sess = _sess(day=4)
        apply_flags(sess, {"聊过电机": True})
        self.assertEqual(sess.flag_days, {"聊过电机": 4})

    def test_setting_the_same_flag_again_does_not_push_the_date_forward(self):
        # 「聊过之后第三天」要从第一次聊算起。重复置位刷新日期的话，
        # 模型每轮顺手再写一遍 True 就能把那一天推到永远不到
        sess = _sess(day=4)
        apply_flags(sess, {"聊过电机": True})
        sess.day = 9
        apply_flags(sess, {"聊过电机": True})
        self.assertEqual(sess.flag_days, {"聊过电机": 4})

    def test_deleting_a_flag_clears_its_date(self):
        # 那件事等于没发生过。留着日期的话重新立起来时「之后三天」当场就满足
        sess = _sess(day=4)
        apply_flags(sess, {"聊过电机": True})
        sess.day = 9
        apply_flags(sess, {"聊过电机": None})
        self.assertEqual(sess.flag_days, {})
        apply_flags(sess, {"聊过电机": True})
        self.assertEqual(sess.flag_days, {"聊过电机": 9})

    def test_a_falsy_value_counts_as_not_happened(self):
        sess = _sess(day=4)
        apply_flags(sess, {"聊过电机": True})
        apply_flags(sess, {"聊过电机": False})
        self.assertEqual(sess.flag_days, {})

    def test_trimming_past_the_limit_takes_the_dates_along(self):
        # 不清的话 flag_days 会攒下一堆指向不存在 flag 的日期，越玩越长
        sess = _sess(day=1, flags={f"旧{i}": True for i in range(FLAG_LIMIT)})
        apply_flags(sess, {"最新的一条": True})
        self.assertEqual(set(sess.flag_days), set(sess.flags))
        self.assertNotIn("旧0", sess.flag_days)

    def test_the_zero_flag_gets_a_date_too(self):
        # check_zero 是第二个写 flags 的地方。漏了它，「精力耗尽之后两天」判不过
        module = _module(stat_defs=[{"name": "精力", "max": 100, "on_zero": ON_ZERO_FLAG}])
        sess = _sess(stats={"精力": 0}, day=6)
        check_zero(module, sess)
        self.assertEqual(sess.flag_days, {"精力耗尽": 6})

    def test_after_days_waits_and_then_opens(self):
        sess = _sess(day=4, flags={"聊过电机": True}, flag_days={"聊过电机": 4})
        cond = {"after_days": [{"flag": "聊过电机", "days": 3}]}
        ok, why = check_condition(cond, sess)
        self.assertFalse(ok)
        # 原因串直接给玩家看，得写还差几天
        self.assertIn("3 天", why)
        sess.day = 6
        self.assertIn("1 天", check_condition(cond, sess)[1])
        sess.day = 7
        self.assertTrue(check_condition(cond, sess)[0])
        sess.day = 20
        self.assertTrue(check_condition(cond, sess)[0])

    def test_a_flag_that_never_fired_fails(self):
        ok, why = check_condition(
            {"after_days": [{"flag": "聊过电机", "days": 3}]}, _sess(day=99),
        )
        self.assertFalse(ok)
        self.assertIn("还没有", why)

    def test_an_old_save_without_a_date_fails_instead_of_passing(self):
        # 加 flag_days 之前的存档：flag 立着但没有日期。引擎不知道那天是哪天，
        # 放行等于凭空满足一个本该等待的条件
        sess = _sess(day=99, flags={"聊过电机": True}, flag_days={})
        ok, why = check_condition({"after_days": [{"flag": "聊过电机", "days": 3}]}, sess)
        self.assertFalse(ok)
        self.assertIn("哪天", why)

    def test_zero_days_means_the_same_day(self):
        sess = _sess(day=4, flags={"到了": True}, flag_days={"到了": 4})
        self.assertTrue(check_condition({"after_days": [{"flag": "到了", "days": 0}]}, sess)[0])


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


class FullTests(unittest.TestCase):
    """填满的后果，check_zero 的镜像。这是「进度时钟」的全部机制。

    一项 max = 8 的数值配上 on_full = 标记，推满就立一条 flag，世界书触发、
    动作可用性、地点进入条件三处都能引用它——不需要新表、新列、新概念。
    """

    def test_filling_a_stat_raises_a_flag(self):
        module = _module(stat_defs=[{"name": "信任", "max": 8, "on_full": ON_FULL_FLAG}])
        sess = _sess(stats={"信任": 8})
        notes = check_full(module, sess)
        self.assertTrue(sess.flags["信任满"])
        self.assertTrue(notes)

    def test_overshooting_counts_too(self):
        # 动作和道具写死的加减不受 step_max 管，能把值顶到上限之上
        module = _module(stat_defs=[{"name": "信任", "max": 8, "on_full": ON_FULL_FLAG}])
        sess = _sess(stats={"信任": 99})
        check_full(module, sess)
        self.assertTrue(sess.flags["信任满"])

    def test_not_yet_full_raises_nothing(self):
        module = _module(stat_defs=[{"name": "信任", "max": 8, "on_full": ON_FULL_FLAG}])
        sess = _sess(stats={"信任": 7})
        self.assertEqual(check_full(module, sess), [])
        self.assertEqual(sess.flags, {})

    def test_a_stat_without_a_ceiling_is_skipped(self):
        # 钱、声望永远填不满。spec 里那个 on_full 是作者填错了，不是一条
        # 永不触发的规则——真去比就会拿 None 当数字
        module = _module(stat_defs=[{"name": "资金", "max": None, "on_full": ON_FULL_FLAG}])
        sess = _sess(stats={"资金": 99999})
        self.assertEqual(check_full(module, sess), [])
        self.assertEqual(sess.flags, {})

    def test_the_default_does_nothing(self):
        # 没填 on_full 的项（也就是所有老模组的所有项）一个字都不动
        module = _module(stat_defs=[{"name": "精力", "max": 100}])
        sess = _sess(stats={"精力": 100})
        self.assertEqual(check_full(module, sess), [])
        self.assertEqual(sess.flags, {})

    def test_the_flag_is_only_raised_once(self):
        module = _module(stat_defs=[{"name": "信任", "max": 8, "on_full": ON_FULL_FLAG}])
        sess = _sess(stats={"信任": 8})
        check_full(module, sess)
        self.assertEqual(check_full(module, sess), [])

    def test_the_full_flag_gets_a_date_too(self):
        # 漏了 _sync_flag_days，「她信任满了之后第 3 天」这条 after_days 判不过
        module = _module(stat_defs=[{"name": "信任", "max": 8, "on_full": ON_FULL_FLAG}])
        sess = _sess(stats={"信任": 8}, day=6)
        check_full(module, sess)
        self.assertEqual(sess.flag_days, {"信任满": 6})

    def test_the_flag_it_raises_is_usable_as_a_condition(self):
        """立 flag 而不是直接触发事件，理由就在这一条：三处条件都能引用它。"""
        module = _module(stat_defs=[{"name": "信任", "max": 8, "on_full": ON_FULL_FLAG}])
        sess = _sess(stats={"信任": 8})
        self.assertFalse(check_condition({"flags": ["信任满"]}, sess)[0])
        check_full(module, sess)
        self.assertTrue(check_condition({"flags": ["信任满"]}, sess)[0])

    def test_there_is_no_death_option(self):
        """填满致死没有语义。要那个效果就用 on_zero 表达。"""
        from app.services.rpg_state import ON_FULL_FLAG as flag, ON_FULL_NONE as none
        module = _module(stat_defs=[{"name": "污染", "max": 8, "on_full": "死亡"}])
        sess = _sess(stats={"污染": 8})
        self.assertEqual(check_full(module, sess), [])
        self.assertEqual(sess.status, "alive")
        self.assertEqual((none, flag), ("无", "标记"))


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

    def test_a_place_note_lands_on_where_you_are_standing(self):
        self.sess.location = "地窖"
        warnings = apply_state_delta(
            self.module, self.sess, {"place_notes": {"地窖": "门被踹坏了"}}, self.npcs,
        )
        self.assertEqual(warnings, [])
        self.assertEqual(self.sess.place_notes["地窖"], "门被踹坏了")

    def test_a_place_note_can_also_land_on_where_you_just_arrived(self):
        # 同一轮里「走进地窖、顺手把门踹坏」：那一笔属于地窖，不属于你出发的地方
        self.sess.location = "巷子"
        apply_state_delta(
            self.module, self.sess,
            {"location": "地窖", "place_notes": {"地窖": "门被踹坏了"}}, self.npcs,
        )
        self.assertEqual(self.sess.place_notes["地窖"], "门被踹坏了")

    def test_a_note_about_a_place_you_never_set_foot_in_is_refused(self):
        # 剧情里提一句「铁匠铺」不该让隔着三条街的铁匠铺凭空塌一半：同 note_npcs，
        # 这是长期事实，每次你走进去都会进【场面】，而玩家没有纠正的入口
        self.sess.location = "地窖"
        warnings = apply_state_delta(
            self.module, self.sess, {"place_notes": {"铁匠铺": "炉子灭了"}}, self.npcs,
        )
        # 拒掉的那一路一个字都不写，连那张表都不该被建出来
        self.assertFalse(self.sess.place_notes)
        self.assertTrue(any("铁匠铺" in w for w in warnings))

    def test_a_place_note_is_matched_back_to_the_real_place_name(self):
        # 模型爱给地名加修饰。对不回真名的话这一笔会存成「外门藏经阁」那一格，
        # 而你站在「藏经阁」，下次回来什么都看不到
        self.sess.location = "藏经阁"
        apply_state_delta(
            self.module, self.sess, {"place_notes": {"外门藏经阁": "书架塌了一排"}},
            self.npcs, places=["藏经阁"],
        )
        self.assertEqual(self.sess.place_notes["藏经阁"], "书架塌了一排")

    def test_moving_someone_does_not_blind_the_place_name_matcher(self):
        # npc_places 那一段原先用的局部变量就叫 places，把参数里的地点表盖掉了：
        # 于是**只要这一轮带了人物位置**，「外门藏经阁 → 藏经阁」就对不回来了，
        # 而那正是 match_place 存在要修的 bug
        npcs = [RpgNpc(id=3, module_id=1, name="赫敏")]
        apply_state_delta(
            self.module, self.sess,
            {"npc_places": {"赫敏": "外门藏经阁"}, "location": "外门藏经阁"},
            npcs, move_npcs=npcs, places=["藏经阁"],
        )
        self.assertEqual(self.sess.location, "藏经阁")
        self.assertEqual(self.sess.npc_places["3"], "藏经阁")


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


class TweakTests(unittest.TestCase):
    """玩家手动改数值的入口（修改器面板），和模型提议那条路是两回事。

    模型提议走 apply_state_delta，头顶压着 cap_delta 那道每轮幅度上限；玩家
    自己动手走 apply_tweak，绕过那道闸——它防的是模型一轮给自己加 80 点好感，
    不是防玩家的手。但 clamp（作者定的 min/max）和归零 / 填满后果照旧生效，
    走的是和平常完全同一条路。
    """

    def test_tweak_sets_the_exact_value_instead_of_adding(self):
        # 面板上收的是目标值。当成增减的话 100 改成 72 会变成 172
        module, sess = _module(), _sess(stats={"精力": 100})
        apply_tweak(module, sess, stats={"精力": 72})
        self.assertEqual(sess.stats["精力"], 72)
        apply_tweak(module, sess, stats={"精力": 30})
        self.assertEqual(sess.stats["精力"], 30)

    def test_tweak_still_obeys_the_author_s_min_and_max(self):
        # clamp 是作者定义的数值范围，不是防作弊的闸，改完了也得落在线里
        module, sess = _module(), _sess(stats={"精力": 50})
        notes = apply_tweak(module, sess, stats={"精力": 999})
        self.assertEqual(sess.stats["精力"], 100)
        self.assertTrue(any("精力" in n and "100" in n for n in notes))

    def test_tweak_is_not_capped_by_the_per_turn_ceiling(self):
        # 关键回归锁：step_max 那道闸是给模型提议用的（apply_state_delta），
        # 玩家自己的手不受它管——打开修改器就是明说要这个数字
        defs = [{"name": "精力", "initial": 10, "min": 0, "max": 100, "step_max": 5}]
        module, sess = _module(stat_defs=defs), _sess(stats={"精力": 10})
        apply_tweak(module, sess, stats={"精力": 90})
        self.assertEqual(sess.stats["精力"], 90)
        # 先确认这道闸对模型那一路真在管，否则上面那条锁的是空气
        module, sess = _module(stat_defs=defs), _sess(stats={"精力": 10})
        apply_state_delta(module, sess, {"stats": {"精力": 80}})
        self.assertEqual(sess.stats["精力"], 15)

    def test_tweak_triggers_the_same_zero_consequences(self):
        # 归零后果不能推到下一轮：值已经是 0 了，下一轮照样触发，
        # 中间这一段反而是面板显示 0 而 status 还写着活着的怪状态
        module = _module(stat_defs=[{"name": "生命", "max": 100, "on_zero": ON_ZERO_DEAD}])
        sess = _sess(stats={"生命": 40})
        notes = apply_tweak(module, sess, stats={"生命": 0})
        self.assertEqual(sess.status, "dead")
        self.assertTrue(notes)

        module = _module(stat_defs=[{"name": "精力", "max": 100, "on_zero": ON_ZERO_FLAG}])
        sess = _sess(stats={"精力": 40})
        apply_tweak(module, sess, stats={"精力": 0})
        self.assertTrue(sess.flags.get("精力耗尽"))

    def test_tweak_only_touches_the_named_npc(self):
        module = _module()
        sess = _sess(npc_states={
            "1": init_relation(RELATION_DEFS),
            "2": init_relation(RELATION_DEFS),
        })
        apply_tweak(module, sess, relations={"1": {"好感": 80}})
        self.assertEqual(sess.npc_states["1"]["好感"], 80)
        self.assertEqual(sess.npc_states["2"]["好感"], 0)
        # npc_states 里根本没有的角色：apply_relations 会拒绝，这里不该抛
        notes = apply_tweak(module, sess, relations={"9": {"好感": 50}})
        self.assertTrue(any("这个角色没有启用关系数值" in n for n in notes))

    def test_tweak_treats_inventory_qty_as_the_target_count(self):
        # 面板上写的是「要几件」。当成增减的话 2 件改成 5 会变成 7 件
        module, sess = _module(), _sess(inventory=[{"name": "绳子", "qty": 2}])
        apply_tweak(module, sess, inventory=[{"name": "绳子", "qty": 5}])
        self.assertEqual(len(sess.inventory), 1)
        self.assertEqual(sess.inventory[0]["qty"], 5)
        # qty 0 是「一件都不留」，走 apply_inventory 的扣到 0 就删掉那条路
        apply_tweak(module, sess, inventory=[{"name": "绳子", "qty": 0}])
        self.assertEqual(sess.inventory, [])
        # 背包里没有的名字就是新增一条
        apply_tweak(module, sess, inventory=[{"name": "火把", "qty": 3}])
        self.assertEqual([(r["name"], r["qty"]) for r in sess.inventory], [("火把", 3)])

    def test_tweak_writes_nothing_the_gm_would_see(self):
        # 修改器对 GM 完全静默：GM 每轮本来就拿当前数值，只会看到新数字。
        # 这条防以后有人顺手往大事记里加一句「玩家改了数值」
        module, sess = _module(), _sess(chronicle=["旧事"])
        apply_tweak(module, sess, stats={"精力": 30}, flags={"开过修改器": True})
        self.assertEqual(sess.chronicle, ["旧事"])


class RankGainTests(unittest.TestCase):
    """等级一轮最多升 1 级。只夹上行——修为被废是正当的剧情。"""

    LEVELS = [{"name": "境界", "initial": 1, "min": 0, "max": 9}]

    def _mod(self, **over):
        base = {"stat_defs": [dict(d) for d in self.LEVELS], "rank_stat": "境界"}
        base.update(over)
        return _module(**base)

    def test_a_single_win_does_not_carry_you_to_the_top(self):
        module, sess = self._mod(), _sess(stats={"境界": 3})
        notes = apply_state_delta(module, sess, {"stats": {"境界": 5}})
        self.assertEqual(sess.stats["境界"], 4)
        self.assertTrue(any("境界" in n for n in notes))

    def test_losing_everything_is_not_capped(self):
        # 「修为被废，从 8 掉到 0」是正当的剧情。cap_delta 那道闸是对称的，
        # 借它实现这条上限就会把这件事也锁成 -1
        module, sess = self._mod(), _sess(stats={"境界": 8})
        apply_state_delta(module, sess, {"stats": {"境界": -8}})
        self.assertEqual(sess.stats["境界"], 0)

    def test_the_author_s_own_step_max_wins_including_zero(self):
        module = self._mod(stat_defs=[{"name": "境界", "min": 0, "max": 9, "step_max": 3}])
        sess = _sess(stats={"境界": 3})
        apply_state_delta(module, sess, {"stats": {"境界": 5}})
        self.assertEqual(sess.stats["境界"], 6)
        # 填 0 = 这一项模型一点都不许动，只能靠动作和道具改
        module = self._mod(stat_defs=[{"name": "境界", "min": 0, "max": 9, "step_max": 0}])
        sess = _sess(stats={"境界": 3})
        apply_state_delta(module, sess, {"stats": {"境界": 5}})
        self.assertEqual(sess.stats["境界"], 3)

    def test_numeric_mode_is_byte_for_byte_unchanged(self):
        module, sess = self._mod(rank_stat=""), _sess(stats={"境界": 3})
        self.assertEqual(apply_state_delta(module, sess, {"stats": {"境界": 5}}), [])
        self.assertEqual(sess.stats["境界"], 8)

    def test_other_stats_are_untouched(self):
        module = self._mod(stat_defs=STAT_DEFS + [dict(self.LEVELS[0])])
        sess = _sess(stats={"精力": 10, "境界": 3})
        apply_state_delta(module, sess, {"stats": {"精力": 40, "境界": 5}})
        self.assertEqual(sess.stats["精力"], 50)
        self.assertEqual(sess.stats["境界"], 4)

    def test_the_author_s_module_json_comes_out_untouched(self):
        """def_map 返回的是 module.stat_defs 里同一批 dict 的引用。

        原地往里塞一个 step_max，只要同一请求里别处 setattr(module, "stat_defs")
        （编辑器保存、向导回填都会），那个凭空多出来的值就被持久化了。
        """
        module = self._mod()
        before = [dict(d) for d in module.stat_defs]
        apply_state_delta(module, _sess(stats={"境界": 3}), {"stats": {"境界": 5}})
        self.assertEqual(module.stat_defs, before)

    def test_settling_the_same_turn_twice_still_only_gives_one_level(self):
        module, sess = self._mod(), _sess(stats={"境界": 3})
        apply_state_delta(module, sess, {"stats": {"境界": 5}})
        self.assertEqual(sess.stats["境界"], 4)

    def test_the_pure_function_on_its_own(self):
        module = self._mod()
        self.assertEqual(cap_rank_gain(module, {"境界": 9})[0], {"境界": RANK_GAIN_MAX})
        self.assertEqual(cap_rank_gain(module, {"境界": 1})[0], {"境界": 1})
        self.assertEqual(cap_rank_gain(module, {"境界": -4})[0], {"境界": -4})
        # 坏值原样放过去，交给下游——这里不是校验的地方
        for junk in (True, "三级", None, [1]):
            self.assertEqual(cap_rank_gain(module, {"境界": junk})[0], {"境界": junk})
        self.assertEqual(cap_rank_gain(module, None), ({}, []))
        self.assertEqual(cap_rank_gain(module, {"精力": 9})[0], {"精力": 9})

    def test_rank_stat_of_tolerates_a_stub_without_the_attribute(self):
        # 结算传的是 working 副本，测试里的 module 常是手搓对象
        self.assertEqual(rank_stat_of(object()), "")
        self.assertEqual(rank_stat_of(self._mod(rank_stat="  境界  ")), "境界")


class RandomMovementOkTests(unittest.TestCase):
    """随机移动的三张判据。三处调用点共用这一个函数，所以在这儿钉组合。"""

    def _npc(self, **over):
        base = {
            "name": "赫敏", "random_movement": True,
            "random_movement_slots": [], "random_movement_places": [],
        }
        base.update(over)
        return RpgNpc(module_id=1, **base)

    def test_no_whitelist_means_no_restriction(self):
        npc = self._npc()
        self.assertTrue(random_movement_ok(npc, "晚"))
        self.assertTrue(random_movement_ok(npc, "晚", "任何地方"))
        # 没勾随机移动一律不动，这是最外面那道
        self.assertFalse(random_movement_ok(self._npc(random_movement=False), "晚", "图书馆"))
        self.assertFalse(random_movement_ok(None, "晚", "图书馆"))

    def test_the_slot_whitelist(self):
        npc = self._npc(random_movement_slots=["晚", " 早 "])
        self.assertTrue(random_movement_ok(npc, "晚"))
        self.assertTrue(random_movement_ok(npc, "早"))
        self.assertFalse(random_movement_ok(npc, "中"))
        self.assertFalse(random_movement_ok(npc, ""))

    def test_the_place_whitelist(self):
        npc = self._npc(random_movement_places=["图书馆", " 禁林 "])
        self.assertTrue(random_movement_ok(npc, "晚", "图书馆"))
        self.assertTrue(random_movement_ok(npc, "晚", "禁林"))
        self.assertFalse(random_movement_ok(npc, "晚", "寝室"))
        # place 留空是「只问准不准动」，这时白名单不参与
        self.assertTrue(random_movement_ok(npc, "晚"))

    def test_both_whitelists_must_hold(self):
        npc = self._npc(random_movement_slots=["晚"], random_movement_places=["图书馆"])
        self.assertTrue(random_movement_ok(npc, "晚", "图书馆"))
        self.assertFalse(random_movement_ok(npc, "中", "图书馆"))
        self.assertFalse(random_movement_ok(npc, "晚", "寝室"))

    def test_a_stub_without_the_columns_behaves_like_no_whitelist(self):
        # 老库的行、以及测试里的手搓对象都可能缺这两列
        class Stub:
            random_movement = True

        self.assertTrue(random_movement_ok(Stub(), "晚", "图书馆"))


if __name__ == "__main__":
    unittest.main()
