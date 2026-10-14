"""OpenAI 兼容中转上的 Gemini 模型：供应商填了 Gemini 原生地址就改走原生格式。

OpenAI 兼容那条路带不上 safetySettings，Gemini 按默认严格档过滤，症状是
finish_reason=content_filter 空回。只认名字带 gemini 的模型，同一家中转上的
其他模型不能跟着切。"""
import unittest
from unittest.mock import patch

from app.services import llm_client


def _provider(api_format="openai", gemini_base_url=""):
    return {
        "name": "relay", "api_key": "k", "base_url": "https://relay.example/v1",
        "api_format": api_format, "use_proxy": False,
        "gemini_base_url": gemini_base_url, "user_id": None,
    }


class NativeGeminiRouteTests(unittest.TestCase):
    def setUp(self):
        self.providers = {
            1: _provider(gemini_base_url="https://relay.example/gemini"),
            2: _provider(),
            3: _provider(api_format="gemini"),
        }
        self.entries = {
            10: {"model_id": "gemini-3.8-flash", "api_format": "openai", "provider_id": 1, "user_id": None},
            11: {"model_id": "deepseek-v4", "api_format": "openai", "provider_id": 1, "user_id": None},
            12: {"model_id": "gemini-3.8-flash", "api_format": "openai", "provider_id": 2, "user_id": None},
        }
        self.patches = [
            patch.dict(llm_client._providers_cache, self.providers, clear=True),
            patch.dict(llm_client._entry_index, self.entries, clear=True),
            patch.object(llm_client, "_current_non_admin", return_value=None),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_gemini_model_on_relay_with_native_url_reports_gemini(self):
        self.assertEqual(llm_client.resolve_model_ref("10"), ("gemini-3.8-flash", "gemini", 1))

    def test_other_models_on_same_relay_stay_openai(self):
        self.assertEqual(llm_client.resolve_model_ref("11")[1], "openai")

    def test_relay_without_native_url_stays_openai(self):
        self.assertEqual(llm_client.resolve_model_ref("12")[1], "openai")

    def test_dispatch_uses_native_url_for_gemini_client(self):
        with patch.object(llm_client, "_get_gemini_client_for", return_value="G") as gem, \
             patch.object(llm_client, "_get_openai_client_for", return_value="O"):
            self.assertEqual(llm_client._resolve_dispatch("10", "openai"), ("gemini-3.8-flash", "gemini", "G"))
        gem.assert_called_once_with("k", "https://relay.example/gemini", False)

    def test_dispatch_keeps_openai_for_non_gemini_and_unset_url(self):
        with patch.object(llm_client, "_get_gemini_client_for", return_value="G"), \
             patch.object(llm_client, "_get_openai_client_for", return_value="O") as oai:
            self.assertEqual(llm_client._resolve_dispatch("11", "openai")[1:], ("openai", "O"))
            self.assertEqual(llm_client._resolve_dispatch("12", "openai")[1:], ("openai", "O"))
        oai.assert_called_with("k", "https://relay.example/v1", False)

    def test_native_url_ignored_on_non_openai_provider(self):
        self.providers[3]["gemini_base_url"] = "https://elsewhere/gemini"
        llm_client._providers_cache[3] = self.providers[3]
        self.assertEqual(llm_client._native_gemini_url("gemini-3.8-flash", 3), "")


if __name__ == "__main__":
    unittest.main()
