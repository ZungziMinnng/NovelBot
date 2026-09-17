import unittest
from types import SimpleNamespace

from app.services.context_budget import estimate_tokens
from app.services.rpg_context import CATALOG_TOKEN_BUDGET, catalog_block


def _def(name, description=""):
    return SimpleNamespace(name=name, description=description)


def _sess(inventory=(), skills=()):
    return SimpleNamespace(inventory=list(inventory), skills=list(skills))


class CatalogBlockTests(unittest.TestCase):
    """这一块存在的理由只有一个：没勾「开局就有」的道具和技能，GM 以前
    压根不知道它们存在，于是一整局都发不出去。所以头一条就要验它们在里面。"""

    def test_things_the_player_does_not_have_are_still_listed(self):
        block = catalog_block(
            [_def("治伤药水", "褐色，闻着发苦")], [_def("破军斩", "起手极慢")], _sess(),
        )
        self.assertIn("治伤药水", block)
        self.assertIn("还没到他手里", block)
        self.assertIn("破军斩", block)
        self.assertIn("还没学会", block)

    def test_what_he_already_has_is_marked_and_comes_first(self):
        block = catalog_block(
            [_def("治伤药水"), _def("铜铃")], [],
            _sess(inventory=[{"name": " 铜铃 ", "qty": 1}]),
        )
        self.assertIn("铜铃（他身上有）", block)
        self.assertIn("治伤药水（还没到他手里）", block)
        # 有的排前面，超预算降级时先丢的才是他还没有的那些
        self.assertLess(block.index("铜铃"), block.index("治伤药水"))

    def test_the_block_never_carries_numbers(self):
        """effects 不进这一块：数值是引擎按 effects 算的，摆进提示词只会
        诱导模型在正文里自己报一遍，两边对不上。"""
        item = SimpleNamespace(name="治伤药水", description="", effects={"精力": 20})
        self.assertNotIn("20", catalog_block([item], [], _sess()))

    def test_nothing_defined_means_no_block_at_all(self):
        self.assertEqual(catalog_block([], [], _sess()), "")

    def test_a_huge_catalogue_is_cut_down_to_budget(self):
        items = [_def(f"道具{i}", "描述" * 30) for i in range(300)]
        block = catalog_block(items, [], _sess())
        self.assertLessEqual(estimate_tokens(block), CATALOG_TOKEN_BUDGET)

    def test_degrading_keeps_what_he_has_over_what_he_does_not(self):
        """降级第二级会丢掉「他还没有的」那一半，但他身上的必须留住——
        模型连背包里那件东西是什么都不知道的话，这一块就白加了。"""
        mine = _def("铜铃", "摇起来声音发闷")
        rest = [_def(f"杂物{i}", "描述" * 40) for i in range(200)]
        block = catalog_block([mine, *rest], [], _sess(inventory=[{"name": "铜铃"}]))
        self.assertIn("铜铃", block)
        self.assertNotIn("杂物199", block)


if __name__ == "__main__":
    unittest.main()
