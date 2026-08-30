"""伏笔回收/秘密公开检测测试：ref 匹配库内真实条目、杜撰丢弃、上限、
resolve/reveal 分流、known_by 并集去重、候选不落库（端到端）。"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter as _chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread as _story_thread, glossary_entry  # noqa: F401
from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.story_thread import StoryThread
from app.services import summarizer
from app.services.summarizer import _extract_resolution_candidates, _MAX_RESOLUTIONS_PER_CHAPTER


class _Thread:
    """轻量替身：_extract_resolution_candidates 只读 id/kind/title/content/known_by。"""
    def __init__(self, id, kind, title, content, known_by=None):
        self.id = id
        self.kind = kind
        self.title = title
        self.content = content
        self.known_by = known_by or []


class ExtractResolutionTests(unittest.TestCase):
    def _pool(self):
        return [
            _Thread(1, "foreshadowing", "逐出宗门", "师尊将欺凌主角的弟子逐出宗门。"),
            _Thread(2, "secret", "月华顿悟谎言", "主角实为获得系统突破，对外谎称观月华顿悟。", known_by=["主角"]),
        ]

    def test_resolve_exact_title_match(self):
        cands = _extract_resolution_candidates(
            10,
            [{"ref": "逐出宗门", "kind": "foreshadowing", "resolution": "弟子回归复仇"}],
            None,
            self._pool(),
        )
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual(c["thread_id"], 1)
        self.assertEqual(c["action"], "resolve")
        self.assertEqual(c["resolution"], "弟子回归复仇")
        self.assertEqual(c["source_chapter"], 10)

    def test_reveal_secret_known_by_union(self):
        cands = _extract_resolution_candidates(
            10, None,
            [{"ref": "月华顿悟谎言", "newly_known_by": ["师尊", "主角"]}],
            self._pool(),
        )
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual(c["action"], "reveal")
        self.assertEqual(c["newly_known_by"], ["师尊"])  # 主角已知，去掉
        self.assertEqual(c["known_by"], ["主角", "师尊"])  # 并集去重

    def test_fabricated_ref_dropped(self):
        cands = _extract_resolution_candidates(
            10,
            [{"ref": "根本不存在的伏笔", "resolution": "x"}],
            [{"ref": "也不存在", "newly_known_by": ["某人"]}],
            self._pool(),
        )
        self.assertEqual(cands, [])

    def test_content_substring_match(self):
        # 标题被模型改写，退化到内容互含仍能匹配
        cands = _extract_resolution_candidates(
            10,
            [{"ref": "师尊将欺凌主角的弟子逐出宗门", "resolution": "回归"}],
            None,
            self._pool(),
        )
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["thread_id"], 1)

    def test_reveal_on_foreshadowing_ignored(self):
        # reveal 只对 secret 有意义，指向伏笔应丢弃
        cands = _extract_resolution_candidates(
            10, None,
            [{"ref": "逐出宗门", "newly_known_by": ["某人"]}],
            self._pool(),
        )
        self.assertEqual(cands, [])

    def test_reveal_no_new_knower_dropped(self):
        cands = _extract_resolution_candidates(
            10, None,
            [{"ref": "月华顿悟谎言", "newly_known_by": ["主角"]}],  # 已知情
            self._pool(),
        )
        self.assertEqual(cands, [])

    def test_same_thread_resolve_wins_over_reveal(self):
        cands = _extract_resolution_candidates(
            10,
            [{"ref": "月华顿悟谎言", "resolution": "当众揭穿"}],
            [{"ref": "月华顿悟谎言", "newly_known_by": ["师尊"]}],
            self._pool(),
        )
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["action"], "resolve")

    def test_per_chapter_cap(self):
        pool = [_Thread(i, "foreshadowing", f"伏笔{i}", f"内容{i}") for i in range(1, 7)]
        resolved = [{"ref": f"伏笔{i}", "resolution": "r"} for i in range(1, 7)]
        cands = _extract_resolution_candidates(10, resolved, None, pool)
        self.assertEqual(len(cands), _MAX_RESOLUTIONS_PER_CHAPTER)

    def test_non_dict_and_empty_ref_skipped(self):
        cands = _extract_resolution_candidates(
            10,
            ["不是字典", {"ref": "", "resolution": "x"}, {"resolution": "无ref"}],
            None,
            self._pool(),
        )
        self.assertEqual(cands, [])


class ResolutionEndToEndTests(unittest.TestCase):
    def test_discovered_resolutions_not_persisted(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                novel = Novel(title="测试")
                session.add(novel)
                await session.flush()
                chapter = Chapter(novel_id=novel.id, number=8, volume=1, content="第八章：真相大白。")
                session.add(chapter)
                thread = StoryThread(
                    novel_id=novel.id, kind="foreshadowing", title="逐出宗门",
                    content="师尊将弟子逐出宗门。", status="active", source_chapter=2,
                )
                session.add(thread)
                await session.flush()
                thread_id = thread.id

                data = {
                    "day_offset": 0, "period": "", "summary": "真相大白。", "importance": 3,
                    "characters": [], "entities": [], "locations": [], "techniques": [], "factions": [],
                    "threads": [], "milestones": [],
                    "resolved_threads": [{"ref": "逐出宗门", "kind": "foreshadowing", "resolution": "弟子归来复仇"}],
                    "secret_reveals": [],
                }

                async def fake_call_json(messages, model, api_format, **kwargs):
                    return data, 0, 0

                with patch.object(summarizer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(summarizer, "call_json", fake_call_json), \
                     patch.object(summarizer.vector_store, "ensure_embedding_configured", AsyncMock()), \
                     patch.object(summarizer.vector_store, "astore_text", AsyncMock()):
                    _, discovered, _, _ = await summarizer.summarize_and_discover(
                        session, chapter, novel,
                        known_char_names=[], known_entity_names=[], known_locations=[],
                        known_tech_names=[], known_faction_names=[],
                    )

                res = discovered["resolutions"]
                self.assertEqual(len(res), 1)
                self.assertEqual(res[0]["thread_id"], thread_id)
                self.assertEqual(res[0]["action"], "resolve")
                self.assertEqual(res[0]["resolution"], "弟子归来复仇")

                # 候选不落库：库内条目仍是 active
                fresh = (await session.execute(
                    select(StoryThread).where(StoryThread.id == thread_id)
                )).scalar_one()
                self.assertEqual(fresh.status, "active")
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
