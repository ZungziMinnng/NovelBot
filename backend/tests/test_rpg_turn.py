"""RPG 编排里能脱离 LLM 之外单独测的那部分：「帮我想想」。

整轮 run_turn 要打桩流式接口、引擎落库和结算三处，成本高收益低，
这里只钉住 suggest_actions 的四条：窗口怎么切、prompt 里有什么、
模型输出怎么洗、出错怎么办。
"""
import unittest
from unittest.mock import patch

from app.agents import rpg_turn
from app.models.rpg import RpgMessage, RpgModule, RpgSession

SENTINEL = "哨兵串勿入提示词XYZZY"


def _module(**over):
    base = dict(id=1, user_id=1, name="锈湖地窖", creator_note=SENTINEL, context_turns=20)
    base.update(over)
    return RpgModule(**base)


def _session(**over):
    base = dict(
        id=1, module_id=1, char_name="阿隼", location="地窖", summary="", summarized_upto_id=0
    )
    base.update(over)
    return RpgSession(**base)


def _history(*pairs):
    """(role, content) 变 RpgMessage，id 从 1 递增。"""
    return [
        RpgMessage(id=i, session_id=1, role=role, content=content)
        for i, (role, content) in enumerate(pairs, start=1)
    ]


class _Base(unittest.IsolatedAsyncioTestCase):
    async def _suggest(self, reply="", history=None, module=None, sess=None):
        """跑一次 suggest_actions，把发给模型的 messages 和调用次数捞出来。"""
        captured = {"calls": 0}

        async def fake_dispatch(messages, **kwargs):
            captured["calls"] += 1
            captured["prompt"] = messages[0]["content"]
            captured["kwargs"] = kwargs
            return reply

        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake_dispatch):
            result = await rpg_turn.suggest_actions(
                module or _module(), sess or _session(), history or []
            )
        return result, captured


class SuggestTests(_Base):
    async def test_the_prompt_carries_the_player_and_never_the_creator_note(self):
        _, captured = await self._suggest(
            "看看四周",
            history=_history(("user", "我推开门"), ("assistant", "门后是黑的。")),
        )
        self.assertIn("阿隼", captured["prompt"])
        self.assertIn("地窖", captured["prompt"])
        self.assertIn("我推开门", captured["prompt"])
        self.assertIn("GM：门后是黑的。", captured["prompt"])
        # creator_note 是只给作者看的备注，任何提示词里都不能出现
        self.assertNotIn(SENTINEL, captured["prompt"])

    async def test_the_model_is_asked_for_three_short_lines(self):
        _, captured = await self._suggest(
            "看看四周", history=_history(("user", "我推开门")),
        )
        # 要三条就不能只给 600 token 里的三条留位置，这里钉住温度：
        # 低了三条会是同一件事的三种说法，那就白搭了
        self.assertEqual(captured["kwargs"]["temperature"], 0.95)
        self.assertEqual(captured["kwargs"]["max_tokens"], 600)

    async def test_numbering_quotes_and_bullets_are_stripped(self):
        result, _ = await self._suggest(
            "1. 撬开那把铁锁\n- 「问老兵」\n• 往东边走走\n4. 多出来的第四条",
            history=_history(("user", "我推开门")),
        )
        self.assertEqual(result, ["撬开那把铁锁", "问老兵", "往东边走走"])

    async def test_a_number_without_a_separator_survives(self):
        # 编号必须带 . 、 ) ） 之一才剥，否则「3天后再回来」会被吃掉开头的数字
        result, _ = await self._suggest(
            "3天后再回来看看", history=_history(("user", "我推开门")),
        )
        self.assertEqual(result, ["3天后再回来看看"])

    async def test_blank_lines_do_not_become_suggestions(self):
        result, _ = await self._suggest(
            "推门进去\n\n  \n问老兵\n", history=_history(("user", "我推开门")),
        )
        self.assertEqual(result, ["推门进去", "问老兵"])

    async def test_an_empty_session_does_not_call_the_model(self):
        # 刚开局、还没有任何消息时按灯泡，不该为「什么都不知道」付一次调用
        result, captured = await self._suggest("推门进去", history=[])
        self.assertEqual(result, [])
        self.assertEqual(captured["calls"], 0)

    async def test_summarized_messages_are_not_sent_again(self):
        history = _history(
            ("user", "很久以前的一句"), ("assistant", "很久以前的回答"), ("user", "刚说的一句"),
        )
        _, captured = await self._suggest(
            "推门进去", history=history, sess=_session(summarized_upto_id=2),
        )
        self.assertNotIn("很久以前的一句", captured["prompt"])
        self.assertIn("刚说的一句", captured["prompt"])

    async def test_only_the_recent_tail_is_sent(self):
        history = _history(*[("user", f"第{i}句") for i in range(1, 13)])
        _, captured = await self._suggest("推门进去", history=history)
        self.assertNotIn("第1句", captured["prompt"])
        self.assertIn("第12句", captured["prompt"])

    async def test_a_misconfigured_model_reaches_the_route(self):
        # 路由靠这个 ValueError 转成 400。吞掉它的话，模型配错时前端
        # 只会看到「没想出来」，找不到真正的毛病
        with patch.object(rpg_turn.llm_client, "get_agent_client", side_effect=ValueError("模型不存在")):
            with self.assertRaises(ValueError):
                await rpg_turn.suggest_actions(
                    _module(), _session(), _history(("user", "我推开门"))
                )


if __name__ == "__main__":
    unittest.main()
