import asyncio
import unittest
from types import SimpleNamespace

from app.services import llm_client

# DZMM 实测回包：stream=false 也回 SSE，data: 后两个空格，没有 usage/finish_reason/[DONE]
_DZMM_SSE = (
    'data:  {"choices":[{"delta":{"content":"你好"}}]}\n\n'
    'data:  {"choices":[{"delta":{"content":"，1"}}]}\n\n'
)


def _fake_client(response):
    async def create(**kwargs):
        return response
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


class ParseSseTextTests(unittest.TestCase):
    def test_joins_deltas(self):
        self.assertEqual(
            llm_client._parse_sse_text(_DZMM_SSE, "m"), ("你好，1", None, 0, 0))

    def test_reads_usage_and_finish_reason(self):
        text = (
            'data: {"choices":[{"delta":{"content":"a"},"finish_reason":"length"}]}\n'
            'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}\n'
            'data: [DONE]\n'
        )
        self.assertEqual(llm_client._parse_sse_text(text, "m"), ("a", "length", 5, 2))

    def test_non_sse_text_raises(self):
        with self.assertRaises(RuntimeError):
            llm_client._parse_sse_text("<html>oops</html>", "m")


class NonStreamFallbackTests(unittest.TestCase):
    def test_chat_complete_accepts_sse_str(self):
        out = asyncio.run(llm_client.chat_complete([], "x-apex", _fake_client(_DZMM_SSE)))
        self.assertEqual(out, "你好，1")

    def test_chat_complete_with_usage_accepts_sse_str(self):
        out = asyncio.run(
            llm_client.chat_complete_with_usage([], "x-apex", _fake_client(_DZMM_SSE)))
        self.assertEqual(out, ("你好，1", 0, 0))


if __name__ == "__main__":
    unittest.main()
