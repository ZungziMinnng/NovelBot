import asyncio
import unittest
from unittest.mock import patch

from app.agents import writer


class DeepseekSystemMergeTests(unittest.TestCase):
    def _msgs(self):
        return [
            {"role": "system", "content": "写作要求"},
            {"role": "user", "content": "资料"},
            {"role": "assistant", "content": "草稿"},
            {"role": "user", "content": "修订指令"},
        ]

    def test_non_deepseek_unchanged(self):
        with patch.object(writer.llm_client, "_is_deepseek_model", return_value=False):
            out = writer._apply_deepseek_system_merge(self._msgs(), "gpt-x")
        self.assertEqual(out[0]["role"], "system")
        self.assertEqual(len(out), 4)

    def test_deepseek_merges_system_into_last_user(self):
        with patch.object(writer.llm_client, "_is_deepseek_model", return_value=True):
            out = writer._apply_deepseek_system_merge(self._msgs(), "deepseek-x")
        self.assertEqual(len(out), 3)
        self.assertNotIn("system", [m["role"] for m in out])
        self.assertIn("写作要求", out[-1]["content"])
        self.assertIn("修订指令", out[-1]["content"])
        # 只合并到最后一条 user，第一条 user 不动
        self.assertEqual(out[0]["content"], "资料")


class RevisionConstraintsTests(unittest.TestCase):
    def test_empty_ctx_returns_empty(self):
        self.assertEqual(writer._build_revision_constraints({}), "")

    def test_blocks_included(self):
        ctx = {
            "core_rules": "## 核心规则\n- 灵气不可再生",
            "glossary": [{"term": "灵石", "forbidden_variants": "灵晶", "notes": ""}],
            "_all_character_names": ["张三", "李四"],
        }
        text = writer._build_revision_constraints(ctx)
        self.assertIn("灵气不可再生", text)
        self.assertIn("用「灵石」", text)
        self.assertIn("禁用：「灵晶」", text)
        self.assertIn("张三、李四", text)

    def test_names_fallback_to_characters(self):
        text = writer._build_revision_constraints({"characters": [{"name": "王五"}]})
        self.assertIn("王五", text)


class StreamChapterRevisionTests(unittest.TestCase):
    def _collect(self, api_format):
        async def scenario():
            async def fake_stream(messages, **kwargs):
                fake_stream.captured = messages
                yield "修订正文"
                yield ("stop", 10, 5)

            items = []
            with patch.object(writer.llm_client, "get_agent_client", return_value=("m", api_format)), \
                 patch.object(writer.llm_client, "resolve_model_ref", return_value=("real-m", None, None)), \
                 patch.object(writer.llm_client, "_is_deepseek_model", return_value=False), \
                 patch.object(writer.llm_client, "dispatch_chat_stream_with_usage", fake_stream):
                async for item in writer.stream_chapter_revision(
                    ctx={"core_rules": "规则A", "_all_character_names": ["张三"]},
                    previous_text="上一版全文内容。",
                    issues_feedback="- 第三段逻辑矛盾",
                    instruction="保持紧凑",
                    target_words=3000,
                ):
                    items.append(item)
            return items, fake_stream.captured

        return asyncio.run(scenario())

    def test_openai_structure_has_assistant_draft(self):
        items, messages = self._collect("openai")
        roles = [m["role"] for m in messages]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(messages[2]["content"], "上一版全文内容。")
        self.assertIn("规则A", messages[1]["content"])
        self.assertIn("第三段逻辑矛盾", messages[3]["content"])
        self.assertIn("只修正所列问题", messages[3]["content"])
        self.assertIn("保持紧凑", messages[3]["content"])
        # 输出流：payload → token → usage
        self.assertIn("llm_payload", items[0])
        self.assertEqual(items[1], "修订正文")
        self.assertEqual(items[2], ("stop", 10, 5))

    def test_gemini_single_user_message(self):
        _, messages = self._collect("gemini")
        roles = [m["role"] for m in messages]
        self.assertEqual(roles, ["system", "user"])
        self.assertIn("上一版全文内容。", messages[1]["content"])
        self.assertIn("第三段逻辑矛盾", messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
