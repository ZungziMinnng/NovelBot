import asyncio
import json
import unittest
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, llm_usage as _llm_usage  # noqa: F401
from app.agents import memory_pipeline, review_agent
from app.api.routes.novels import aggregate_usage
from app.models.chapter import Chapter
from app.models.llm_usage import LlmUsage


class AggregateUsageTests(unittest.TestCase):
    def test_merges_models_within_group_and_prices(self):
        rows = [
            ("writer", "model-a", 2, 1_000_000, 500_000, 3000),
            ("writer", "model-b", 1, 2_000_000, 0, 1000),
            ("critic", "model-a", 1, 100, 50, 200),
        ]
        price_map = {"model-a": (2.0, 8.0)}  # 元/百万token；model-b 未配置单价
        out = aggregate_usage(rows, price_map, "agent")
        self.assertEqual(out["group_by"], "agent")
        writer = next(r for r in out["rows"] if r["key"] == "writer")
        self.assertEqual(writer["calls"], 3)
        self.assertEqual(writer["input_tokens"], 3_000_000)
        self.assertEqual(writer["output_tokens"], 500_000)
        # model-a: 1M*2 + 0.5M*8 = 6 元；model-b 无单价计 0
        self.assertAlmostEqual(writer["cost_cny"], 6.0)
        self.assertEqual(out["total"]["calls"], 4)
        self.assertEqual(out["total"]["input_tokens"], 3_000_100)

    def test_none_values_treated_as_zero(self):
        out = aggregate_usage([("writer", "m", None, None, None, None)], {}, "agent")
        self.assertEqual(out["rows"][0]["input_tokens"], 0)
        self.assertEqual(out["total"]["cost_cny"], 0.0)

    def test_empty_rows(self):
        out = aggregate_usage([], {}, "chapter")
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["total"]["calls"], 0)


class EmitLlmCallTests(unittest.TestCase):
    def test_writes_row_and_returns_sse(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            try:
                data = {
                    "agent": "writer", "model": "gpt-x", "status": "ok",
                    "input_tokens": 100, "output_tokens": 200, "duration_ms": 1500,
                    "payload": {"messages": []},  # 额外字段不入库
                }
                with patch.object(memory_pipeline, "AsyncSessionLocal", maker):
                    sse = await memory_pipeline._emit_llm_call(7, 3, data)
                payload = json.loads(sse[len("data: "):])
                self.assertEqual(payload["event"], "llm_call")
                self.assertEqual(payload["data"]["agent"], "writer")
                async with maker() as s:
                    row = (await s.execute(select(LlmUsage))).scalars().one()
                self.assertEqual(
                    (row.novel_id, row.chapter_number, row.agent, row.model,
                     row.status, row.input_tokens, row.output_tokens, row.duration_ms),
                    (7, 3, "writer", "gpt-x", "ok", 100, 200, 1500),
                )
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    def test_db_failure_still_returns_sse(self):
        async def scenario():
            def broken_maker():
                raise RuntimeError("db down")

            with patch.object(memory_pipeline, "AsyncSessionLocal", broken_maker):
                sse = await memory_pipeline._emit_llm_call(1, 1, {"agent": "critic"})
            self.assertIn("llm_call", sse)

        asyncio.run(scenario())


class RecentContextTests(unittest.TestCase):
    def _chapters(self, n):
        return [
            Chapter(novel_id=1, number=i + 1, title=f"章{i + 1}",
                    content=f"第{i + 1}章的正文内容。", summary=f"第{i + 1}章摘要。")
            for i in range(n)
        ]

    def test_recent_full_older_summary_only(self):
        text = review_agent._build_recent_context(self._chapters(5), full_recent=3)
        blocks = text.split("\n\n")
        self.assertEqual(len(blocks), 5)
        for b in blocks[:2]:
            self.assertNotIn("正文：", b)
            self.assertIn("摘要：", b)
        for b in blocks[2:]:
            self.assertIn("正文：", b)

    def test_missing_summary_falls_back_to_truncated_content(self):
        chapters = self._chapters(4)
        chapters[0].summary = ""
        text = review_agent._build_recent_context(chapters, full_recent=3)
        first = text.split("\n\n")[0]
        self.assertIn("第1章的正文内容。", first)
        self.assertNotIn("正文：", first)

    def test_fewer_chapters_than_full_recent(self):
        text = review_agent._build_recent_context(self._chapters(2), full_recent=3)
        self.assertEqual(text.count("正文："), 2)

    def test_empty_returns_placeholder(self):
        self.assertIn("无前文", review_agent._build_recent_context([]))


if __name__ == "__main__":
    unittest.main()
