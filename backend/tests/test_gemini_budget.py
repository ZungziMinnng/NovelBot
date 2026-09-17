"""Gemini 的 max_output_tokens 是「思考链 + 正文」共用的。

非流式那两个 dispatch 曾经把用户的 max_tokens 原样透进 max_output_tokens，
思考吃掉一部分，正文说到一半就 MAX_TOKENS——模组页的「AI 优化」和「一键生成」
天天截断就是这个。流式那条路一直有 _effective_max_tokens，非流式漏了。
"""
import unittest
from unittest.mock import patch

from app.services import llm_client


class ThinkingHeadroomTests(unittest.TestCase):
    def test_off_still_reserves_something(self):
        """"off" 不等于不思考：_resolve_gemini_thinking 给 3.x 的是 MINIMAL/LOW，
        给 2.x pro 的是 min_budget=128。headroom 返回 0 的话那点思考就从正文里扣。"""
        self.assertGreater(llm_client._gemini_thinking_headroom("gemini-3.0-pro", "off"), 0)
        self.assertGreater(llm_client._gemini_thinking_headroom("gemini-2.5-pro", "off"), 0)

    def test_headroom_is_added_on_top_of_the_body_budget(self):
        for model in ("gemini-3.0-pro", "gemini-2.5-pro", "gemini-2.0-flash-lite"):
            with self.subTest(model=model):
                self.assertGreater(
                    llm_client._effective_max_tokens(model, "gemini", 1500, "off", "off"),
                    1500,
                )

    def test_hard_cap_is_respected(self):
        self.assertEqual(
            llm_client._effective_max_tokens("gemini-3.0-pro", "gemini", 65000, "off", "off"),
            65536,
        )

    def test_non_gemini_budget_is_untouched(self):
        self.assertEqual(
            llm_client._effective_max_tokens("gpt-4o", "openai", 1500, "off", "off"), 1500
        )

    def test_gemini_behind_an_openai_compatible_endpoint_also_gets_headroom(self):
        """中转站把 Gemini 挂在 OpenAI 兼容端点上，api_format 是 "openai"，
        但上游还是 Gemini，max_output_tokens 照样覆盖思考链。

        真实case：出图转 tag 写死 max_tokens=1200，走 gemini-3.5-flash 的
        openai 兼容端点，1200 全被思考吃掉、一个 { 都没吐出来，外面报的是
        「Expecting value: line 1 column 1 (char 0)」，看着像模型拒答。
        """
        self.assertGreater(
            llm_client._effective_max_tokens("gemini-3.5-flash", "openai", 1200, "off", "off"),
            1200,
        )


class NonStreamDispatchBudgetTests(unittest.IsolatedAsyncioTestCase):
    """两个非流式 dispatch 都要把 max_tokens 过一遍 _effective_max_tokens。"""

    async def _seen_budget(self, dispatch, target, ret, fmt="gemini"):
        seen = {}

        async def fake(messages, model, temperature, max_tokens, client=None):
            seen["max_tokens"] = max_tokens
            return ret

        with (
            patch.object(llm_client, "_resolve_dispatch",
                         return_value=("gemini-3.0-pro", fmt, None)),
            patch.object(llm_client, target, fake),
        ):
            await dispatch(messages=[{"role": "user", "content": "x"}],
                           model="gemini-3.0-pro", api_format=fmt, max_tokens=1500)
        return seen["max_tokens"]

    async def test_complete_widens_the_budget(self):
        got = await self._seen_budget(
            llm_client.dispatch_chat_complete, "_gemini_complete", "ok"
        )
        self.assertGreater(got, 1500)

    async def test_complete_with_usage_widens_the_budget(self):
        got = await self._seen_budget(
            llm_client.dispatch_chat_complete_with_usage,
            "_gemini_complete_with_usage", ("ok", 1, 2),
        )
        self.assertGreater(got, 1500)

    async def _seen_openai_budget(self, dispatch, target, ret):
        """openai 兼容那一路：预算原来压根没过 _effective_max_tokens，
        挂在中转站上的 Gemini 就拿不到思考预留。"""
        seen = {}

        async def fake(messages, model, client, temperature, max_tokens):
            seen["max_tokens"] = max_tokens
            return ret

        with (
            patch.object(llm_client, "_resolve_dispatch",
                         return_value=("gemini-3.5-flash", "openai", None)),
            patch.object(llm_client, target, fake),
        ):
            await dispatch(messages=[{"role": "user", "content": "x"}],
                           model="gemini-3.5-flash", api_format="openai", max_tokens=1200)
        return seen["max_tokens"]

    async def test_openai_branch_widens_the_budget(self):
        got = await self._seen_openai_budget(
            llm_client.dispatch_chat_complete, "chat_complete", "ok"
        )
        self.assertGreater(got, 1200)

    async def test_openai_branch_with_usage_widens_the_budget(self):
        got = await self._seen_openai_budget(
            llm_client.dispatch_chat_complete_with_usage,
            "chat_complete_with_usage", ("ok", 1, 2),
        )
        self.assertGreater(got, 1200)


if __name__ == "__main__":
    unittest.main()
