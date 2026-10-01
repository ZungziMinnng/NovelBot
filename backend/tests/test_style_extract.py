"""文风库导入的确定性部分。全部用构造文本，不碰任何真实书。"""
import re
import unittest

from app.services import style_extract as se


def _chapter_body(i: int, paras: int = 12) -> str:
    return "\n".join(
        f"第{i}章第{p}段，他走过长街，风从巷口灌进来。“你来了。”她说。" * 2
        for p in range(paras)
    )


def _book(n: int) -> str:
    parts = ["简介：这是一本书。"]
    for i in range(1, n + 1):
        parts.append(f"第{i}章 标题{i}\n{_chapter_body(i)}")
    return "\n".join(parts)


class DecodeTests(unittest.TestCase):
    def test_gbk_and_utf8_bom(self):
        text = "第一章 开端\n他推开门。"
        self.assertEqual(se.decode_text(text.encode("gbk")), text)
        self.assertEqual(se.decode_text(text.encode("utf-8-sig")), text)

    def test_crlf_normalized(self):
        self.assertEqual(se.decode_text("甲\r\n乙\r丙".encode()), "甲\n乙\n丙")


class SplitTests(unittest.TestCase):
    def test_chapter_heads_split_and_preface_dropped(self):
        chapters = se.split_chapters(_book(5))
        self.assertEqual(len(chapters), 5)
        self.assertNotIn("简介", chapters[0])
        self.assertNotIn("标题1", chapters[0])

    def test_chinese_numerals_and_hui(self):
        text = "第一回 甲\n正文一\n第二十三回 乙\n正文二"
        self.assertEqual(se.split_chapters(text), ["正文一", "正文二"])

    def test_heading_mentioned_mid_sentence_is_not_a_chapter(self):
        text = "第1章\n他说起第3章的事情，还没讲完。\n第2章\n正文"
        self.assertEqual(len(se.split_chapters(text)), 2)

    def test_no_heads_falls_back_to_size(self):
        text = "\n".join("没有章节标记的一段话。" * 10 for _ in range(200))
        chapters = se.split_chapters(text)
        self.assertGreater(len(chapters), 1)
        self.assertEqual("".join(chapters).replace("\n", ""), text.replace("\n", ""))


class ChunkTests(unittest.TestCase):
    def test_chunk_bounds(self):
        for c in se._chunks(_chapter_body(1, 40)):
            self.assertGreaterEqual(len(c.replace("\n", "")), se._CHUNK_MIN)
            self.assertLessEqual(len(c.replace("\n", "")), se._CHUNK_MAX)

    def test_oversized_paragraph_dropped_but_neighbours_kept(self):
        short = "短段落，写一点东西凑字数。" * 5
        chapter = "\n".join([short, short, "长" * (se._CHUNK_MAX + 1), short, short])
        chunks = se._chunks(chapter)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all("长长" not in c for c in chunks))


class SampleTests(unittest.TestCase):
    def test_spread_over_whole_book(self):
        chapters = se.split_chapters(_book(120))
        chunks = se.sample_chunks(chapters, seed=1)
        self.assertLessEqual(len(chunks), se._SAMPLE_BUCKETS * se._CHUNKS_PER_CHAPTER)
        # 最后一份（第 111~120 章）也要被抽到，不能只抽开头
        numbers = {int(re.match(r"第(\d+)章", c).group(1)) for c in chunks}
        self.assertGreater(max(numbers), 110)
        self.assertLess(min(numbers), 11)

    def test_short_book_and_empty(self):
        self.assertTrue(se.sample_chunks(se.split_chapters(_book(3)), seed=1))
        self.assertEqual(se.sample_chunks([]), [])

    def test_deterministic_with_seed(self):
        chapters = se.split_chapters(_book(50))
        self.assertEqual(se.sample_chunks(chapters, seed=7), se.sample_chunks(chapters, seed=7))


class StatsTests(unittest.TestCase):
    def test_values(self):
        stats = se.compute_stats(["他走了。“好。”\n她说。", "他停下。"])
        # 去空白后 15 字、4 句、3 段；引号部分「“好。”」4 字
        self.assertEqual(stats["avg_sentence_len"], 4)
        self.assertEqual(stats["avg_para_len"], 5)
        self.assertEqual(stats["dialogue_ratio"], round(4 / 15, 2))
        self.assertEqual(stats["person"], "第三人称")

    def test_first_person_ignores_quotes(self):
        self.assertEqual(se.compute_stats(["我推开门。我看见他。"])["person"], "第一人称")
        # 台词里的「我」不算叙述视角
        self.assertEqual(se.compute_stats(["他说：“我我我我。”他走了。"])["person"], "第三人称")

    def test_empty(self):
        self.assertEqual(se.compute_stats([])["avg_sentence_len"], 0)


class CandidateTests(unittest.TestCase):
    def _fight(self, text):
        return se.keyword_score(text, se.PRESET_KEYWORDS["打斗"])

    def test_keyword_score_ranks_fighting_above_plain(self):
        pool = [
            (0, "他走过长街，风从巷口灌进来，街上没有人，灯也没亮。"),
            (0, "萧炎挥剑斩向对面，剑光如雪，对面举刀硬挡，被震退三步。"),
        ]
        self.assertEqual(se.pick_candidates(pool, self._fight), [pool[1][1]])  # 零分的不要

    def test_per_chapter_cap(self):
        pool = [(0, f"他挥剑斩过去，第{i}块。") for i in range(5)]
        pool.append((1, "他挥剑斩过去，另一章。"))

        picked = se.pick_candidates(pool, self._fight)

        self.assertEqual(len(picked), 3)
        self.assertEqual(len([t for t in picked if "另一章" not in t]), 2)
        self.assertIn("他挥剑斩过去，另一章。", picked)

    def test_empty_pool(self):
        self.assertEqual(se.pick_candidates([], se.dialogue_score), [])

    def test_dialogue_score_prefers_quotes(self):
        self.assertGreater(
            se.dialogue_score("“你来了。”她说。"), se.dialogue_score("他走过长街，风从巷口灌进来。")
        )
        self.assertEqual(se.dialogue_score(""), 0)

    def test_find_in_tolerates_whitespace_but_not_edits(self):
        text = "萧炎挥剑\n斩向对面，剑光如雪。"
        self.assertTrue(se.find_in("萧炎挥剑斩向 对面", [text]))
        self.assertFalse(se.find_in("萧炎挥刀斩向对面", [text]))
        self.assertFalse(se.find_in("  ", [text]))

    def test_all_chunks_tags_chapter_index(self):
        chunks = se.all_chunks([_chapter_body(1), _chapter_body(2)])
        self.assertEqual({i for i, _ in chunks}, {0, 1})
        for index, text in chunks:
            self.assertIn(f"第{index + 1}章", text)


if __name__ == "__main__":
    unittest.main()
