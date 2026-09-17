import unittest
from types import SimpleNamespace

from app.services.rpg_settlement import _is_new_gain, filter_item_claims


NARRATION = (
    "柳娘子从柜台底下摸出三颗固元丹塞给你，说路上垫垫。"
    "你把最后一支火把点了，顺手把那把铁钥匙也留在了桌上。"
)


def _row(name, item_id=1):
    return SimpleNamespace(name=name, id=item_id)


class NewGainTests(unittest.TestCase):
    """哪些条目要拦下来等玩家点头。判据只有两条：正数、背包里还没有同名。"""

    def test_a_brand_new_item_is_held_back(self):
        self.assertTrue(_is_new_gain({"name": "固元丹", "qty": 3}, set()))

    def test_losing_something_always_goes_straight_through(self):
        """负数是已经写出来的事实（用掉、交出、失去），拦下来等于把剧情推回去。"""
        self.assertFalse(_is_new_gain({"name": "火把", "qty": -1}, set()))

    def test_more_of_something_you_already_carry_goes_straight_through(self):
        """已有同名直接 +qty，否则捡第二根箭还要再点一次确认。"""
        self.assertFalse(_is_new_gain({"name": "固元丹", "qty": 2}, {"固元丹"}))

    def test_a_sloppily_spaced_name_is_the_same_item(self):
        """模型写「铁 钥匙」很常见，按字面算就成了一件没见过的东西。"""
        self.assertFalse(_is_new_gain({"name": "铁 钥匙", "qty": 1}, {"铁钥匙"}))

    def test_a_boolean_quantity_is_not_a_quantity(self):
        """bool 是 int 的子类，True 会被当成 1——那是格式错误，交给校验去报。"""
        self.assertFalse(_is_new_gain({"name": "固元丹", "qty": True}, set()))

    def test_a_zero_or_missing_quantity_is_not_a_gain(self):
        self.assertFalse(_is_new_gain({"name": "固元丹", "qty": 0}, set()))
        self.assertFalse(_is_new_gain({"name": "固元丹"}, set()))


class FilterItemClaimsTests(unittest.TestCase):
    def _run(self, bag=(), items=(), pending=()):
        data = {"inventory": [
            {"name": "固元丹", "qty": 3, "note": "路上垫垫"},
            {"name": "火把", "qty": -1},
        ]}
        return filter_item_claims(data, NARRATION, list(bag), list(items), 7, pending)

    def test_only_the_new_gain_becomes_a_claim(self):
        got = self._run()
        self.assertEqual([entry["name"] for entry in got], ["固元丹"])
        self.assertEqual(got[0]["qty"], 3)
        self.assertEqual(got[0]["message_id"], 7)

    def test_the_hint_is_the_sentence_from_the_narration(self):
        """名字往往只是个称呼，玩家靠这句原话判断该不该认下这件东西。"""
        self.assertIn("柳娘子", self._run()[0]["hint"])

    def test_an_item_the_module_already_defines_still_needs_confirming(self):
        """定义里有只说明作者写过这件东西，不说明这一轮玩家真拿到了它——
        区别只在不必再问「一次性还是重复使用」，所以带上 known_item_id。"""
        got = self._run(items=[_row("固元丹", 12)])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["known_item_id"], 12)

    def test_an_undefined_item_leaves_the_consumable_question_open(self):
        self.assertIsNone(self._run()[0]["known_item_id"])

    def test_something_already_waiting_is_not_reported_twice(self):
        """一件东西只要还在正文里被提起，每回合都会被重新报上来。不去重的话
        道具格上就堆出一串同名的行，玩家得一条条点掉。"""
        self.assertEqual(self._run(pending=[{"name": "固元丹"}]), [])

    def test_the_same_name_listed_twice_in_one_proposal_only_claims_once(self):
        data = {"inventory": [
            {"name": "固元丹", "qty": 1},
            {"name": "固元丹", "qty": 2},
        ]}
        got = filter_item_claims(data, NARRATION, [], [], 7, ())
        self.assertEqual(len(got), 1)

    def test_a_malformed_inventory_does_not_raise(self):
        self.assertEqual(filter_item_claims({"inventory": "拿到了固元丹"}, NARRATION, [], [], 7), [])
        self.assertEqual(filter_item_claims({}, NARRATION, [], [], 7), [])


if __name__ == "__main__":
    unittest.main()
