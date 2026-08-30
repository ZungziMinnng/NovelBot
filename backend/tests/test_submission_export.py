import unittest
import io
import zipfile
from types import SimpleNamespace

from app.services import exporter, sensitive_check


def _chapter(number, title, content):
    return SimpleNamespace(number=number, title=title, content=content)


def _novel(title="测试书", blurb="", tags=None):
    return SimpleNamespace(title=title, blurb=blurb, submission_tags=tags or [])


class ExportTests(unittest.TestCase):
    def test_strips_model_appended_plot_options(self):
        """模型常在章末附「接下来可以这样发展：A/B/C」，投稿稿件里绝不能带。"""
        ch = _chapter(1, "开局", "正文结束。\n\n接下来剧情可以这样发展：\nA. 甲\nB. 乙")
        txt = exporter.build_single_txt(_novel(), [ch])
        self.assertIn("正文结束。", txt)
        self.assertNotIn("接下来剧情", txt)
        self.assertNotIn("A. 甲", txt)

    def test_blurb_and_tags_go_in_header(self):
        txt = exporter.build_single_txt(_novel(blurb="一句简介", tags=["重生", "系统"]), [])
        self.assertIn("【简介】", txt)
        self.assertIn("一句简介", txt)
        self.assertIn("重生 系统", txt)

    def test_header_omitted_when_metadata_blank(self):
        txt = exporter.build_single_txt(_novel(), [_chapter(1, "", "内容")])
        self.assertNotIn("【简介】", txt)
        self.assertNotIn("【标签】", txt)

    def test_chapter_heading_handles_empty_title(self):
        self.assertEqual(exporter.chapter_heading(_chapter(3, "", "x")), "第3章")
        self.assertEqual(exporter.chapter_heading(_chapter(3, "归来", "x")), "第3章 归来")

    def test_filename_strips_illegal_characters(self):
        self.assertEqual(exporter.safe_filename('书:名/带*非法?字符'), "书_名_带_非法_字符")
        self.assertEqual(exporter.safe_filename(""), "未命名")
        self.assertLessEqual(len(exporter.safe_filename("长" * 200)), 80)

    def test_zip_entries_are_zero_padded_for_ordering(self):
        chapters = [_chapter(2, "乙", "内容2"), _chapter(10, "丙", "内容10")]
        with zipfile.ZipFile(io.BytesIO(exporter.build_chapter_zip(_novel(), chapters))) as zf:
            names = zf.namelist()
            self.assertEqual(names, sorted(names), "文件名排序必须与章节顺序一致")
            self.assertIn("0002_乙.txt", names)
            self.assertIn("0010_丙.txt", names)


class SensitiveCheckTests(unittest.TestCase):
    def test_no_categories_and_no_custom_means_no_wordlist(self):
        """默认全关：不勾类别、没有自定义词时必须完全不检查（要写 NSFW 的场景）。"""
        self.assertEqual(sensitive_check.build_wordlist([], []), [])

    def test_unchecked_category_does_not_match(self):
        wordlist = sensitive_check.build_wordlist(["real_brand"], [])
        hits = sensitive_check.scan_text("他赤裸着上身，喝了瓶可乐。", wordlist)
        self.assertEqual([h["word"] for h in hits], [])

    def test_checked_category_matches_with_excerpt(self):
        wordlist = sensitive_check.build_wordlist(["real_brand"], [])
        hits = sensitive_check.scan_text("他打开了微信。", wordlist)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["word"], "微信")
        self.assertEqual(hits[0]["category"], "real_brand")
        self.assertIn("微信", hits[0]["excerpt"])

    def test_custom_words_are_tagged_custom(self):
        wordlist = sensitive_check.build_wordlist([], ["自造敏感词"])
        hits = sensitive_check.scan_text("这里有自造敏感词。", wordlist)
        self.assertEqual(hits[0]["category"], "custom")

    def test_duplicate_words_are_deduped(self):
        wordlist = sensitive_check.build_wordlist(["real_brand"], ["微信"])
        self.assertEqual([w for w, _ in wordlist].count("微信"), 1)

    def test_repeated_hits_are_capped(self):
        wordlist = sensitive_check.build_wordlist([], ["啊"])
        hits = sensitive_check.scan_text("啊" * 100, wordlist)
        self.assertLessEqual(len(hits), 20)

    def test_positions_advance_past_each_match(self):
        wordlist = sensitive_check.build_wordlist([], ["微信"])
        hits = sensitive_check.scan_text("微信和微信", wordlist)
        self.assertEqual([h["position"] for h in hits], [0, 3])

    def test_politics_category_ships_empty_by_design(self):
        """政治类清单各平台不同，默认留空由用户自己填。"""
        baseline = sensitive_check.load_baseline()
        self.assertIn("politics", baseline)
        self.assertEqual(baseline["politics"]["words"], [])


if __name__ == "__main__":
    unittest.main()
