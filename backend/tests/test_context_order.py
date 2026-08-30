"""format_context_for_writer 块顺序测试：实体背景后置、角色与本章大纲贴近末尾。"""
import unittest

from app.services.context_builder import format_context_for_writer


def _full_ctx() -> dict:
    return {
        "characters": [{
            "name": "裴云霁", "role": "主角", "description": "外冷内热",
            "state": {}, "full_sheet": {},
        }],
        "world_entities": [{
            "name": "轮回系统", "type": "system", "description": "金手指",
            "properties": {}, "state": {},
        }],
        "locations": [{"name": "青云城", "type": "城市", "description": "北境重镇"}],
        "factions": [{"name": "天剑宗", "type": "宗门", "description": "正道魁首"}],
        "techniques": [{"name": "御雷诀", "type": "法术", "description": "引雷入体"}],
        "notes": [{"title": "货币", "content": "以灵石为通货"}],
        "core_setting": "修真世界",
        "chapter_outline": "主角初入青云城",
        "rolling_summary": "上回说到……",
        "full_text_context": "前文正文原文",
        "context_config": {},
    }


class ContextOrderTests(unittest.TestCase):
    def test_entities_moved_into_context_block_tail(self):
        context_block, chars_block, _ = format_context_for_writer(_full_ctx())
        for header in ("=== 世界实体 ===", "=== 地点 ===", "=== 势力 ===", "=== 功法 ===", "=== 补充设定 ==="):
            self.assertIn(header, context_block)
            self.assertNotIn(header, chars_block)
        # 顺序：世界观 < 摘要 < 前文正文 < 实体 < 地点 < 势力 < 功法 < 补充设定
        positions = [context_block.index(h) for h in (
            "=== 世界观设定", "=== 近期剧情摘要", "=== 前文正文",
            "=== 世界实体 ===", "=== 地点 ===", "=== 势力 ===", "=== 功法 ===", "=== 补充设定 ===",
        )]
        self.assertEqual(positions, sorted(positions))

    def test_outline_moved_after_characters(self):
        context_block, chars_block, _ = format_context_for_writer(_full_ctx())
        self.assertNotIn("=== 本章大纲 ===", context_block)
        self.assertIn("=== 本章大纲 ===", chars_block)
        self.assertLess(chars_block.index("=== 角色状态 ==="), chars_block.index("=== 本章大纲 ==="))

    def test_outline_alone_when_characters_disabled(self):
        ctx = _full_ctx()
        ctx["context_config"] = {"characters": False}
        _, chars_block, _ = format_context_for_writer(ctx)
        self.assertIn("=== 本章大纲 ===", chars_block)
        self.assertNotIn("=== 角色状态 ===", chars_block)

    def test_milestone_and_recall_blocks_present(self):
        ctx = _full_ctx()
        ctx["relationship_milestones"] = ["[表白] 林砚↔苏晚 | 第37章 | 天台雨夜表白"]
        ctx["recall_evidence"] = "[表白] 林砚↔苏晚 | 第37章\n【第37章原文】天台雨夜……"
        context_block, _, _ = format_context_for_writer(ctx)
        self.assertIn("=== 关系里程碑（已确立事实，回忆时以此为准）===", context_block)
        self.assertIn("- [表白] 林砚↔苏晚", context_block)
        self.assertIn("=== 回忆取证（历史章节原文片段）===", context_block)
        # 里程碑在摘要之前（事实优先），取证在相关历史场景之后
        self.assertLess(
            context_block.index("=== 关系里程碑"),
            context_block.index("=== 近期剧情摘要"),
        )

    def test_rag_fulltext_block_present(self):
        ctx = _full_ctx()
        ctx["rag_context"] = "【第37章·历史证据】摘要内容"
        ctx["rag_fulltext"] = "【第37章原文】天台雨夜，林砚坦白身世……"
        context_block, _, _ = format_context_for_writer(ctx)
        self.assertIn("=== 历史章节原文片段（真实原文）===", context_block)
        self.assertIn("【第37章原文】", context_block)
        # 原文片段紧跟在相关历史场景之后
        self.assertLess(
            context_block.index("=== 相关历史场景"),
            context_block.index("=== 历史章节原文片段"),
        )

    def test_rag_fulltext_block_respects_config_off(self):
        ctx = _full_ctx()
        ctx["rag_fulltext"] = "【第37章原文】天台雨夜……"
        ctx["context_config"] = {"rag_fulltext": False}
        context_block, _, _ = format_context_for_writer(ctx)
        self.assertNotIn("历史章节原文片段", context_block)

    def test_milestone_and_recall_blocks_absent_by_default(self):
        context_block, _, _ = format_context_for_writer(_full_ctx())
        self.assertNotIn("关系里程碑", context_block)
        self.assertNotIn("回忆取证", context_block)
        self.assertNotIn("历史章节原文片段", context_block)

    def test_milestone_and_recall_blocks_respect_config_off(self):
        ctx = _full_ctx()
        ctx["relationship_milestones"] = ["[表白] 林砚↔苏晚 | 第37章 | 天台雨夜表白"]
        ctx["recall_evidence"] = "【第37章原文】天台雨夜……"
        ctx["context_config"] = {"relationship_milestones": False, "recall_evidence": False}
        context_block, _, _ = format_context_for_writer(ctx)
        self.assertNotIn("关系里程碑", context_block)
        self.assertNotIn("回忆取证", context_block)


if __name__ == "__main__":
    unittest.main()
