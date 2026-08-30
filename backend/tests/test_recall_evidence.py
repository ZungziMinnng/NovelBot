"""回忆取证测试：意图触发判定、切段规则、两跳选段。"""
import asyncio
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry  # noqa: F401
from app.models.chapter import Chapter
from app.models.memory import Memory
from app.models.novel import Novel
from app.services.context_builder import (
    _build_rag_fulltext,
    _build_recall_evidence,
    _has_recall_intent,
    _split_paragraphs,
)


class RecallIntentTests(unittest.TestCase):
    def test_keywords_trigger(self):
        for text in ("两人回忆过往", "想起当年初见", "重逢旧事涌上心头"):
            self.assertTrue(_has_recall_intent(text))

    def test_no_trigger(self):
        self.assertFalse(_has_recall_intent("主角大战反派，攻入皇城"))
        self.assertFalse(_has_recall_intent(""))


class SplitParagraphTests(unittest.TestCase):
    def test_short_paragraph_merged(self):
        text = "短句。\n" + "这是一段足够长的正文内容，" * 5
        paras = _split_paragraphs(text)
        self.assertEqual(len(paras), 1)
        self.assertTrue(paras[0].startswith("短句。"))

    def test_trailing_short_merged_backward(self):
        text = ("这是一段足够长的正文内容，" * 5) + "\n结尾短句。"
        paras = _split_paragraphs(text)
        self.assertEqual(len(paras), 1)
        self.assertTrue(paras[0].endswith("结尾短句。"))

    def test_long_paragraph_split_at_period(self):
        text = ("这是一句相当长的话，用来填充长度直到超过限制。" * 40)
        paras = _split_paragraphs(text)
        self.assertGreater(len(paras), 1)
        for p in paras[:-1]:
            self.assertLessEqual(len(p), 600)
            self.assertTrue(p.endswith("。"))

    def test_empty_returns_empty(self):
        self.assertEqual(_split_paragraphs(""), [])


async def _make_env():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    novel = Novel(title="测试")
    session.add(novel)
    await session.flush()
    filler = "山风吹过竹林，弟子们在校场上练剑，晨雾缭绕。" * 3
    ch37 = Chapter(
        novel_id=novel.id, number=37, volume=1,
        content=(
            f"{filler}\n\n"
            "天台雨夜，林砚握住苏晚的手，坦白了自己的身世，随后郑重表白，苏晚含泪点头答应。\n\n"
            f"{filler}"
        ),
    )
    ch50 = Chapter(
        novel_id=novel.id, number=50, volume=1,
        content="边境战事吃紧，大军开拔，粮草辎重络绎不绝。" * 5,
    )
    session.add_all([ch37, ch50])
    await session.flush()
    m1 = Memory(
        novel_id=novel.id, chapter_id=ch37.id, memory_type="relationship_milestone",
        content="[表白] 林砚↔苏晚 | 第37章 | 天台雨夜，林砚坦白身世后表白",
        volume=1, chapter_number=37, importance=4,
    )
    m2 = Memory(
        novel_id=novel.id, chapter_id=ch50.id, memory_type="relationship_milestone",
        content="[决裂] 林砚↔赵铁柱 | 第50章 | 军中争执后割袍断义",
        volume=1, chapter_number=50, importance=3,
    )
    session.add_all([m1, m2])
    await session.flush()
    return engine, session, novel, [m1, m2]


class BuildRecallEvidenceTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    async def _make_env(self):
        return await _make_env()

    def test_evidence_contains_real_fragment(self):
        async def scenario():
            engine, session, novel, milestones = await self._make_env()
            try:
                text = await _build_recall_evidence(
                    session, novel.id, milestones,
                    "两人回忆当年天台雨夜表白的往事",
                    token_budget=2000,
                )
                self.assertIn("【第37章原文】", text)
                self.assertIn("坦白了自己的身世", text)  # 捞到目标段而非填充段
                self.assertIn("[表白] 林砚↔苏晚", text)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_budget_respected(self):
        async def scenario():
            engine, session, novel, milestones = await self._make_env()
            try:
                text = await _build_recall_evidence(
                    session, novel.id, milestones,
                    "回忆天台雨夜表白",
                    token_budget=100,
                )
                # 预算极小仍至少保留一条，且整体被截断到预算内
                self.assertTrue(text)
                from app.services.context_budget import estimate_tokens
                self.assertLessEqual(estimate_tokens(text), 101)  # 截断加省略号
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_missing_chapter_skipped(self):
        async def scenario():
            engine, session, novel, _ = await self._make_env()
            try:
                orphan = Memory(
                    novel_id=novel.id, memory_type="relationship_milestone",
                    content="[初见] 甲↔乙 | 第999章 | 章节不存在",
                    volume=1, chapter_number=999, importance=3,
                )
                session.add(orphan)
                await session.flush()
                text = await _build_recall_evidence(
                    session, novel.id, [orphan],
                    "回忆初见",
                    token_budget=2000,
                )
                self.assertEqual(text, "")
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())


class BuildRagFulltextTests(unittest.TestCase):
    """两跳原文取段（方案A泛化）：复用回忆取证的章节夹具。"""

    def _run(self, coro):
        return asyncio.run(coro)

    async def _make_env(self):
        return await _make_env()

    def test_fragment_from_hit_chapters(self):
        async def scenario():
            engine, session, novel, _ = await self._make_env()
            try:
                text = await _build_rag_fulltext(
                    session, novel.id, [37, 50],
                    "林砚向苏晚坦白身世并表白",
                    token_budget=2000,
                )
                self.assertIn("【第37章原文】", text)
                self.assertIn("坦白了自己的身世", text)  # 捞到目标段而非填充段
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_missing_and_empty_chapters_skipped(self):
        async def scenario():
            engine, session, novel, _ = await self._make_env()
            try:
                text = await _build_rag_fulltext(
                    session, novel.id, [999],
                    "任意查询",
                    token_budget=2000,
                )
                self.assertEqual(text, "")
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())

    def test_budget_respected(self):
        async def scenario():
            engine, session, novel, _ = await self._make_env()
            try:
                text = await _build_rag_fulltext(
                    session, novel.id, [37, 50],
                    "林砚向苏晚坦白身世并表白",
                    token_budget=100,
                )
                self.assertTrue(text)
                from app.services.context_budget import estimate_tokens
                self.assertLessEqual(estimate_tokens(text), 101)  # 截断加省略号
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario())


if __name__ == "__main__":
    unittest.main()
