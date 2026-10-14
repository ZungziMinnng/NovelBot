"""选段改写：只把选中段交给模型改，前后文截断后作参考；不碰数据库里的章节。"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import passage_rewrite


def _novel():
    return SimpleNamespace(id=1, genre="玄幻", writing_style="热血激昂", writer_model="")


class PassageRewriteTests(unittest.TestCase):
    def test_messages_mark_context_as_reference(self):
        before = "前" * 3000
        after = "后" * 3000
        msgs = passage_rewrite.build_messages(_novel(), "expand", before, "选中的一段", after, "多写心理")
        system, user = msgs[0]["content"], msgs[1]["content"]
        self.assertIn("扩写", system)
        self.assertIn("多写心理", system)
        self.assertIn("只输出选中那段的替换文字", system)
        self.assertIn("选中的一段", user)
        # 前后文截断到上限
        self.assertIn("前" * passage_rewrite.BEFORE_CHARS, user)
        self.assertNotIn("前" * (passage_rewrite.BEFORE_CHARS + 1), user)
        self.assertIn("后" * passage_rewrite.AFTER_CHARS, user)
        self.assertNotIn("后" * (passage_rewrite.AFTER_CHARS + 1), user)
        self.assertLess(user.index("选中的一段"), user.index("后" * 10))

    def test_each_mode_renders_own_requirements(self):
        texts = {
            m: passage_rewrite.build_messages(_novel(), m, "", "原文" * 50, "", "")[0]["content"]
            for m in ("rewrite", "expand", "condense")
        }
        self.assertIn("改写要求", texts["rewrite"])
        self.assertIn("扩写要求", texts["expand"])
        self.assertIn("缩写要求", texts["condense"])
        self.assertNotIn("额外要求", texts["rewrite"])
        # 目标字数随模式变化
        self.assertIn("约 100 字", texts["rewrite"])
        self.assertIn("约 180 字", texts["expand"])
        self.assertIn("约 60 字", texts["condense"])

    def test_empty_context_omitted(self):
        user = passage_rewrite.build_messages(_novel(), "rewrite", "  ", "一段", "", "")[1]["content"]
        self.assertNotIn("前文", user)
        self.assertNotIn("后文", user)

    def test_run_returns_stripped_text(self):
        async def scenario():
            with patch.object(passage_rewrite.llm_client, "get_agent_client", return_value=("m", "openai")), \
                 patch.object(passage_rewrite.llm_client, "resolve_model_ref", return_value=("m", "openai", None)), \
                 patch.object(passage_rewrite.llm_client, "dispatch_chat_complete_with_usage",
                              new=AsyncMock(return_value=("  新的一段\n", 10, 5))), \
                 patch.object(passage_rewrite, "AsyncSessionLocal") as sess:
                sess.return_value.__aenter__.return_value = SimpleNamespace(add=lambda _: None, commit=AsyncMock())
                out = await passage_rewrite.run(_novel(), "rewrite", "", "旧的一段", "")
            self.assertEqual(out, "新的一段")
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
