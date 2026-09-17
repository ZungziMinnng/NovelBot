"""负温度 = 整个 temperature 参数不发给供应商。

这个约定全项目在用（RPG 模组、酒馆卡、小说的构思温度都靠它支持「不传」），
可 dispatch_chat_complete 底下的两个非流式实现当初漏了守卫，会把 -1 原样发出去
换来一个 400。这里把两条路各钉一个测试。
"""
import asyncio
import unittest

from app.services import llm_client


class _FakeOpenAI:
    """只记下 create() 收到的 kwargs。"""

    def __init__(self):
        self.kwargs = {}
        outer = self

        class Completions:
            async def create(self, **kw):
                outer.kwargs = kw
                choice = type("C", (), {
                    "message": type("M", (), {"content": "ok"})(),
                    "finish_reason": "stop",
                })()
                return type("R", (), {"choices": [choice], "usage": None})()

        self.chat = type("Chat", (), {"completions": Completions()})()


class _FakeAnthropic:
    def __init__(self):
        self.kwargs = {}
        outer = self

        class Messages:
            async def create(self, **kw):
                outer.kwargs = kw
                return type("R", (), {
                    "content": [type("T", (), {"text": "ok"})()],
                })()

        self.messages = Messages()


_MSGS = [{"role": "user", "content": "hi"}]


class TemperatureOmitTests(unittest.TestCase):
    def test_openai_omits_negative_temperature(self):
        client = _FakeOpenAI()
        asyncio.run(llm_client.chat_complete(_MSGS, "gpt-x", client, temperature=-1))
        self.assertNotIn("temperature", client.kwargs)

    def test_openai_sends_normal_temperature(self):
        client = _FakeOpenAI()
        asyncio.run(llm_client.chat_complete(_MSGS, "gpt-x", client, temperature=0.5))
        self.assertEqual(client.kwargs["temperature"], 0.5)

    def test_anthropic_omits_negative_temperature(self):
        client = _FakeAnthropic()
        asyncio.run(llm_client._anthropic_complete(_MSGS, "claude-x", -1, 100, client))
        self.assertNotIn("temperature", client.kwargs)

    def test_anthropic_sends_normal_temperature(self):
        client = _FakeAnthropic()
        asyncio.run(llm_client._anthropic_complete(_MSGS, "claude-x", 0.5, 100, client))
        self.assertEqual(client.kwargs["temperature"], 0.5)


if __name__ == "__main__":
    unittest.main()
