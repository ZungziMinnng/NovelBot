import unittest
from types import SimpleNamespace

from app.services.relevance_selector import (
    keyword_hits,
    recency_factor,
    rerank_by_importance,
    select_by_name_then_rag,
    select_notes_by_title_then_rag,
)
from app.services.text_ranking import bm25_rank, rrf_fuse


def _items(n: int) -> list:
    return [SimpleNamespace(id=i, name=f"实体{i}号") for i in range(n)]


class FallbackLimitTests(unittest.TestCase):
    def test_full_fallback_capped(self):
        result = select_by_name_then_rag(
            _items(50), [], "无关查询", fallback_limit=10,
        )
        self.assertEqual(result.source, "full")
        self.assertEqual(len(result.items), 10)

    def test_zero_limit_keeps_all(self):
        result = select_by_name_then_rag(_items(50), [], "无关查询")
        self.assertEqual(result.source, "full")
        self.assertEqual(len(result.items), 50)

    def test_name_match_not_affected_by_limit(self):
        items = _items(50)
        query = "、".join(i.name for i in items)
        result = select_by_name_then_rag(items, [], query, fallback_limit=10)
        self.assertEqual(result.source, "name")
        self.assertEqual(len(result.items), 50)

    def test_rag_match_not_affected_by_limit(self):
        items = _items(20)
        hits = [{"metadata": {"entity_id": i}} for i in range(15)]
        result = select_by_name_then_rag(items, hits, "无关查询", fallback_limit=5)
        self.assertEqual(result.source, "rag")
        self.assertEqual(len(result.items), 15)


class RecencyDecayTests(unittest.TestCase):
    def test_factor_bounds(self):
        self.assertEqual(recency_factor(100, 100), 1.0)
        self.assertEqual(recency_factor(None, 100), 1.0)
        self.assertEqual(recency_factor("abc", 100), 1.0)
        # 久远章节渐近 0.7 封底，不会归零
        self.assertGreater(recency_factor(1, 1000), 0.7)
        self.assertLess(recency_factor(1, 1000), 0.75)

    def test_recent_wins_when_otherwise_equal(self):
        hits = [
            {"distance": 0.3, "metadata": {"importance": 3, "chapter_number": 1}},
            {"distance": 0.3, "metadata": {"importance": 3, "chapter_number": 99}},
        ]
        ranked = rerank_by_importance(hits, 2, current_chapter=100)
        self.assertEqual(ranked[0]["metadata"]["chapter_number"], 99)

    def test_high_importance_old_hit_survives(self):
        hits = [
            {"distance": 0.3, "metadata": {"importance": 5, "chapter_number": 1}},
            {"distance": 0.3, "metadata": {"importance": 3, "chapter_number": 99}},
        ]
        ranked = rerank_by_importance(hits, 2, current_chapter=100)
        self.assertEqual(ranked[0]["metadata"]["importance"], 5)

    def test_no_current_chapter_no_decay(self):
        hits = [
            {"distance": 0.3, "metadata": {"importance": 3, "chapter_number": 1}},
            {"distance": 0.4, "metadata": {"importance": 3, "chapter_number": 99}},
        ]
        ranked = rerank_by_importance(hits, 2)
        self.assertEqual(ranked[0]["metadata"]["chapter_number"], 1)


class FragmentMatchTests(unittest.TestCase):
    def _select(self, names, query):
        items = [SimpleNamespace(id=i, name=n) for i, n in enumerate(names)]
        return select_by_name_then_rag(items, [], query, allow_full=False)

    def test_abbreviation_hits_unique_fragment(self):
        result = self._select(
            ["天地十三法则之法则五", "极阴寒玉戒尺"],
            "本章主角以法则五御敌",
        )
        self.assertEqual(result.source, "name")
        self.assertEqual([i.name for i in result.items], ["天地十三法则之法则五"])

    def test_ambiguous_fragment_no_match(self):
        result = self._select(
            [f"天地十三法则之法则{c}" for c in "一二三"],
            "他试图参悟法则",
        )
        self.assertEqual(result.items, [])

    def test_two_char_abbreviation(self):
        result = self._select(["极阴寒玉戒尺", "天地十三法则之法则五"], "她抽出戒尺")
        self.assertEqual([i.name for i in result.items], ["极阴寒玉戒尺"])
        # 出现第二把带「戒尺」的道具后片段歧义，静默退回 RAG 兜底
        result = self._select(["极阴寒玉戒尺", "紫金戒尺"], "她抽出戒尺")
        self.assertEqual(result.items, [])

    def test_full_name_and_fragment_combine(self):
        result = self._select(
            ["极阴寒玉戒尺", "天地十三法则之法则五"],
            "极阴寒玉戒尺蕴含法则五之力",
        )
        self.assertEqual(result.source, "name")
        self.assertEqual(len(result.items), 2)

    def test_notes_title_fragment(self):
        notes = [SimpleNamespace(id=1, title="裴云霁调教手册", content="")]
        result = select_notes_by_title_then_rag(notes, [], "翻开调教手册", allow_full=False)
        self.assertEqual(result.source, "name")
        self.assertEqual(len(result.items), 1)


class KeywordHitsTests(unittest.TestCase):
    def _summaries(self, *contents):
        return [
            {"chapter_number": i + 1, "content": c}
            for i, c in enumerate(contents)
        ]

    def test_distinctive_phrase_hits_old_chapter(self):
        summaries = self._summaries(
            "主角修为提升，从练气到筑基，对外谎称观月华顿悟所致。",
            "主角在坊市购买丹药。",
            "主角与同门切磋获胜。",
        )
        hits = keyword_hits("众人再次提起月华顿悟之事", summaries)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["chapter_number"], 1)

    def test_high_df_gram_filtered(self):
        # 出现在全部摘要里的短语（如主角名相关）不算证据
        summaries = self._summaries(*[
            f"叶凡真人今日做了第{i}件事。" for i in range(20)
        ])
        hits = keyword_hits("叶凡真人在山门前驻足", summaries)
        self.assertEqual(hits, [])

    def test_no_cjk_query_returns_empty(self):
        summaries = self._summaries("主角观月华顿悟突破。")
        self.assertEqual(keyword_hits("abc 123", summaries), [])
        self.assertEqual(keyword_hits("", summaries), [])

    def test_top_k_and_ordering_by_match_count(self):
        summaries = self._summaries(
            "师尊将弟子逐出宗门。",                      # 1 gram
            "师尊护短，把欺负主角的弟子逐出宗门并废其修为。",  # 更多 gram
            "无关章节内容。",
        )
        hits = keyword_hits("再提师尊把那弟子逐出宗门废其修为的旧事", summaries, top_k=1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["chapter_number"], 2)


class Bm25RankTests(unittest.TestCase):
    def _candidates(self, *contents):
        return [
            {"text": c, "metadata": {"chapter_number": i + 1, "importance": 3}}
            for i, c in enumerate(contents)
        ]

    def test_proper_noun_ranks_matching_chapter_first(self):
        candidates = self._candidates(
            "主角在坊市购买丹药，与摊主讨价还价。",
            "主角于秘境中拔出玄天剑，剑身雷光大盛。",
            "主角与同门切磋获胜，赢得彩头。",
        )
        hits = bm25_rank("玄天剑再度出鞘", candidates, top_k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["metadata"]["chapter_number"], 2)
        self.assertIn("bm25_score", hits[0])

    def test_empty_inputs_return_empty(self):
        candidates = self._candidates("主角观月华顿悟。")
        self.assertEqual(bm25_rank("", candidates, top_k=3), [])
        self.assertEqual(bm25_rank("玄天剑", [], top_k=3), [])
        self.assertEqual(bm25_rank("玄天剑", candidates, top_k=0), [])

    def test_all_empty_docs_return_empty(self):
        candidates = [{"text": "", "metadata": {"chapter_number": 1}}]
        self.assertEqual(bm25_rank("玄天剑", candidates, top_k=3), [])

    def test_top_k_truncation(self):
        # 查询词出现在部分（而非全部）文档中，IDF 才为正、得分>0
        candidates = self._candidates(
            "玄天剑出鞘。", "玄天剑折断。", "玄天剑重铸。",
            "主角在坊市购买丹药。", "主角与同门切磋。",
        )
        hits = bm25_rank("玄天剑", candidates, top_k=2)
        self.assertEqual(len(hits), 2)


class RrfFuseTests(unittest.TestCase):
    _key = staticmethod(lambda h: (h.get("metadata") or {}).get("chapter_number"))

    def test_double_hit_ranks_first_and_keeps_vector_fields(self):
        vector_ranked = [
            {"text": "A", "distance": 0.1, "metadata": {"chapter_number": 1}},
            {"text": "B", "distance": 0.2, "metadata": {"chapter_number": 2}},
        ]
        bm25_ranked = [
            {"text": "B'", "bm25_score": 9.0, "metadata": {"chapter_number": 2}},
            {"text": "C", "bm25_score": 5.0, "metadata": {"chapter_number": 3}},
        ]
        fused = rrf_fuse(vector_ranked, bm25_ranked, key=self._key)
        # 两路都命中的第2章融合分最高；去重保留向量侧 dict（带 distance）
        self.assertEqual([self._key(h) for h in fused], [2, 1, 3])
        self.assertIn("distance", fused[0])
        self.assertNotIn("bm25_score", fused[0])

    def test_single_list_passthrough(self):
        ranked = [
            {"text": "A", "metadata": {"chapter_number": 1}},
            {"text": "B", "metadata": {"chapter_number": 2}},
        ]
        fused = rrf_fuse(ranked, [], key=self._key)
        self.assertEqual([self._key(h) for h in fused], [1, 2])

    def test_both_empty(self):
        self.assertEqual(rrf_fuse([], [], key=self._key), [])


if __name__ == "__main__":
    unittest.main()
