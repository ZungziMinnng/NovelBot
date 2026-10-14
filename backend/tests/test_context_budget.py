import unittest

from app.services.context_budget import (
    build_context_budget,
    estimate_tokens,
    truncate_to_token_budget,
)
from app.services.relevance_selector import diversify_historical_hits


class ContextBudgetTests(unittest.TestCase):
    def test_input_budget_follows_window_not_output(self):
        # 65536 窗口：扣掉输出 5250、思考 1313、安全 6554 后全给输入
        budget = build_context_budget(target_words=3500, context_window=65536)
        self.assertEqual(budget.output_reserve, 5250)
        self.assertEqual(budget.input_budget, 65536 - 5250 - 1313 - 6554)

    def test_large_window_is_capped(self):
        budget = build_context_budget(target_words=5000, context_window=1_000_000)
        self.assertEqual(budget.input_budget, 64000)

    def test_small_model_window_is_a_hard_limit(self):
        budget = build_context_budget(target_words=8000, context_window=32768)
        available = (
            budget.context_window
            - budget.output_reserve
            - budget.thinking_reserve
            - budget.safety_reserve
        )
        self.assertEqual(budget.input_budget, available)
        self.assertLess(budget.input_budget, 18000)

    def test_tail_truncation_respects_budget(self):
        text = "开头" * 1000 + "关键结尾"
        truncated = truncate_to_token_budget(text, 100, keep_end=True)
        self.assertLessEqual(estimate_tokens(truncated), 102)
        self.assertTrue(truncated.endswith("关键结尾"))

    def test_historical_hits_are_spread_across_time_buckets(self):
        hits = [
            {"metadata": {"chapter_number": chapter}, "text": str(chapter)}
            for chapter in (1, 2, 3, 4, 11, 12)
        ]
        selected = diversify_historical_hits(hits, 4)
        chapters = [hit["metadata"]["chapter_number"] for hit in selected]
        self.assertEqual(chapters, [1, 2, 11, 12])


if __name__ == "__main__":
    unittest.main()
