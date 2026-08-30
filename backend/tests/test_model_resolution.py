"""每用户模型解析测试：非 admin 绝不回退全局配置、拒绝他人模型引用。"""
import unittest

from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user  # noqa: F401
from app.models.user import User
from app.services import llm_client
from app.services.auth import current_user_var


def _user_ctx(**kwargs):
    return User(username=kwargs.pop("username", "u"), password_hash="x", **kwargs)


class ModelResolutionTests(unittest.TestCase):
    def setUp(self):
        self._saved_entry_index = dict(llm_client._entry_index)
        self._saved_formats = dict(llm_client._model_formats)
        self._saved_provider_map = dict(llm_client._model_provider_map)
        llm_client._entry_index.clear()
        llm_client._model_formats.clear()
        llm_client._model_provider_map.clear()
        llm_client._entry_index[1] = {"model_id": "gpt-a", "api_format": "openai", "provider_id": 10, "user_id": 1}
        llm_client._entry_index[2] = {"model_id": "gpt-b", "api_format": "gemini", "provider_id": 20, "user_id": 2}
        llm_client._model_formats["legacy-model"] = "anthropic"
        self._ctx_token = None

    def tearDown(self):
        if self._ctx_token is not None:
            current_user_var.reset(self._ctx_token)
        llm_client._entry_index.clear()
        llm_client._entry_index.update(self._saved_entry_index)
        llm_client._model_formats.clear()
        llm_client._model_formats.update(self._saved_formats)
        llm_client._model_provider_map.clear()
        llm_client._model_provider_map.update(self._saved_provider_map)

    def _set_user(self, user):
        self._ctx_token = current_user_var.set(user)

    # ── 无上下文（启动、后台任务、旧测试）：原行为不变 ──

    def test_no_context_original_behavior(self):
        model, fmt, pid = llm_client.resolve_model_ref("1")
        self.assertEqual((model, fmt, pid), ("gpt-a", "openai", 10))
        model, fmt, pid = llm_client.resolve_model_ref("legacy-model")
        self.assertEqual((model, fmt, pid), ("legacy-model", "anthropic", None))

    # ── 非 admin：只接受本人的数字 ModelEntry id ──

    def test_non_admin_own_entry_ok(self):
        self._set_user(_user_ctx(id=1))
        self.assertEqual(llm_client.resolve_model_ref("1"), ("gpt-a", "openai", 10))

    def test_non_admin_rejects_others_entry(self):
        self._set_user(_user_ctx(id=1))
        with self.assertRaises(ValueError):
            llm_client.resolve_model_ref("2")

    def test_non_admin_rejects_legacy_string_ref(self):
        # 字符串引用会命中"最早注册的同名模型"（可能是别人的供应商），必须拒绝
        self._set_user(_user_ctx(id=1))
        with self.assertRaises(ValueError):
            llm_client.resolve_model_ref("legacy-model")

    def test_admin_keeps_original_behavior(self):
        self._set_user(_user_ctx(id=1, is_admin=True))
        self.assertEqual(llm_client.resolve_model_ref("2"), ("gpt-b", "gemini", 20))
        self.assertEqual(llm_client.resolve_model_ref("legacy-model")[1], "anthropic")

    # ── _resolve_model 回退链：小说指定 → 本人默认 → 报错，绝不落到 .env ──

    def test_non_admin_uses_own_default(self):
        self._set_user(_user_ctx(id=1, default_writer_model="1", default_fast_model="1"))
        self.assertEqual(llm_client._resolve_model("writer"), "1")
        self.assertEqual(llm_client._resolve_model("critic"), "1")

    def test_non_admin_no_default_raises(self):
        self._set_user(_user_ctx(id=1))
        with self.assertRaises(ValueError):
            llm_client._resolve_model("writer")
        with self.assertRaises(ValueError):
            llm_client.get_fast_client()

    def test_novel_override_wins(self):
        self._set_user(_user_ctx(id=1))
        self.assertEqual(llm_client._resolve_model("writer", novel_override="1"), "1")
        self.assertEqual(llm_client.get_fast_client(novel_fast_model="1"), ("1", "openai"))

    def test_get_agent_client_rejects_others_override(self):
        # 小说里存了他人的模型 id（比如换号后旧数据）→ 解析阶段就拒绝
        self._set_user(_user_ctx(id=1))
        with self.assertRaises(ValueError):
            llm_client.get_agent_client("writer", novel_override="2")


if __name__ == "__main__":
    unittest.main()
