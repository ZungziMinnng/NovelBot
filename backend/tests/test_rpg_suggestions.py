"""建议条的结构化收口：纯函数，不碰 LLM、不落库。

钉的是两件事：**白名单每一格都对应一个真实的引擎拦截点**（写漏一格不报错，
只是建议里多一条点了会弹黄条的动作），以及**对不上时降级而不是丢弃**。
"""
import unittest

from app.models.rpg import RpgAction, RpgItem, RpgLocation, RpgNpc, RpgSession, RpgSkill
from app.services.rpg_suggestions import (
    SuggestSources, allow_lists, clean_suggestions, parse_tagged_lines, split_quota,
)


def _sess(**over):
    base = dict(
        id=1, module_id=1, char_name="阿隼", location="地窖",
        inventory=[], skills=[], stats={}, flags={}, day=1, slot="",
    )
    base.update(over)
    return RpgSession(**base)


def _sources(**over):
    base = dict(npcs=[], items=[], skills=[], locations=[], actions=[])
    base.update(over)
    return SuggestSources(**base)


def _item(name, usable=True):
    return RpgItem(id=1, module_id=1, name=name, usable=usable)


def _skill(name, usable=True):
    return RpgSkill(id=1, module_id=1, name=name, usable=usable)


def _place(name, enter_requires=None):
    return RpgLocation(id=1, module_id=1, name=name, enter_requires=enter_requires or {})


def _action(id_, name, needs_target=False, target_anywhere=False):
    return RpgAction(
        id=id_, module_id=1, name=name,
        needs_target=needs_target, target_anywhere=target_anywhere,
    )


class TagLineTests(unittest.TestCase):
    """主动路的行首标签协议。顺序错一步就会漏掉一批写法，所以逐种钉住。"""

    def test_a_plain_line_has_no_tag(self):
        self.assertEqual(
            parse_tagged_lines("先去问问老兵"),
            [{"kind": "free", "name": "", "text": "先去问问老兵"}],
        )

    def test_a_tag_is_split_into_kind_name_and_body(self):
        self.assertEqual(
            parse_tagged_lines("[技|暗影步] 绕到他背后"),
            [{"kind": "skill", "name": "暗影步", "text": "绕到他背后"}],
        )

    def test_every_tag_letter_maps_to_its_kind(self):
        got = parse_tagged_lines("\n".join([
            "[技|暗影步] 用招", "[物|止血草] 敷上", "[去|后山] 过去", "[行|夸她] 夸一句",
        ]))
        self.assertEqual([g["kind"] for g in got], ["skill", "item", "move", "action"])

    def test_a_full_width_pipe_works(self):
        self.assertEqual(
            parse_tagged_lines("[物｜止血草] 敷上")[0],
            {"kind": "item", "name": "止血草", "text": "敷上"},
        )

    def test_an_unknown_tag_letter_stays_in_the_text(self):
        """认不出的标签不剥——它可能是正文里的方括号，剥了会吃掉玩家的字。"""
        self.assertEqual(
            parse_tagged_lines("[怪|什么] 走开")[0],
            {"kind": "free", "name": "", "text": "[怪|什么] 走开"},
        )

    def test_line_noise_and_quotes_are_stripped(self):
        got = parse_tagged_lines("- 1. 「撬开那把铁锁」")
        self.assertEqual(got[0]["text"], "撬开那把铁锁")

    def test_quotes_around_the_body_are_stripped_too(self):
        self.assertEqual(
            parse_tagged_lines("[技|暗影步]「绕过去」")[0],
            {"kind": "skill", "name": "暗影步", "text": "绕过去"},
        )

    def test_quotes_wrapping_the_whole_tagged_line_are_stripped_first(self):
        """整行带引号时，标签必须在剥完引号之后才认得出来。"""
        self.assertEqual(
            parse_tagged_lines("「[技|暗影步] 绕过去」")[0],
            {"kind": "skill", "name": "暗影步", "text": "绕过去"},
        )

    def test_a_leading_number_needs_a_separator(self):
        """「3天后再来」有个数字，但它不是编号。"""
        self.assertEqual(parse_tagged_lines("3天后再来看看")[0]["text"], "3天后再来看看")

    def test_blank_lines_are_dropped(self):
        self.assertEqual(len(parse_tagged_lines("先走\n\n   \n再问")), 2)

    def test_a_half_written_tag_is_left_alone(self):
        self.assertEqual(parse_tagged_lines("[技|绕过去")[0]["kind"], "free")


class AllowListTests(unittest.TestCase):
    """四张白名单。每一格写漏了都不报错，只是建议里多一条点不动的动作。"""

    def test_an_owned_and_defined_item_is_allowed(self):
        sess, src = _sess(inventory=[{"name": "止血草", "qty": 2}]), _sources(items=[_item("止血草")])
        self.assertEqual(allow_lists(sess, src)["item"], {"止血草": "止血草"})

    def test_an_item_missing_from_the_module_is_excluded(self):
        """剧情里捡到的名字，模组表里没有 —— 点了必然弹「模组里没有这件道具」。"""
        sess, src = _sess(inventory=[{"name": "神秘钥匙", "qty": 1}]), _sources(items=[_item("止血草")])
        self.assertEqual(allow_lists(sess, src)["item"], {})

    def test_an_item_at_zero_quantity_is_excluded(self):
        sess, src = _sess(inventory=[{"name": "止血草", "qty": 0}]), _sources(items=[_item("止血草")])
        self.assertEqual(allow_lists(sess, src)["item"], {})

    def test_an_unusable_item_is_excluded(self):
        sess = _sess(inventory=[{"name": "铁钥匙", "qty": 1}])
        src = _sources(items=[_item("铁钥匙", usable=False)])
        self.assertEqual(allow_lists(sess, src)["item"], {})

    def test_an_owned_and_defined_skill_is_allowed(self):
        sess = _sess(skills=[{"name": "暗影步", "cooldown_left": 0}])
        src = _sources(skills=[_skill("暗影步")])
        self.assertEqual(allow_lists(sess, src)["skill"], {"暗影步": "暗影步"})

    def test_a_skill_on_cooldown_is_excluded(self):
        sess = _sess(skills=[{"name": "暗影步", "cooldown_left": 2}])
        src = _sources(skills=[_skill("暗影步")])
        self.assertEqual(allow_lists(sess, src)["skill"], {})

    def test_a_skill_missing_from_the_module_is_excluded(self):
        sess = _sess(skills=[{"name": "野路子", "cooldown_left": 0}])
        src = _sources(skills=[_skill("暗影步")])
        self.assertEqual(allow_lists(sess, src)["skill"], {})

    def test_the_original_name_wins_over_what_is_stored(self):
        """比对走归一化，但带回去的必须是模组里写的那一份。"""
        sess = _sess(inventory=[{"name": " 止血草 ", "qty": 1}])
        src = _sources(items=[_item("止血草")])
        self.assertEqual(allow_lists(sess, src)["item"], {"止血草": "止血草"})

    def test_the_current_place_is_not_a_destination(self):
        sess, src = _sess(location="地窖"), _sources(locations=[_place("地窖")])
        self.assertEqual(allow_lists(sess, src)["move"], {})

    def test_a_place_whose_condition_fails_is_excluded(self):
        sess = _sess(stats={"精力": 10})
        src = _sources(locations=[_place("后山", {"stats": {"精力": {"op": ">=", "value": 100}}})])
        self.assertEqual(allow_lists(sess, src)["move"], {})

    def test_a_place_whose_condition_holds_is_allowed(self):
        sess = _sess(stats={"精力": 90})
        src = _sources(locations=[_place("后山", {"stats": {"精力": {"op": ">=", "value": 50}}})])
        self.assertEqual(allow_lists(sess, src)["move"], {"后山": "后山"})

    def test_actions_come_straight_from_the_caller(self):
        """_action_gate 是唯一的判据，这里只信调用方递进来的 `usable`。"""
        src = _sources(usable=[(_action(7, "夸她"), "柳如烟")])
        self.assertEqual(allow_lists(_sess(), src)["action"], {"夸她": "夸她"})

    def test_the_raw_action_table_is_not_a_whitelist(self):
        """`actions` 是模组定义的全部动作，没过判据。忘填 `usable` 时它必须
        落成空——失败的方向要是「动作全降级成自由文本」，不能是「作者没放的
        按钮全放进来」。"""
        src = _sources(actions=[_action(7, "夸她")])
        self.assertEqual(allow_lists(_sess(), src)["action"], {})


class CleanSuggestionTests(unittest.TestCase):

    def _clean(self, raw, sess=None, src=None):
        return clean_suggestions(raw, sess or _sess(), src or _sources())

    def test_a_tagged_item_becomes_structured(self):
        got = self._clean(
            parse_tagged_lines("[物|止血草] 先把血止住"),
            sess=_sess(inventory=[{"name": "止血草", "qty": 1}]),
            src=_sources(items=[_item("止血草")]),
        )
        self.assertEqual(got, [{
            "text": "先把血止住", "kind": "item", "name": "止血草", "action_id": None,
        }])

    def test_a_name_that_is_not_allowed_degrades_to_free(self):
        """幻觉出来的技能，作为自由文本建议依然成立，不该丢掉。"""
        got = self._clean(parse_tagged_lines("[技|影分身] 骗过他"))
        self.assertEqual(got, [{
            "text": "骗过他", "kind": "free", "name": "", "action_id": None,
        }])

    def test_a_plain_string_stays_free(self):
        self.assertEqual(
            self._clean(["顺着楼梯继续往下"])[0]["kind"], "free",
        )

    def test_an_unknown_kind_degrades_to_free(self):
        got = self._clean([{"kind": "咒语", "text": "念一段咒"}])
        self.assertEqual(got[0]["kind"], "free")

    def test_a_json_object_from_the_settlement_path_is_accepted(self):
        got = self._clean(
            [{"kind": "item", "name": "止血草", "text": "敷上"}],
            sess=_sess(inventory=[{"name": "止血草", "qty": 1}]),
            src=_sources(items=[_item("止血草")]),
        )
        self.assertEqual(got[0]["kind"], "item")
        self.assertEqual(got[0]["name"], "止血草")

    def test_an_action_gets_its_id_from_the_table(self):
        got = self._clean(
            parse_tagged_lines("[行|夸她] 夸她一句"),
            src=_sources(usable=[(_action(7, "夸她"), "柳如烟")]),
        )
        self.assertEqual(got[0], {
            "text": "夸她一句", "kind": "action", "name": "", "action_id": 7,
        })

    def test_an_action_that_no_longer_exists_degrades_to_free(self):
        """建议是模组改动之前生成的，那个动作可能已经被作者删了。"""
        got = self._clean(parse_tagged_lines("[行|已经删掉的动作] 试试"))
        self.assertEqual(got[0]["kind"], "free")
        self.assertIsNone(got[0]["action_id"])

    def test_the_tag_carries_the_line_when_the_model_wrote_no_body(self):
        got = self._clean(
            parse_tagged_lines("[去|后山]"),
            src=_sources(locations=[_place("后山")]),
        )
        self.assertEqual(got[0], {
            "text": "你前往后山。", "kind": "move", "name": "后山", "action_id": None,
        })

    def test_duplicates_are_dropped(self):
        got = self._clean(["先问问老兵", "先问问老兵"])
        self.assertEqual(len(got), 1)

    def test_at_most_three(self):
        """不传 limit 就是被动路（每轮结算顺带产出）的行为，总量 3 条。"""
        got = self._clean(["一", "二", "三", "四", "五"])
        self.assertEqual(len(got), 3)

    def test_a_wider_limit_lets_more_through(self):
        """主动路先捞一个宽池子，名额留给 split_quota 去分。"""
        got = clean_suggestions(
            ["一", "二", "三", "四", "五"], _sess(), _sources(), limit=12,
        )
        self.assertEqual(len(got), 5)

    def test_a_non_list_is_ignored(self):
        self.assertEqual(self._clean(None), [])
        self.assertEqual(self._clean({"text": "不是数组"}), [])

    def test_rows_that_are_not_strings_or_dicts_are_dropped_one_by_one(self):
        got = self._clean(["好的", 42, None, "也好"])
        self.assertEqual([g["text"] for g in got], ["好的", "也好"])


class SplitQuotaTests(unittest.TestCase):
    """「帮我想想」那条路的名额分配：3 条能点的 + 3 句台词，两个桶各管各的。"""

    def test_three_of_each_with_the_structured_ones_first(self):
        rows = (
            [{"kind": "skill", "text": f"技{i}"} for i in range(5)]
            + [{"kind": "free", "text": f"话{i}"} for i in range(5)]
        )
        self.assertEqual(
            [r["text"] for r in split_quota(rows)],
            ["技0", "技1", "技2", "话0", "话1", "话2"],
        )

    def test_a_flood_of_structured_lines_cannot_crowd_out_the_dialogue(self):
        """这就是不直接截前六条的理由：模型一口气写满能做的事时，台词得留着。"""
        rows = (
            [{"kind": "item", "text": f"物{i}"} for i in range(8)]
            + [{"kind": "free", "text": "我不去"}]
        )
        got = split_quota(rows)
        self.assertEqual(len(got), 4)
        self.assertEqual(got[-1]["text"], "我不去")

    def test_all_free_is_capped_at_three(self):
        rows = [{"kind": "free", "text": f"话{i}"} for i in range(6)]
        self.assertEqual(len(split_quota(rows)), 3)

    def test_the_original_order_inside_each_bucket_is_kept(self):
        rows = [
            {"kind": "free", "text": "先说话"},
            {"kind": "move", "text": "再走"},
            {"kind": "free", "text": "后说话"},
        ]
        self.assertEqual(
            [r["text"] for r in split_quota(rows)], ["再走", "先说话", "后说话"],
        )


if __name__ == "__main__":
    unittest.main()
