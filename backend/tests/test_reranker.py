"""重排模块测试：按分数重排、头部截取、不可用降级。"""
import unittest
from unittest.mock import patch

from app.services import reranker


class _FakeModel:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def predict(self, pairs):
        self.calls.append(pairs)
        return self.scores[:len(pairs)]


class _FailingModel:
    def predict(self, pairs):
        raise RuntimeError("cuda out of memory")


def _hits(n):
    return [{"text": f"第{i}章摘要", "metadata": {"chapter_number": i}} for i in range(1, n + 1)]


class RerankHitsTests(unittest.TestCase):
    def test_reorders_by_score(self):
        hits = _hits(3)
        model = _FakeModel([0.1, 0.9, 0.5])
        with patch.object(reranker, "_get_model", return_value=model):
            result, applied = reranker.rerank_hits("查询", hits)
        self.assertTrue(applied)
        self.assertEqual([h["metadata"]["chapter_number"] for h in result], [2, 3, 1])
        # 打分输入是 (query, 摘要原文) 成对文本
        self.assertEqual(model.calls[0][0], ("查询", "第1章摘要"))

    def test_candidate_k_only_reranks_head(self):
        hits = _hits(5)
        model = _FakeModel([0.1, 0.9, 0.5])
        with patch.object(reranker, "_get_model", return_value=model):
            result, applied = reranker.rerank_hits("查询", hits, candidate_k=3)
        self.assertTrue(applied)
        # 头部按分数重排，尾部保持原序拼回
        self.assertEqual([h["metadata"]["chapter_number"] for h in result], [2, 3, 1, 4, 5])

    def test_model_unavailable_returns_unchanged(self):
        hits = _hits(3)
        with patch.object(reranker, "_get_model", return_value=None):
            result, applied = reranker.rerank_hits("查询", hits)
        self.assertFalse(applied)
        self.assertEqual(result, hits)

    def test_predict_failure_degrades(self):
        hits = _hits(3)
        with patch.object(reranker, "_get_model", return_value=_FailingModel()):
            result, applied = reranker.rerank_hits("查询", hits)
        self.assertFalse(applied)
        self.assertEqual(result, hits)

    def test_trivial_input_skips_model(self):
        with patch.object(reranker, "_get_model", side_effect=AssertionError("不应加载模型")):
            result, applied = reranker.rerank_hits("", _hits(3))
            self.assertFalse(applied)
            result, applied = reranker.rerank_hits("查询", _hits(1))
            self.assertFalse(applied)

    def test_unavailable_flag_stops_retry(self):
        with patch.object(reranker, "_model", None), patch.object(reranker, "_unavailable", True):
            self.assertIsNone(reranker._get_model())


if __name__ == "__main__":
    unittest.main()
