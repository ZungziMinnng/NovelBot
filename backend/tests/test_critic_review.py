"""审稿链路：全文送审、本地/审稿预算分开、advisory 捎带。"""
import asyncio
import unittest
from unittest.mock import patch

from app.agents import critic


def _ctx(**over):
    ctx = {"characters": [], "glossary": [], "chapter_outline": "大纲", "rolling_summary": "摘要"}
    ctx.update(over)
    return ctx


def _prose(n: int) -> str:
    """凑够字数且能过本地检查的正文：结尾是句号，无套式句、无禁用词。"""
    return "他向前走了一步。" * (n // 8 + 1)


class LocalPrecheckTests(unittest.TestCase):
    def test_returns_hard_and_advisory_separately(self):
        hard, advisory = critic._local_precheck(_prose(200), _ctx(), 0)
        self.assertEqual(hard, [])
        self.assertEqual(advisory, [])

    def test_tier2_meta_word_is_advisory_not_hard(self):
        """「伏笔」这类创作术语只提醒，不该单独把正文打回。"""
        text = _prose(200) + "这处伏笔已经埋好。"
        hard, advisory = critic._local_precheck(text, _ctx(), 0)
        self.assertEqual(hard, [])
        self.assertTrue(any("伏笔" in a for a in advisory))

    def test_tier1_meta_word_is_hard(self):
        text = _prose(200) + "本章大纲要求他离开。"
        hard, _ = critic._local_precheck(text, _ctx(), 0)
        self.assertTrue(any("本章大纲" in h for h in hard))

    def test_empty_text_returns_two_lists(self):
        hard, advisory = critic._local_precheck("", _ctx(), 0)
        self.assertEqual(hard, ["正文为空"])
        self.assertEqual(advisory, [])


class ReviewChapterTests(unittest.TestCase):
    def _review(self, text, ctx=None, llm_reply="PASS", target_words=0):
        captured = {}

        async def fake_dispatch(messages, **kwargs):
            captured["prompt"] = messages[0]["content"]
            return llm_reply, 10, 5

        with patch.object(critic.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(critic.llm_client, "dispatch_chat_complete_with_usage", fake_dispatch):
            result = asyncio.run(critic.review_chapter(
                generated_text=text, ctx=ctx or _ctx(), target_words=target_words,
            ))
        return result, captured.get("prompt", "")

    def test_full_text_reaches_the_prompt(self):
        """不再截 3000 字：长章的结尾必须出现在审稿提示词里。"""
        body = _prose(6000) + "结尾独有的一句话。"
        (_, _, _, _, _), prompt = self._review(body)
        self.assertGreater(len(body), 3000)
        self.assertIn("结尾独有的一句话。", prompt)

    def test_plot_suggestions_are_not_sent_for_review(self):
        text = _prose(200) + "\n\n接下来剧情可以这样发展：\nA. 甲\nB. 乙"
        _, prompt = self._review(text)
        self.assertNotIn("接下来剧情", prompt)

    def test_local_reject_is_tagged_with_local_model(self):
        (passed, issues, in_tok, out_tok, model), prompt = self._review(
            _prose(200), target_words=5000,
        )
        self.assertFalse(passed)
        self.assertEqual(model, critic.LOCAL_PRECHECK_MODEL)
        self.assertIn("字数不足", issues)
        self.assertEqual((in_tok, out_tok), (0, 0))
        self.assertEqual(prompt, "", "本地打回时不该调用 LLM")

    def test_advisory_rides_along_on_local_reject(self):
        text = _prose(200) + "这处伏笔已经埋好。"
        (passed, issues, _, _, _), _ = self._review(text, target_words=5000)
        self.assertFalse(passed)
        self.assertIn("字数不足", issues)
        self.assertIn("顺手一并处理", issues)
        self.assertIn("伏笔", issues)

    def test_advisory_alone_does_not_reject(self):
        text = _prose(200) + "这处伏笔已经埋好。"
        (passed, issues, _, _, _), _ = self._review(text, llm_reply="PASS")
        self.assertTrue(passed)
        self.assertEqual(issues, "")

    def test_advisory_rides_along_on_llm_reject(self):
        text = _prose(200) + "这处伏笔已经埋好。"
        reply = "- [S1][角色不一致] 死人出场｜依据：“他笑了”｜修正：改为回忆"
        (passed, issues, _, _, _), _ = self._review(text, llm_reply=reply)
        self.assertFalse(passed)
        self.assertIn("[S1]", issues)
        self.assertIn("顺手一并处理", issues)

    def test_s3_only_still_passes(self):
        reply = "- [S3][其他] 存疑｜依据：证据不足｜修正：无"
        (passed, issues, _, _, _), _ = self._review(_prose(200), llm_reply=reply)
        self.assertTrue(passed)
        self.assertEqual(issues, "")
