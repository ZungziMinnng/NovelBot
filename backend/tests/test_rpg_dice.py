"""判定引擎：分档边界、成功率换算、以及最要紧的——手感。

手感那条测试是这个文件存在的主要理由。分档规则怎么改都能自圆其说，
但改完成功率掉到 30% 就没人愿意玩了，得有个东西拦住。
"""
import random
import unittest
from collections import Counter

from app.services.rpg_dice import (
    BANDS, DEFAULT_BAND, RATE_MAX, RATE_MIN, classify, classify_certain,
    normalize_band, resolve_rate, roll,
)


class BandTests(unittest.TestCase):
    def test_known_bands_pass_through(self):
        for band in BANDS:
            self.assertEqual(normalize_band(band), band)
        self.assertEqual(normalize_band("HARD"), "hard")
        self.assertEqual(normalize_band(" medium "), "medium")

    def test_unknown_band_falls_back_instead_of_raising(self):
        for bad in ("impossible", "", None, 7, "困难"):
            self.assertEqual(normalize_band(bad), DEFAULT_BAND)


class ResolveRateTests(unittest.TestCase):
    def setUp(self):
        self.table = {"trivial": 90, "easy": 75, "medium": 55, "hard": 35, "extreme": 15}

    def test_maps_band_through_module_table(self):
        self.assertEqual(resolve_rate(self.table, "hard", 10), 35)
        self.assertEqual(resolve_rate(self.table, "trivial", 10), 90)

    def test_stat_above_baseline_helps_below_baseline_hurts(self):
        # 15 点比 10 点多 20 个百分点：练了要看得出来
        self.assertEqual(resolve_rate(self.table, "medium", 15), 75)
        self.assertEqual(resolve_rate(self.table, "medium", 5), 35)

    def test_bias_shifts_every_band(self):
        self.assertEqual(resolve_rate(self.table, "medium", 10, 10), 65)
        self.assertEqual(resolve_rate(self.table, "medium", 10, -10), 45)

    def test_always_leaves_room_for_accidents_and_miracles(self):
        self.assertEqual(resolve_rate(self.table, "trivial", 99), RATE_MAX)
        self.assertEqual(resolve_rate(self.table, "extreme", 0, -99), RATE_MIN)

    def test_missing_or_broken_table_uses_builtin_defaults(self):
        self.assertEqual(resolve_rate({}, "hard", 10), 35)
        self.assertEqual(resolve_rate(None, "hard", 10), 35)
        self.assertEqual(resolve_rate({"hard": "很难"}, "hard", 10), 35)

    def test_garbage_stat_is_treated_as_baseline_not_an_exception(self):
        self.assertEqual(resolve_rate(self.table, "medium", None), 55)
        self.assertEqual(resolve_rate(self.table, "medium", "敏捷"), 55)

    def test_unknown_band_resolves_as_medium(self):
        self.assertEqual(resolve_rate(self.table, "impossible", 10), 55)


class ClassifyTests(unittest.TestCase):
    def test_boundaries(self):
        # 掷得越低越好，和成功率同一把尺子
        self.assertEqual(classify(11, 55), "crit_success")  # 55//5 = 11
        self.assertEqual(classify(12, 55), "success")
        self.assertEqual(classify(55, 55), "success")       # 刚好够
        self.assertEqual(classify(56, 55), "narrow")
        self.assertEqual(classify(75, 55), "narrow")        # 险胜的下沿
        self.assertEqual(classify(76, 55), "fail")
        self.assertEqual(classify(96, 55), "crit_fail")

    def test_crit_fail_beats_a_very_high_rate(self):
        # 掷出 96 以上一律大失败，哪怕成功率 95%。玩家会去数这个数字
        self.assertEqual(classify(96, 95), "crit_fail")


class CertainTests(unittest.TestCase):
    """关掉随机后：同一存档重玩，结果必须一样。"""

    def test_bands_by_rate_alone(self):
        self.assertEqual(classify_certain(90), "crit_success")
        self.assertEqual(classify_certain(55), "success")
        self.assertEqual(classify_certain(40), "narrow")
        self.assertEqual(classify_certain(20), "fail")

    def test_roll_without_random_is_reproducible_and_hides_the_die(self):
        first = roll(55, random_check=False)
        self.assertEqual(first, roll(55, random_check=False))
        # dice 为 0，前端据此只显示成功率不显示掷点
        self.assertEqual(first["dice"], 0)


class FeelTests(unittest.TestCase):
    """手感护栏。数字变了就该有人来重新想一遍，而不是悄悄让游戏变难。"""

    def _distribution(self, rate, n=10000, seed=20260911):
        rng = random.Random(seed)
        counts = Counter(roll(rate, rng=rng)["outcome"] for _ in range(n))
        return {k: v / n for k, v in counts.items()}

    def test_medium_check_with_a_modest_bonus_is_a_coin_flip(self):
        # 数值 14 对普通难度：55 + 4*4 = 71%，这是最典型的一次判定
        p = self._distribution(71)
        clean = p.get("crit_success", 0) + p.get("success", 0)
        self.assertGreaterEqual(clean, 0.65)
        self.assertLessEqual(clean, 0.75)

    def test_pure_failure_stays_rare_enough_to_keep_playing(self):
        # 「什么都没做成」才是劝退的那一档，险胜不算
        p = self._distribution(71)
        flat = p.get("fail", 0) + p.get("crit_fail", 0)
        self.assertLessEqual(flat, 0.15)

    def test_hard_check_is_hard_but_not_hopeless(self):
        p = self._distribution(35)
        clean = p.get("crit_success", 0) + p.get("success", 0)
        self.assertGreaterEqual(clean, 0.25)
        self.assertLessEqual(clean, 0.45)

    def test_roll_reports_everything_the_player_watches(self):
        result = roll(63, rng=random.Random(1))
        self.assertEqual(result["rate"], 63)
        self.assertIn(result["dice"], range(1, 101))
        self.assertIn(result["outcome"], set(
            ("crit_success", "success", "narrow", "fail", "crit_fail")
        ))


if __name__ == "__main__":
    unittest.main()
