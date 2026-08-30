"""审稿修订预算：本地机械问题与 LLM 审稿意见各自计数，互不挤占。"""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents import critic, draft_loop, writer


def _novel():
    return SimpleNamespace(
        id=1, writer_model="w", fast_model="f", critic_model="",
        enable_critic=True, enable_detail_review=False,
    )


def _state():
    return {
        "chapter_number": 3, "volume": 1, "instruction": "", "target_words": 2500,
        "context": {}, "generated_text": "", "model_used": "", "critic_issues": "",
        "revision_count": 0, "passed": False, "writer_truncated": False,
        "total_input_tokens": 0, "total_output_tokens": 0,
    }


def _events(raw: list[str]) -> list[tuple[str, str]]:
    """SSE 文本 → (event, data) 列表。"""
    out = []
    for chunk in raw:
        payload = json.loads(chunk.split("data: ", 1)[1])
        out.append((payload["event"], payload["data"]))
    return out


class BudgetTests(unittest.TestCase):
    def _run(self, critic_results, *, max_local=2, max_llm=1):
        writer_calls = []

        async def fake_writer(**kwargs):
            writer_calls.append(kwargs)
            yield "正文。"
            yield ("stop", 10, 5)

        queue = list(critic_results)

        async def fake_review(**kwargs):
            passed, model = queue.pop(0)
            return passed, ("" if passed else "问题"), 1, 1, model

        async def fake_emit(*args, **kwargs):
            return "data: {\"event\": \"llm_call\", \"data\": {}}\n\n"

        state = _state()

        async def drive():
            raw = []
            async for evt in draft_loop.run_draft_loop(
                session=None, novel=_novel(), state=state,
                writer_system_prompt="", writer_examples=[],
            ):
                raw.append(evt)
            return raw

        with patch.object(writer, "stream_chapter", fake_writer), \
             patch.object(writer, "stream_chapter_revision", fake_writer), \
             patch.object(critic, "review_chapter", fake_review), \
             patch.object(draft_loop, "_emit_llm_call", fake_emit), \
             patch.object(draft_loop.llm_client, "get_agent_client", return_value=("r", "openai")), \
             patch.object(draft_loop.llm_client, "resolve_model_ref", return_value=("m", None)), \
             patch.object(draft_loop.settings, "max_local_retries", max_local), \
             patch.object(draft_loop.settings, "max_critic_retries", max_llm):
            raw = asyncio.run(drive())
        return len(writer_calls), state, _events(raw)

    def test_local_reject_does_not_consume_llm_budget(self):
        """字数不达标改一次后，设定审查仍有额度——修好前这一步是拿不到的。"""
        calls, state, _ = self._run([
            (False, critic.LOCAL_PRECHECK_MODEL),
            (False, "critic-x"),
            (True, "critic-x"),
        ])
        self.assertEqual(calls, 3)
        self.assertTrue(state["passed"])

    def test_local_budget_is_bounded(self):
        local = (False, critic.LOCAL_PRECHECK_MODEL)
        calls, state, events = self._run([local] * 6, max_local=2, max_llm=1)
        self.assertEqual(calls, 3, "初稿 + 2 次本地修订")
        self.assertFalse(state["passed"])
        self.assertTrue(any(e == "warning" and "本地检查" in d for e, d in events))

    def test_llm_budget_is_bounded(self):
        calls, state, events = self._run([(False, "critic-x")] * 6, max_local=2, max_llm=1)
        self.assertEqual(calls, 2, "初稿 + 1 次审稿修订")
        self.assertFalse(state["passed"])
        self.assertTrue(any(e == "warning" and "质量审查" in d for e, d in events))

    def test_passing_first_try_runs_writer_once(self):
        calls, state, _ = self._run([(True, "critic-x")])
        self.assertEqual(calls, 1)
        self.assertTrue(state["passed"])

    def test_issues_are_emitted_even_when_budget_runs_out(self):
        """打回意见必须发出去，否则用户看不到最后一版为什么没通过。"""
        _, _, events = self._run([(False, "critic-x")] * 6, max_local=0, max_llm=0)
        self.assertTrue(any(e == "critic_issues" for e, _ in events))
