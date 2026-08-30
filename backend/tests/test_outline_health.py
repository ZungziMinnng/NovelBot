"""大纲体检：章节配比、爽点密度、钩子重复、字数比、卷级库存三问。"""
import unittest

from app.services import outline_health


def ch(n, role="推进", tone="平稳", intensity=3, hook="突然揭示", strength=3,
       content="x" * 60, words=180):
    return {
        "chapter_number": n, "chapter_role": role, "emotion_tone": tone,
        "emotion_intensity": intensity, "hook_type": hook, "hook_strength": strength,
        "content": content, "word_count": words,
    }


def labels(findings):
    return " | ".join(f["label"] for f in findings)


class EmptyAndUnplannedTests(unittest.TestCase):
    def test_no_outlines_no_findings(self):
        self.assertEqual(outline_health.check_chapter_outlines([]), [])

    def test_all_unplanned_warns(self):
        rows = [ch(i, role="") for i in range(1, 11)]
        out = outline_health.check_chapter_outlines(rows)
        self.assertIn("10/10 章没有执行计划", labels(out))
        self.assertEqual([f for f in out if "没有执行计划" in f["label"]][0]["level"], "warn")

    def test_partial_unplanned_is_info(self):
        rows = [ch(i) for i in range(1, 10)] + [ch(10, role="")]
        out = outline_health.check_chapter_outlines(rows)
        hit = [f for f in out if "没有执行计划" in f["label"]]
        self.assertEqual(hit[0]["level"], "info")

    def test_role_mix_only_counts_planned(self):
        """未规划的章不该被算进配比分母，否则"高压偏少"是假警报。"""
        rows = [ch(i, role="高压") for i in range(1, 3)] + [ch(i, role="") for i in range(3, 21)]
        out = outline_health.check_chapter_outlines(rows)
        self.assertNotIn("高压章偏少", labels(out))


class RoleMixTests(unittest.TestCase):
    def _balanced(self):
        """按配比中值造一份健康大纲：高压3 推进9 修炼2 关系回收2 低压2 信息整理1 = 19。
        钩子轮换、高压章给足强度，避免踩到其他检查项。"""
        from app.services.outline_plan import HOOK_TYPES
        plan = [("高压", 3), ("推进", 9), ("修炼试错", 2), ("关系回收", 2),
                ("低压生活", 2), ("信息整理", 1)]
        # 轮转发牌，把高压章摊到全程，别让 9 章推进挤成一段造出爽点断档
        pools = [[role] * count for role, count in plan]
        roles = []
        while any(pools):
            for pool in pools:
                if pool:
                    roles.append(pool.pop())
        return [
            ch(i + 1, role=role,
               intensity=5 if role == "高压" else 3,
               hook=HOOK_TYPES[i % len(HOOK_TYPES)])
            for i, role in enumerate(roles)
        ]

    def test_balanced_outline_has_no_role_warning(self):
        out = outline_health.check_chapter_outlines(self._balanced())
        self.assertNotIn("偏少", labels(out))
        self.assertNotIn("偏多", labels(out))
        self.assertNotIn("合计", labels(out))

    def test_too_many_idle_chapters(self):
        rows = [ch(i, role="低压生活") for i in range(1, 8)] + [ch(i, role="推进") for i in range(8, 21)]
        out = outline_health.check_chapter_outlines(rows)
        self.assertIn("低压生活加信息整理合计", labels(out))

    def test_no_high_pressure_warns(self):
        rows = [ch(i, role="推进") for i in range(1, 21)]
        self.assertIn("高压章偏少", labels(outline_health.check_chapter_outlines(rows)))


class PayoffDensityTests(unittest.TestCase):
    def test_no_payoff_at_all_warns(self):
        rows = [ch(i, role="推进", intensity=2) for i in range(1, 16)]
        self.assertIn("全程没有高强度爽点章", labels(outline_health.check_chapter_outlines(rows)))

    def test_short_outline_no_payoff_is_silent(self):
        """只规划了三四章就报"没有爽点"是噪音。"""
        rows = [ch(i, role="推进", intensity=2) for i in range(1, 4)]
        self.assertNotIn("全程没有高强度爽点章", labels(outline_health.check_chapter_outlines(rows)))

    def test_gap_longer_than_interval_warns(self):
        rows = [ch(1, role="高压", intensity=5)]
        rows += [ch(i, role="推进", intensity=2) for i in range(2, 15)]
        out = outline_health.check_chapter_outlines(rows)
        self.assertIn("没有高强度爽点", labels(out))

    def test_regular_payoffs_no_warning(self):
        rows = []
        for i in range(1, 22):
            if i % 7 == 0:
                rows.append(ch(i, role="高压", intensity=5))
            else:
                rows.append(ch(i, role="推进", intensity=3))
        out = outline_health.check_chapter_outlines(rows)
        self.assertNotIn("没有高强度爽点", labels(out))


class HookTests(unittest.TestCase):
    def test_same_hook_three_in_a_row_warns(self):
        rows = [ch(i, hook="倒计时") for i in range(1, 4)]
        self.assertIn("连用超过", labels(outline_health.check_chapter_outlines(rows)))

    def test_two_in_a_row_is_fine(self):
        rows = [ch(1, hook="倒计时"), ch(2, hook="倒计时"), ch(3, hook="留白")]
        self.assertNotIn("连用超过", labels(outline_health.check_chapter_outlines(rows)))

    def test_blank_hooks_dont_count_as_a_run(self):
        """一串未规划的章不该被当成"同一钩子连用"。"""
        rows = [ch(i, hook="") for i in range(1, 8)]
        self.assertNotIn("连用超过", labels(outline_health.check_chapter_outlines(rows)))

    def test_weak_hook_strength_reported_as_info(self):
        rows = [ch(i, hook="留白", strength=1) for i in range(1, 4)]
        out = outline_health.check_chapter_outlines(rows)
        hit = [f for f in out if "钩子强度低于" in f["label"]]
        self.assertTrue(hit)
        self.assertEqual(hit[0]["level"], "info")


class OutlineProseRatioTests(unittest.TestCase):
    def test_too_few_samples_no_conclusion(self):
        rows = [ch(1, content="x" * 50, words=5000), ch(2, content="x" * 50, words=5000)]
        self.assertNotIn("偏薄", labels(outline_health.check_chapter_outlines(rows)))

    def test_thin_outline_reported(self):
        rows = [ch(i, content="x" * 50, words=5000) for i in range(1, 6)]
        self.assertIn("偏薄", labels(outline_health.check_chapter_outlines(rows)))

    def test_unwritten_chapters_excluded(self):
        """没写正文的章（word_count=0）不参与字数比，否则全书都报"没写开"。"""
        rows = [ch(i, content="x" * 50, words=0) for i in range(1, 11)]
        out = labels(outline_health.check_chapter_outlines(rows))
        self.assertNotIn("没写开", out)
        self.assertNotIn("偏薄", out)

    def test_healthy_ratio_silent(self):
        rows = [ch(i, content="x" * 100, words=300) for i in range(1, 8)]
        out = labels(outline_health.check_chapter_outlines(rows))
        self.assertNotIn("偏薄", out)
        self.assertNotIn("没写开", out)


class VolumeReserveTests(unittest.TestCase):
    HEALTHY = {
        "endgame_cards": "主角身世\n大反派真身\n世界真相",
        "tier_count": 9, "words_per_tier": 40000,
        "spent_payoffs": "灭门真相",
    }

    def test_healthy_volume_no_warnings(self):
        out = outline_health.check_volume_reserves(self.HEALTHY, 300000)
        self.assertEqual([f for f in out if f["level"] == "warn"], [])

    def test_no_endgame_cards_warns(self):
        vol = {**self.HEALTHY, "endgame_cards": ""}
        self.assertIn("没有登记留到结尾", labels(outline_health.check_volume_reserves(vol, 300000)))

    def test_one_card_left_warns(self):
        vol = {**self.HEALTHY, "endgame_cards": "主角身世", "spent_payoffs": ""}
        self.assertIn("只剩 1 张", labels(outline_health.check_volume_reserves(vol, 300000)))

    def test_tiers_cannot_fill_target(self):
        vol = {**self.HEALTHY, "tier_count": 3, "words_per_tier": 20000}
        out = labels(outline_health.check_volume_reserves(vol, 300000))
        self.assertIn("实力档位撑不满全书", out)

    def test_no_target_words_skips_arithmetic(self):
        """未设定预估章数时不该报档位问题——没有分母。"""
        vol = {**self.HEALTHY, "tier_count": 1, "words_per_tier": 1}
        out = labels(outline_health.check_volume_reserves(vol, 0))
        self.assertNotIn("实力档位", out)

    def test_missing_tier_fields_is_info(self):
        vol = {**self.HEALTHY, "tier_count": 0, "words_per_tier": 0}
        hit = [f for f in outline_health.check_volume_reserves(vol, 300000)
               if "实力档位" in f["label"]]
        self.assertEqual(hit[0]["level"], "info")

    def test_spending_faster_than_reserves_warns(self):
        vol = {"endgame_cards": "主角身世\n世界真相",
               "spent_payoffs": "灭门\n夺宝\n屠城\n背叛",
               "tier_count": 9, "words_per_tier": 40000}
        self.assertIn("已用掉", labels(outline_health.check_volume_reserves(vol, 300000)))


if __name__ == "__main__":
    unittest.main()
