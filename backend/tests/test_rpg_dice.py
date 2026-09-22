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


class OpposedRateTests(unittest.TestCase):
    """对抗：opposed 换掉「假想对手 10 级」那个基准。

    上面那一整组 ResolveRateTests 一个字都没改，这就是「不传新参数行为不变」
    的护栏——对抗是加出来的一条路，不是改了原来那条。
    """

    def setUp(self):
        self.table = {"trivial": 90, "easy": 75, "medium": 55, "hard": 35, "extreme": 15}

    def test_opposing_a_stronger_rival_hurts_a_weaker_one_helps(self):
        # 敏捷 12 打 14：差 2 点，每点 4% → 55 - 8
        self.assertEqual(resolve_rate(self.table, "medium", 12, opposed=14), 47)
        self.assertEqual(resolve_rate(self.table, "medium", 14, opposed=12), 63)

    def test_zero_is_a_real_opponent_not_a_missing_one(self):
        # 0 是作者明写的「凡人」，不是「没填」。混了的话凡人会比 4 级魔头难打
        self.assertEqual(resolve_rate(self.table, "medium", 3, opposed=0), 67)
        self.assertEqual(resolve_rate(self.table, "medium", 3, opposed=None), 27)
        self.assertNotEqual(
            resolve_rate(self.table, "medium", 3, opposed=0),
            resolve_rate(self.table, "medium", 3, opposed=None),
        )

    def test_opposing_yourself_means_this_stat_does_not_weigh_in(self):
        # 等级项在没有对手时走这一条：差为 0，只剩档位
        for level in (1, 3, 9, 50):
            self.assertEqual(
                resolve_rate(self.table, "medium", level, opposed=level, per_point=15),
                55,
            )

    def test_level_scale_would_die_on_the_default_baseline(self):
        """这条测的是那个 bug 本身：等级尺不能对 STAT_BASELINE 比。

        境界 3 的人如果落回基准 10，(3-10)*15 = -105，练个功都必败。
        所以「没有对手」必须走 opposed=自己，不能走 opposed=None。
        """
        self.assertEqual(
            resolve_rate(self.table, "medium", 3, opposed=None, per_point=15), RATE_MIN,
        )
        self.assertEqual(
            resolve_rate(self.table, "medium", 3, opposed=3, per_point=15), 55,
        )

    def test_per_point_scales_the_gap(self):
        # 同样差 1，等级每级 15 个百分点，普通数值每点 4 个
        self.assertEqual(resolve_rate(self.table, "medium", 3, opposed=4, per_point=15), 40)
        self.assertEqual(resolve_rate(self.table, "medium", 3, opposed=4), 51)

    def test_clamps_still_leave_room_at_both_ends(self):
        # 差 4 级撞底，但底是 5% 不是 0——越级挑战永远有奇迹
        self.assertEqual(
            resolve_rate(self.table, "medium", 1, opposed=5, per_point=15), RATE_MIN,
        )
        self.assertEqual(
            resolve_rate(self.table, "medium", 9, opposed=1, per_point=15), RATE_MAX,
        )

    def test_garbage_opponent_cancels_the_whole_modifier(self):
        # 坏值不该算出「玩家那半边算了、对手那半边没算」的怪数字
        for bad in ("元婴期", object()):
            self.assertEqual(resolve_rate(self.table, "medium", 12, opposed=bad), 55)

    def test_new_params_are_keyword_only(self):
        # 第 4 个位置参数是 bias，别让人把对手的等级传进去当难度旋钮
        with self.assertRaises(TypeError):
            resolve_rate(self.table, "medium", 3, 0, 4)


class LevelLadderTests(unittest.TestCase):
    """等级阶梯的手感护栏，和 FeelTests 同一个理由。

    这张表就是编辑器里那行阶梯预览要显示的东西。谁想动 rank_per_level
    的默认值 15、或者动 NARROW_MARGIN，都得先来这儿重新想一遍。
    """

    PER_LEVEL = 15
    TABLE = {"trivial": 90, "easy": 75, "medium": 55, "hard": 35, "extreme": 15}

    def _rate(self, gap):
        """gap = 玩家等级 − 对手等级。"""
        return resolve_rate(
            self.TABLE, "medium", 5 + gap, opposed=5, per_point=self.PER_LEVEL,
        )

    def test_the_ladder_authors_will_see_in_the_preview(self):
        self.assertEqual(
            {gap: self._rate(gap) for gap in range(-4, 4)},
            {-4: 5, -3: 10, -2: 25, -1: 40, 0: 55, 1: 70, 2: 85, 3: 95},
        )

    def test_being_outclassed_is_never_hopeless(self):
        """险胜档恒定吃 20 个百分点，所以越级挑战不是纯挨打。

        差 3 级仍有三成机会「办成了但付代价」。要「魔尊面前你连出手的
        资格都没有」就得动 classify，那会影响所有模组，不在这一层解决。
        """
        rng = random.Random(20260921)
        counts = Counter(
            roll(self._rate(-3), rng=rng)["outcome"] for _ in range(10000)
        )
        got = (counts["crit_success"] + counts["success"] + counts["narrow"]) / 10000
        self.assertGreaterEqual(got, 0.25)
        self.assertLessEqual(got, 0.35)

    def test_usable_range_is_only_about_three_levels(self):
        """15/级在 medium 档撞顶撞底的位置：−3…+2 之外就没有分辨率了。

        九重境界的模组里，练气对元婴和练气对大乘手感完全一样。这不是 bug，
        是 15 这个默认值的固有量程——阶梯预览存在的理由就是让作者看见它。
        """
        self.assertEqual(self._rate(-4), self._rate(-8))
        self.assertEqual(self._rate(3), self._rate(7))
        self.assertNotEqual(self._rate(-3), self._rate(-2))


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
