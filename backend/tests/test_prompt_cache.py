"""Claude 显式缓存标记：只有 Claude 改写成 cache_control 块，其他模型只剥键、原样发。

Gemini/DeepSeek/豆包是自动前缀缓存，把 content 改成块数组反而可能被拒，
所以标记键必须在发出前剥干净。
"""
import asyncio
import unittest
from unittest.mock import patch

from app.agents import writer
from app.services import llm_client
from app.services.llm_client import CACHE_BREAKPOINT


def _msgs():
    return [
        {"role": "system", "content": "写作要求", CACHE_BREAKPOINT: True},
        {"role": "user", "content": "资料"},
    ]


class ApplyBreakpointTests(unittest.TestCase):
    def test_claude_gets_cache_control_block(self):
        out = llm_client._apply_cache_breakpoints(_msgs(), "claude-sonnet-5-5")
        self.assertEqual(out[0]["content"], [
            {"type": "text", "text": "写作要求", "cache_control": {"type": "ephemeral"}},
        ])
        self.assertNotIn(CACHE_BREAKPOINT, out[0])
        self.assertEqual(out[1], {"role": "user", "content": "资料"})

    def test_other_models_only_strip_the_key(self):
        for model in ("gemini-3.5-flash", "deepseek-v4-flash", "doubao-seed-2-1-pro"):
            out = llm_client._apply_cache_breakpoints(_msgs(), model)
            self.assertEqual(out[0], {"role": "system", "content": "写作要求"}, model)

    def test_input_not_mutated(self):
        """writer 拿同一份 messages 给 DevPanel 展示，不能被改成块数组。"""
        msgs = _msgs()
        llm_client._apply_cache_breakpoints(msgs, "claude-opus-5-5")
        self.assertEqual(msgs[0]["content"], "写作要求")
        self.assertTrue(msgs[0][CACHE_BREAKPOINT])

    def test_unmarked_messages_pass_through_as_is(self):
        msgs = [{"role": "user", "content": "x"}]
        self.assertIs(llm_client._apply_cache_breakpoints(msgs, "claude-x"), msgs)

    def test_anthropic_native_system_becomes_block(self):
        system, rest = llm_client._to_anthropic_messages(_msgs())
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(rest, [{"role": "user", "content": "资料"}])


class WriterMarksSystemTests(unittest.TestCase):
    def _captured(self, deepseek=False):
        async def scenario():
            async def fake_stream(messages, **kwargs):
                fake_stream.captured = messages
                yield ("stop", 1, 1)

            with patch.object(writer.llm_client, "get_agent_client", return_value=("m", "openai")), \
                 patch.object(writer.llm_client, "resolve_model_ref", return_value=("real-m", None, None)), \
                 patch.object(writer.llm_client, "_is_deepseek_model", return_value=deepseek), \
                 patch.object(writer.llm_client, "dispatch_chat_stream_with_usage", fake_stream):
                async for _ in writer.stream_chapter(ctx={"chapter_number": 5}, instruction="", target_words=3000):
                    pass
            return fake_stream.captured

        return asyncio.run(scenario())

    def test_only_system_is_marked(self):
        msgs = self._captured()
        self.assertTrue(msgs[0].get(CACHE_BREAKPOINT))
        self.assertEqual([m for m in msgs[1:] if CACHE_BREAKPOINT in m], [])

    def test_deepseek_merge_leaves_no_mark(self):
        """DeepSeek 的 system 并进最后一条 user，没有 system 可标，也不该把标记带过去。"""
        msgs = self._captured(deepseek=True)
        self.assertEqual([m for m in msgs if CACHE_BREAKPOINT in m], [])


if __name__ == "__main__":
    unittest.main()
