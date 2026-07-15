import unittest

from app.services.thread_selector import cap_glossary, select_story_threads


def _thread(**kwargs) -> dict:
    base = {
        "kind": "foreshadow",
        "title": "线索",
        "content": "内容" * 20,
        "status": "active",
        "source_chapter": 1,
        "due_chapter": None,
        "resolved_chapter": None,
        "resolution": "",
        "known_by": [],
        "related_entities": [],
        "importance": 3,
    }
    base.update(kwargs)
    return base


class SelectStoryThreadsTests(unittest.TestCase):
    def test_old_resolved_threads_are_dropped(self):
        threads = [
            _thread(status="resolved", resolved_chapter=10),
            _thread(status="resolved", resolved_chapter=90),
        ]
        result = select_story_threads(threads, current_chapter=100)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["resolved_chapter"], 90)

    def test_recent_resolved_marked_compact(self):
        threads = [_thread(status="resolved", resolved_chapter=95)]
        result = select_story_threads(threads, current_chapter=100)
        self.assertTrue(result[0]["compact"])

    def test_active_threads_within_budget_all_kept(self):
        threads = [_thread(importance=2) for _ in range(5)]
        result = select_story_threads(threads, current_chapter=50)
        self.assertEqual(len(result), 5)

    def test_low_importance_dropped_when_over_budget(self):
        big = "字" * 900
        threads = [_thread(importance=2, content=big) for _ in range(10)]
        result = select_story_threads(threads, current_chapter=50, budget_chars=4000)
        self.assertLess(len(result), 10)
        self.assertGreaterEqual(len(result), 1)

    def test_high_importance_always_kept_even_over_budget(self):
        big = "字" * 3000
        threads = [
            _thread(importance=5, content=big),
            _thread(importance=4, content=big),
            _thread(importance=2, content=big),
        ]
        result = select_story_threads(threads, current_chapter=50, budget_chars=4000)
        importances = [t["importance"] for t in result]
        self.assertIn(5, importances)
        self.assertIn(4, importances)
        self.assertNotIn(2, importances)

    def test_input_order_preserved(self):
        threads = [
            _thread(importance=5, title="甲"),
            _thread(importance=3, title="乙"),
            _thread(importance=4, title="丙"),
        ]
        result = select_story_threads(threads, current_chapter=50)
        self.assertEqual([t["title"] for t in result], ["甲", "乙", "丙"])

    def test_resolved_without_chapter_number_kept(self):
        threads = [_thread(status="resolved", resolved_chapter=None)]
        result = select_story_threads(threads, current_chapter=100)
        self.assertEqual(len(result), 1)


class CapGlossaryTests(unittest.TestCase):
    def _entry(self, term="术语", notes="") -> dict:
        return {"term": term, "category": "", "forbidden_variants": "", "notes": notes}

    def test_small_glossary_untouched(self):
        entries = [self._entry(f"词{i}") for i in range(10)]
        self.assertEqual(len(cap_glossary(entries)), 10)

    def test_over_budget_truncated(self):
        entries = [self._entry(f"词{i}", notes="备注" * 100) for i in range(50)]
        result = cap_glossary(entries, budget_chars=3000)
        self.assertLess(len(result), 50)
        self.assertEqual(result[0]["term"], "词0")

    def test_first_entry_always_kept(self):
        entries = [self._entry("超长词", notes="备" * 5000)]
        self.assertEqual(len(cap_glossary(entries, budget_chars=3000)), 1)


if __name__ == "__main__":
    unittest.main()
