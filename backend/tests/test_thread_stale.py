"""长期未回收伏笔的报警，以及 expired 状态不进写作上下文。"""
import unittest

from app.services.thread_selector import (
    STALE_AFTER_CHAPTERS,
    find_stale_threads,
    select_story_threads,
)


def th(tid, status="active", source=1, due=0, importance=3):
    return {
        "id": tid, "kind": "foreshadowing", "title": f"伏笔{tid}", "content": "x",
        "status": status, "source_chapter": source, "due_chapter": due,
        "importance": importance, "resolved_chapter": 0, "related_entities": [],
    }


class FindStaleTests(unittest.TestCase):
    def test_young_thread_not_stale(self):
        self.assertEqual(find_stale_threads([th(1, source=90)], 100), [])

    def test_old_thread_is_stale(self):
        out = find_stale_threads([th(1, source=10)], 100)
        self.assertEqual(len(out), 1)
        self.assertIn("90 章未回收", out[0]["reason"])

    def test_boundary_exactly_at_threshold(self):
        """刚好到阈值就报，差一章不报。"""
        current = 100
        self.assertTrue(find_stale_threads([th(1, source=current - STALE_AFTER_CHAPTERS)], current))
        self.assertFalse(
            find_stale_threads([th(1, source=current - STALE_AFTER_CHAPTERS + 1)], current)
        )

    def test_overdue_beats_age(self):
        """设了回收期限的，过期就报，不必等 50 章。"""
        out = find_stale_threads([th(1, source=98, due=99)], 100)
        self.assertEqual(len(out), 1)
        self.assertIn("第99章的回收期限", out[0]["reason"])

    def test_due_not_yet_passed_is_silent(self):
        self.assertEqual(find_stale_threads([th(1, source=98, due=120)], 100), [])

    def test_only_active_threads_considered(self):
        threads = [
            th(1, status="resolved", source=1),
            th(2, status="abandoned", source=1),
            th(3, status="expired", source=1),
        ]
        self.assertEqual(find_stale_threads(threads, 100), [])

    def test_sorted_oldest_first(self):
        out = find_stale_threads([th(1, source=40), th(2, source=5), th(3, source=20)], 100)
        self.assertEqual([t["id"] for t in out], [2, 3, 1])

    def test_missing_source_chapter_not_stale(self):
        """source_chapter=0 表示没记在哪章埋的，算不出年龄，不报。"""
        self.assertEqual(find_stale_threads([th(1, source=0)], 100), [])


class ExpiredNotInjectedTests(unittest.TestCase):
    def test_expired_excluded_from_writing_context(self):
        """过期伏笔当悬念注入会让模型硬圆，必须和 abandoned 一样排除。

        select_story_threads 只按 status != resolved 分流，所以过滤在查询层，
        这里验证一旦 expired 混进来会被当活跃条目——即查询层的过滤是必需的。
        """
        kept = select_story_threads([th(1, status="expired")], 100)
        self.assertEqual(len(kept), 1, "select_story_threads 不负责剔除 expired，"
                                       "context_builder 的查询必须自己过滤")


if __name__ == "__main__":
    unittest.main()
