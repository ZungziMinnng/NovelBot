import unittest

from app.services import rpg_context
from app.services.rpg_budget import BASELINE_TOTAL, SECTION_BASE, build_rpg_budget
from app.services.rpg_context import DROP_ORDER, PROTECTED_SECTIONS, _fit_sections


class BaselineTests(unittest.TestCase):
    """零回归的凭证：基准总闸下摊出来的每一项都**精确等于**从前写死的常量。

    整数乘除（base * total // BASELINE_TOTAL）就是为了这一条。用浮点比例的话
    `3000 * 21500 / 21500` 也能回到 3000，但改成 `int(base * ratio)` 之后
    任何一个块差一个 token，老局的 prompt 就会从某个位置开始整段错位。
    """

    def test_the_default_budget_reproduces_todays_constants_exactly(self):
        budget = build_rpg_budget(None)
        pairs = {
            "world": rpg_context.WORLD_TOKEN_BUDGET,
            "summary": rpg_context.SUMMARY_TOKEN_BUDGET,
            "aside_summary": rpg_context.ASIDE_SUMMARY_TOKEN_BUDGET,
            "state": rpg_context.STATE_TOKEN_BUDGET,
            "npc": rpg_context.NPC_TOKEN_BUDGET,
            "roster": rpg_context.ROSTER_TOKEN_BUDGET,
            "chronicle": rpg_context.CHRONICLE_TOKEN_BUDGET,
            "meaning": rpg_context.MEANING_TOKEN_BUDGET,
            "scene": rpg_context.SCENE_TOKEN_BUDGET,
            "catalog": rpg_context.CATALOG_TOKEN_BUDGET,
            "npc_history": rpg_context.NPC_HISTORY_TOKEN_BUDGET,
            "milestone": rpg_context.MILESTONE_TOKEN_BUDGET,
        }
        for key, constant in pairs.items():
            with self.subTest(key=key):
                self.assertEqual(budget[key], constant)
        self.assertEqual(budget["system"], rpg_context.SYSTEM_TOKEN_BUDGET)
        self.assertEqual(budget["system"], BASELINE_TOTAL)
        # 基准表和常量表不能有一边多出一项来：漏接的那一块会永远停在老额度上
        self.assertEqual(set(budget) - {"system"}, set(SECTION_BASE))

    def test_an_explicit_baseline_is_the_same_as_leaving_it_blank(self):
        self.assertEqual(build_rpg_budget(BASELINE_TOTAL), build_rpg_budget(None))

    def test_doubling_the_gate_roughly_doubles_every_block(self):
        budget = build_rpg_budget(BASELINE_TOTAL * 2)
        for key, base in SECTION_BASE.items():
            with self.subTest(key=key):
                self.assertEqual(budget[key], base * 2)

    def test_a_silly_gate_never_produces_a_zero_budget(self):
        """0 和负数退回基准；1 这种极小值每块至少留 1——
        额度算出 0 会让 truncate_to_token_budget 把整块裁空，静默丢掉一段。"""
        self.assertEqual(build_rpg_budget(0), build_rpg_budget(None))
        self.assertEqual(build_rpg_budget(-5)["system"], 1)
        tiny = build_rpg_budget(1)
        self.assertTrue(all(value >= 1 for value in tiny.values()))


class FitSectionsTests(unittest.TestCase):
    """丢块顺序。修的是这个 bug：写作规则排在 sections 最末尾，而从前那一刀
    从尾部切，于是最先没的永远是护栏，接着是【此前剧情】【长期事实】。"""

    def _sections(self, big: str):
        return [
            ("gm", "GM"),
            ("catalog", "道具" + big),
            ("roster", "总表" + big),
            ("state", "【你】血 30"),
            ("sample", "样例" + big),
            ("chronicle", "外场" + big),
            ("memories", "【长期事实】她答应过你"),
            ("summary", "【此前剧情】你们在药园见过"),
            ("rules", "不要写心理活动"),
        ]

    def test_nothing_is_touched_when_it_already_fits(self):
        sections = self._sections("")
        text, dropped = _fit_sections(sections, 10_000)
        self.assertEqual(text, "\n\n".join(t for _, t in sections))
        self.assertEqual(dropped, [])

    def test_the_guardrail_and_the_memory_survive_a_blowout(self):
        sections = self._sections("啊" * 2000)
        text, dropped = _fit_sections(sections, 200)
        for keep in ("GM", "【你】血 30", "【长期事实】她答应过你",
                     "【此前剧情】你们在药园见过", "不要写心理活动"):
            with self.subTest(keep=keep):
                self.assertIn(keep, text)
        # 四块可丢的全丢光了，而且是按 DROP_ORDER 的顺序丢的
        self.assertEqual(dropped, ["sample", "roster", "chronicle", "catalog"])

    def test_the_least_important_block_goes_first(self):
        """只超一点点时只丢一块，而且是叙事样例——不是排在最后的写作规则。"""
        sections = self._sections("")
        fits = len("\n\n".join(t for _, t in sections))
        text, dropped = _fit_sections(
            [(k, t + ("啊" * 300 if k == "sample" else "")) for k, t in sections],
            max(1, int(fits * 1.5)),
        )
        self.assertEqual(dropped, ["sample"])
        self.assertIn("不要写心理活动", text)
        self.assertIn("道具", text)

    def test_the_kept_blocks_stay_in_their_original_order(self):
        sections = self._sections("啊" * 2000)
        text, _ = _fit_sections(sections, 200)
        self.assertLess(text.index("GM"), text.index("【你】血 30"))
        self.assertLess(text.index("【长期事实】"), text.index("【此前剧情】"))
        self.assertLess(text.index("【此前剧情】"), text.index("不要写心理活动"))

    def test_the_two_lists_do_not_overlap(self):
        """一个块既保底又可丢的话，丢它那一轮会静默违反保底承诺。"""
        self.assertEqual(PROTECTED_SECTIONS & set(DROP_ORDER), set())


if __name__ == "__main__":
    unittest.main()
