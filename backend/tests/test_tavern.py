"""酒馆上下文组装测试。

最重要的一条：creator_note 是"AI 不会看到的介绍"，绝不能出现在发给模型的 messages 里。
"""
import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import tavern as tavern_routes
from app.api.routes.tavern import (
    _get_owned_card, _get_owned_entry, _get_owned_instruction_preset,
    _get_owned_message, _get_owned_rule, _get_owned_session,
)
from app.agents import tavern_card_agent
from app.schemas.tavern import TavernCardAssistRequest, TavernTurnRequest
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern  # noqa: F401
from app.models.tavern import (
    TavernCard, TavernInstructionPreset, TavernMessage, TavernRule, TavernSession,
    TavernSessionCard, TavernWorldEntry,
)
from app.models.user import User
from app.services.tavern_context import (
    build_tavern_messages, maybe_summarize, resolve_rules, substitute, suggest_replies,
    triggered_entries,
)

SENTINEL = "CREATOR_ONLY_SENTINEL"


class TavernContextTests(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    async def _setup(self, **card_kwargs):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)()
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.flush()
        defaults = dict(
            name="林越",
            creator_note=SENTINEL,
            personality="表面温和，实际记仇",
            opening_scene="酒馆二楼，雨夜",
            system_instruction="用简短的白话对话",
            description="曾是黑塔的守夜人",
            enabled_rule_ids=[],
            context_turns=20,
        )
        defaults.update(card_kwargs)
        card = TavernCard(user_id=user.id, **defaults)
        session.add(card)
        await session.flush()
        sess = TavernSession(card_id=card.id)
        session.add(sess)
        await session.flush()
        return engine, session, user, card, sess

    async def _add_messages(self, session, sess, pairs):
        rows = []
        for role, content in pairs:
            row = TavernMessage(session_id=sess.id, role=role, content=content)
            session.add(row)
            rows.append(row)
        await session.flush()
        return rows

    # ── creator_note 泄漏 ──────────────────────────────────────────────

    def test_creator_note_never_reaches_model(self):
        """角色卡介绍绝不进 prompt。这是本功能最重要的一条断言。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                await session.commit()
                messages, _ = await build_tavern_messages(
                    session, card, sess, [], "你好"
                )
                self.assertNotIn(SENTINEL, json.dumps(messages, ensure_ascii=False))
                # 其他字段确实进去了，证明不是整体组装失败造成的假通过
                blob = json.dumps(messages, ensure_ascii=False)
                self.assertIn("表面温和", blob)
                self.assertIn("黑塔的守夜人", blob)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_creator_note_absent_from_diag(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                await session.commit()
                _, diag = await build_tavern_messages(session, card, sess, [], "你好")
                self.assertNotIn(SENTINEL, json.dumps(diag, ensure_ascii=False))
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    # ── 扮演底层指令 ──────────────────────────────────────────────────

    def test_roleplay_baseline_always_present(self):
        """不填系统指令的卡也得拿到扮演规则，否则模型只有素材没有演法。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup(system_instruction="")
            try:
                sess.persona_name = "阿辰"
                await session.commit()
                messages, _ = await build_tavern_messages(session, card, sess, [], "你好")
                system = messages[0]["content"]
                self.assertIn("扮演「林越」", system)
                self.assertIn("阿辰", system)
                self.assertIn("不要替玩家说话", system)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_roleplay_baseline_precedes_card_instruction(self):
        """卡上的系统指令排在底稿之后，用户写的话才能覆盖默认行为。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup(
                system_instruction="只说三个字以内的短句",
            )
            try:
                await session.commit()
                messages, _ = await build_tavern_messages(session, card, sess, [], "你好")
                system = messages[0]["content"]
                self.assertLess(
                    system.index("扮演「林越」"), system.index("只说三个字以内的短句")
                )
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_reply_length_only_when_set(self):
        """0 = 不提字数要求，别给模型一句"控制在 0 字左右"。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup(reply_length=0)
            try:
                await session.commit()
                messages, _ = await build_tavern_messages(session, card, sess, [], "你好")
                self.assertNotIn("字左右", messages[0]["content"])

                card.reply_length = 200
                await session.commit()
                messages, _ = await build_tavern_messages(session, card, sess, [], "你好")
                self.assertIn("200 字左右", messages[0]["content"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    # ── 占位符替换 ────────────────────────────────────────────────────

    def test_substitute_basic(self):
        self.assertEqual(substitute("{{char}}看着{{user}}", "林越", "阿辰"), "林越看着阿辰")

    def test_substitute_empty_persona_defaults_to_user(self):
        self.assertEqual(substitute("{{user}}", "林越", ""), "user")

    def test_substitute_case_insensitive(self):
        self.assertEqual(substitute("{{User}} {{Char}}", "林越", "阿辰"), "阿辰 林越")

    def test_substitute_applies_to_history(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                sess.persona_name = "阿辰"
                rows = await self._add_messages(session, sess, [("user", "我是{{user}}")])
                await session.commit()
                messages, _ = await build_tavern_messages(
                    session, card, sess, rows, "{{char}}在吗"
                )
                self.assertEqual(messages[-2]["content"], "我是阿辰")
                self.assertEqual(messages[-1]["content"], "林越在吗")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    # ── 世界书触发 ────────────────────────────────────────────────────

    def _entry(self, card_id, keywords, content, enabled=True, sort_order=0,
               constant=False, depth=0):
        return TavernWorldEntry(
            card_id=card_id, keywords=keywords, content=content,
            enabled=enabled, sort_order=sort_order, constant=constant, depth=depth,
        )

    def test_world_entry_triggers_on_keyword(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                session.add(self._entry(card.id, "黑塔", "黑塔是禁地"))
                session.add(self._entry(card.id, "旧盟约", "旧盟约早已失效"))
                await session.commit()
                messages, diag = await build_tavern_messages(
                    session, card, sess, [], "黑塔那边怎么了"
                )
                system = messages[0]["content"]
                self.assertIn("黑塔是禁地", system)
                self.assertNotIn("旧盟约早已失效", system)
                self.assertEqual(len(diag["triggered"]), 1)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_keywords_split_on_chinese_separators(self):
        """顿号/分号也是分隔符。中文列举词条爱用顿号，只认逗号会让整串变成
        一个永远匹配不上的长关键词。空格不算——"black tower"这种短语要留着。
        """
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                session.add(self._entry(card.id, "十六岁、男婴；抛弃，娘亲", "当年那件事"))
                session.add(self._entry(card.id, "black tower", "塔的设定"))
                await session.commit()
                for probe in ("她十六岁那年", "那个男婴", "你抛弃过谁", "娘亲"):
                    messages, _ = await build_tavern_messages(
                        session, card, sess, [], probe
                    )
                    self.assertIn("当年那件事", messages[0]["content"], probe)
                # 带空格的关键词不该被拆开
                messages, _ = await build_tavern_messages(
                    session, card, sess, [], "去过 black tower 吗"
                )
                self.assertIn("塔的设定", messages[0]["content"])
                messages, _ = await build_tavern_messages(
                    session, card, sess, [], "这是一座 tower"
                )
                self.assertNotIn("塔的设定", messages[0]["content"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_scan_depth_limits_history_scanning(self):
        """scan_depth=1 只扫玩家刚发的这句。

        默认 3 会连角色自己的回复一起扫，词条容易自己喂自己连续触发好几轮——
        用户看到的现象是"改完关键词后好像一直生效"。
        """
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                session.add(self._entry(card.id, "寒玉", "寒玉封着一个孩子"))
                rows = await self._add_messages(
                    session, sess, [("assistant", "那块寒玉早碎了")]
                )
                await session.commit()

                # 默认 3：历史里角色提过"寒玉"，这一轮跟着命中
                _, diag = await build_tavern_messages(
                    session, card, sess, rows, "然后呢",
                )
                self.assertEqual(len(diag["triggered"]), 1)

                # 1：只看当前输入，历史里那句不算
                card.scan_depth = 1
                await session.commit()
                _, diag = await build_tavern_messages(
                    session, card, sess, rows, "然后呢",
                )
                self.assertEqual(diag["triggered"], [])

                # 1 但当前输入自己带了关键词：照样触发
                _, diag = await build_tavern_messages(
                    session, card, sess, rows, "那块寒玉呢",
                )
                self.assertEqual(len(diag["triggered"]), 1)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_disabled_world_entry_never_triggers(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                session.add(self._entry(card.id, "黑塔", "黑塔是禁地", enabled=False))
                await session.commit()
                messages, diag = await build_tavern_messages(
                    session, card, sess, [], "黑塔那边怎么了"
                )
                self.assertNotIn("黑塔是禁地", messages[0]["content"])
                self.assertEqual(diag["triggered"], [])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_keywords_comma_and_whitespace_tolerant(self):
        """半角/全角逗号、空白、换行都当分隔符。"""
        entry = TavernWorldEntry(
            card_id=1, keywords=" 黑塔 ，旧盟约\n守夜人 ", content="x", enabled=True,
        )
        self.assertEqual(len(triggered_entries([entry], "提到守夜人")), 1)
        self.assertEqual(len(triggered_entries([entry], "提到旧盟约")), 1)
        self.assertEqual(len(triggered_entries([entry], "什么都没提")), 0)

    def test_empty_content_entry_skipped(self):
        entry = TavernWorldEntry(card_id=1, keywords="黑塔", content="  ", enabled=True)
        self.assertEqual(triggered_entries([entry], "黑塔"), [])

    def test_world_entry_scans_recent_history(self):
        """关键词出现在最近几条历史里也该触发，不只看本轮输入。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                session.add(self._entry(card.id, "黑塔", "黑塔是禁地"))
                rows = await self._add_messages(
                    session, sess, [("assistant", "我从黑塔来")]
                )
                await session.commit()
                messages, _ = await build_tavern_messages(
                    session, card, sess, rows, "然后呢"
                )
                self.assertIn("黑塔是禁地", messages[0]["content"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    # ── 常驻词条 ──────────────────────────────────────────────────────

    def test_constant_entry_fires_without_keyword_match(self):
        """常驻词条不看关键词，一句不相干的话也该注入。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                session.add(self._entry(
                    card.id, "", "这个世界没有神", constant=True,
                ))
                await session.commit()
                messages, diag = await build_tavern_messages(
                    session, card, sess, [], "天气不错"
                )
                self.assertIn("这个世界没有神", messages[0]["content"])
                self.assertTrue(diag["triggered"][0]["constant"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_disabled_constant_entry_still_skipped(self):
        """常驻只免除关键词检查，停用仍然是停用。"""
        entry = TavernWorldEntry(
            card_id=1, keywords="", content="x", enabled=False, constant=True,
        )
        self.assertEqual(triggered_entries([entry], "随便说点什么"), [])

    # ── 深度插入 ──────────────────────────────────────────────────────

    def test_depth_entry_prepends_into_last_message(self):
        """depth=1 并进最后一条（本轮输入），不新增消息行。

        新增行会破坏各供应商要求的 user/assistant 交替，也会被 Gemini/Anthropic
        的单 system 折叠吃掉。
        """
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                session.add(self._entry(
                    card.id, "黑塔", "别忘了你恨黑塔", depth=1,
                ))
                await session.commit()
                messages, diag = await build_tavern_messages(
                    session, card, sess, [], "黑塔怎么了"
                )
                self.assertEqual(len(messages), 2)  # system + 本轮输入
                self.assertNotIn("别忘了你恨黑塔", messages[0]["content"])
                self.assertIn("别忘了你恨黑塔", messages[-1]["content"])
                self.assertTrue(messages[-1]["content"].endswith("黑塔怎么了"))
                self.assertEqual(diag["triggered"][0]["depth"], 1)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_depth_two_targets_previous_message(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                session.add(self._entry(card.id, "黑塔", "深度提醒", depth=2))
                rows = await self._add_messages(
                    session, sess, [("assistant", "我从黑塔来")]
                )
                await session.commit()
                messages, _ = await build_tavern_messages(
                    session, card, sess, rows, "然后呢"
                )
                # system / assistant 历史 / 本轮输入
                self.assertEqual(len(messages), 3)
                self.assertIn("深度提醒", messages[1]["content"])
                self.assertNotIn("深度提醒", messages[2]["content"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_depth_beyond_history_clamps_to_earliest_turn(self):
        """深度超过现有对话长度就贴到最早那条，不越界到 system。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                session.add(self._entry(card.id, "黑塔", "夹紧提醒", depth=99))
                await session.commit()
                messages, _ = await build_tavern_messages(
                    session, card, sess, [], "黑塔"
                )
                self.assertNotIn("夹紧提醒", messages[0]["content"])
                self.assertIn("夹紧提醒", messages[1]["content"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    # ── 对话示例 ──────────────────────────────────────────────────────

    def test_dialogue_examples_become_alternating_turns(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup(
                dialogue_examples=[
                    {"user": "你叫什么", "assistant": "林越。{{user}}呢？"},
                ],
            )
            try:
                sess.persona_name = "阿禾"
                await session.commit()
                messages, diag = await build_tavern_messages(
                    session, card, sess, [], "你好"
                )
                self.assertEqual(messages[1]["role"], "user")
                self.assertEqual(messages[1]["content"], "你叫什么")
                self.assertEqual(messages[2]["role"], "assistant")
                # 示例里的占位符也要替换
                self.assertEqual(messages[2]["content"], "林越。阿禾呢？")
                self.assertEqual(diag["examples_used"], 1)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_half_filled_example_skipped(self):
        """只填一边的示例不成对，整组丢掉——否则会破坏 user/assistant 交替。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup(
                dialogue_examples=[
                    {"user": "只有问题", "assistant": ""},
                    {"user": "", "assistant": "只有回答"},
                ],
            )
            try:
                await session.commit()
                messages, diag = await build_tavern_messages(
                    session, card, sess, [], "你好"
                )
                self.assertEqual(diag["examples_used"], 0)
                self.assertEqual(len(messages), 2)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    # ── 规则解析 ──────────────────────────────────────────────────────

    def _rule(self, user_id, content, sort_order=0, enabled=True):
        return TavernRule(
            user_id=user_id, name=content, content=content,
            enabled=enabled, sort_order=sort_order,
        )

    def test_resolve_rules_empty_list_returns_empty(self):
        """空列表 → 空字符串。酒馆默认不注入，没有兜底。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                session.add(self._rule(user.id, "规则A"))
                await session.commit()
                self.assertEqual(await resolve_rules(session, user.id, []), "")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_resolve_rules_uses_sort_order(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                a = self._rule(user.id, "规则A", sort_order=2)
                b = self._rule(user.id, "规则B", sort_order=1)
                session.add_all([a, b])
                await session.commit()
                block = await resolve_rules(session, user.id, [a.id, b.id])
                self.assertEqual(block, "规则B\n\n规则A")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_resolve_rules_excludes_disabled(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                a = self._rule(user.id, "规则A")
                b = self._rule(user.id, "规则B", sort_order=1, enabled=False)
                session.add_all([a, b])
                await session.commit()
                block = await resolve_rules(session, user.id, [a.id, b.id])
                self.assertEqual(block, "规则A")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_resolve_rules_ignores_other_users_ids(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                other = User(username="bob", password_hash="x")
                session.add(other)
                await session.flush()
                mine = self._rule(user.id, "我的")
                theirs = self._rule(other.id, "别人的")
                session.add_all([mine, theirs])
                await session.commit()
                block = await resolve_rules(session, user.id, [mine.id, theirs.id])
                self.assertEqual(block, "我的")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_rules_appear_in_system_prompt(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                rule = self._rule(user.id, "不要写心理独白")
                session.add(rule)
                await session.flush()
                card.enabled_rule_ids = [rule.id]
                await session.commit()
                messages, diag = await build_tavern_messages(
                    session, card, sess, [], "你好"
                )
                self.assertIn("不要写心理独白", messages[0]["content"])
                self.assertEqual(diag["rules_used"], 1)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    # ── 历史截断 ──────────────────────────────────────────────────────

    def test_history_truncated_to_context_turns(self):
        """context_turns=2 时只发最近 4 条。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup(context_turns=2)
            try:
                rows = await self._add_messages(session, sess, [
                    ("user", "第1"), ("assistant", "第2"),
                    ("user", "第3"), ("assistant", "第4"),
                    ("user", "第5"), ("assistant", "第6"),
                ])
                await session.commit()
                messages, diag = await build_tavern_messages(
                    session, card, sess, rows, "新的"
                )
                self.assertEqual(diag["history_count"], 4)
                contents = [m["content"] for m in messages]
                self.assertNotIn("第1", contents)
                self.assertNotIn("第2", contents)
                self.assertIn("第3", contents)
                self.assertIn("第6", contents)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_summarized_messages_not_resent(self):
        """已压缩进 summary 的消息不再发原文。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup(context_turns=10)
            try:
                rows = await self._add_messages(session, sess, [
                    ("user", "旧的"), ("assistant", "也旧"), ("user", "新的"),
                ])
                sess.summarized_upto_id = rows[1].id
                sess.summary = "此前他们见过面"
                await session.commit()
                messages, diag = await build_tavern_messages(
                    session, card, sess, rows, "接着说"
                )
                contents = [m["content"] for m in messages]
                self.assertNotIn("旧的", contents)
                self.assertIn("新的", contents)
                self.assertIn("此前他们见过面", messages[0]["content"])
                self.assertEqual(diag["history_count"], 1)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    # ── 摘要边界 ──────────────────────────────────────────────────────

    def test_maybe_summarize_noop_below_threshold(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup(context_turns=2)
            try:
                await self._add_messages(session, sess, [
                    ("user", "1"), ("assistant", "2"), ("user", "3"), ("assistant", "4"),
                ])
                await session.commit()
                self.assertFalse(await maybe_summarize(session, card, sess))
                self.assertEqual(sess.summarized_upto_id, 0)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_maybe_summarize_advances_pointer(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup(context_turns=2)
            try:
                rows = await self._add_messages(session, sess, [
                    ("user", "1"), ("assistant", "2"), ("user", "3"),
                    ("assistant", "4"), ("user", "5"), ("assistant", "6"),
                ])
                await session.commit()
                with patch(
                    "app.services.tavern_context.llm_client.get_agent_client",
                    return_value=("m", "openai"),
                ), patch(
                    "app.services.tavern_context.llm_client.dispatch_chat_complete",
                    return_value="他们聊了很久",
                ):
                    self.assertTrue(await maybe_summarize(session, card, sess))
                # 保留最近 4 条，压缩前 2 条 → 指针停在第 2 条
                self.assertEqual(sess.summarized_upto_id, rows[1].id)
                self.assertEqual(sess.summary, "他们聊了很久")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_maybe_summarize_swallows_llm_failure(self):
        """LLM 失败不抛且指针不动：上下文退化成纯截断，对话还能继续。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup(context_turns=1)
            try:
                await self._add_messages(session, sess, [
                    ("user", "1"), ("assistant", "2"), ("user", "3"), ("assistant", "4"),
                ])
                await session.commit()
                with patch(
                    "app.services.tavern_context.llm_client.get_agent_client",
                    side_effect=ValueError("模型未配置"),
                ):
                    self.assertFalse(await maybe_summarize(session, card, sess))
                self.assertEqual(sess.summarized_upto_id, 0)
                self.assertEqual(sess.summary, "")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_maybe_summarize_ignores_empty_llm_reply(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup(context_turns=1)
            try:
                await self._add_messages(session, sess, [
                    ("user", "1"), ("assistant", "2"), ("user", "3"), ("assistant", "4"),
                ])
                await session.commit()
                with patch(
                    "app.services.tavern_context.llm_client.get_agent_client",
                    return_value=("m", "openai"),
                ), patch(
                    "app.services.tavern_context.llm_client.dispatch_chat_complete",
                    return_value="   ",
                ):
                    self.assertFalse(await maybe_summarize(session, card, sess))
                self.assertEqual(sess.summarized_upto_id, 0)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)


class TavernSuggestTests(unittest.TestCase):
    """帮我想想：4 条候选回复。"""

    _run = TavernContextTests._run
    _setup = TavernContextTests._setup
    _add_messages = TavernContextTests._add_messages

    def test_strips_numbering_and_caps_at_four(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                rows = await self._add_messages(session, sess, [("assistant", "你终于来了")])
                await session.commit()
                reply = "1. 你等我很久了？\n2、我只是路过\n- 转身就走\n「说吧，什么事」\n5. 多出来的一条"
                with patch(
                    "app.services.tavern_context.llm_client.get_agent_client",
                    return_value=("m", "openai"),
                ), patch(
                    "app.services.tavern_context.llm_client.dispatch_chat_complete",
                    return_value=reply,
                ):
                    out = await suggest_replies(card, sess, rows)
                self.assertEqual(out, ["你等我很久了？", "我只是路过", "转身就走", "说吧，什么事"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_keeps_leading_digits_without_separator(self):
        """"3天后再来"不该被当成编号剥掉开头。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                rows = await self._add_messages(session, sess, [("assistant", "你终于来了")])
                await session.commit()
                with patch(
                    "app.services.tavern_context.llm_client.get_agent_client",
                    return_value=("m", "openai"),
                ), patch(
                    "app.services.tavern_context.llm_client.dispatch_chat_complete",
                    return_value="3天后再来",
                ):
                    out = await suggest_replies(card, sess, rows)
                self.assertEqual(out, ["3天后再来"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_no_creator_note_in_prompt(self):
        """候选回复的 prompt 同样不能带上 creator_note。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                rows = await self._add_messages(session, sess, [("assistant", "你终于来了")])
                await session.commit()
                captured = {}

                async def fake(messages, **kwargs):
                    captured["messages"] = messages
                    return "随便说点什么"

                with patch(
                    "app.services.tavern_context.llm_client.get_agent_client",
                    return_value=("m", "openai"),
                ), patch(
                    "app.services.tavern_context.llm_client.dispatch_chat_complete",
                    side_effect=fake,
                ):
                    await suggest_replies(card, sess, rows)
                blob = json.dumps(captured["messages"], ensure_ascii=False)
                self.assertNotIn(SENTINEL, blob)
                # 组装没整体失效才算这条断言有效
                self.assertIn("林越", blob)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_empty_history_skips_llm(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                with patch(
                    "app.services.tavern_context.llm_client.get_agent_client",
                    side_effect=AssertionError("空历史不该调用模型"),
                ):
                    self.assertEqual(await suggest_replies(card, sess, []), [])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)


class TavernStopTests(unittest.TestCase):
    """停止生成：已吐出的半段必须落库，否则刷新页面就没了。"""

    _run = TavernContextTests._run
    _setup = TavernContextTests._setup

    async def _drive_and_stop(self, session, card, sess, user, chunks, stop_after):
        """跑 stream_turn，吐够 stop_after 个 token 后关掉生成器（= 前端按停止）。"""
        async def fake_stream(**_kwargs):
            for c in chunks:
                yield c

        maker = async_sessionmaker(session.bind, expire_on_commit=False)
        with patch.object(tavern_routes, "AsyncSessionLocal", maker), patch.object(
            tavern_routes.llm_client, "get_agent_client", return_value=("m", "openai")
        ), patch.object(
            tavern_routes.llm_client, "dispatch_chat_stream_with_usage", fake_stream
        ):
            response = await tavern_routes.stream_turn(
                sess.id, TavernTurnRequest(content="你好"), user, session,
            )
            body = response.body_iterator
            seen = 0
            async for _ in body:
                seen += 1
                if seen >= stop_after:
                    break
            await body.aclose()
            # 收尾是独立 task，等它跑完
            for task in list(tavern_routes._detached_tasks):
                await task

    def test_partial_reply_saved_when_stopped(self):
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                await session.commit()
                # meta + 前两个 token 之后就停
                await self._drive_and_stop(
                    session, card, sess, user, ["前半", "段", "后面这些不该出现"], 3,
                )
                rows = (await session.execute(
                    select(TavernMessage)
                    .where(TavernMessage.session_id == sess.id)
                    .order_by(TavernMessage.id)
                )).scalars().all()
                roles = [r.role for r in rows]
                self.assertEqual(roles, ["user", "assistant"])
                self.assertEqual(rows[1].content, "前半段")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_meta_carries_user_message_id_first(self):
        """meta 必须带上刚落库的用户消息 id，且排在最前面。

        前端靠它给刚发出的那句挂编辑按钮。之前漏了这个字段，表现是"发完要刷新
        页面才能编辑自己说的话"。meta 还必须早于模型解析——模型配错时那条消息
        已经入库了，不给 id 就永远编辑不了。
        """
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                await session.commit()

                async def fake_stream(**_kwargs):
                    yield "好"

                maker = async_sessionmaker(session.bind, expire_on_commit=False)
                with patch.object(tavern_routes, "AsyncSessionLocal", maker), patch.object(
                    tavern_routes.llm_client, "get_agent_client", return_value=("m", "openai")
                ), patch.object(
                    tavern_routes.llm_client, "dispatch_chat_stream_with_usage", fake_stream
                ):
                    response = await tavern_routes.stream_turn(
                        sess.id, TavernTurnRequest(content="你好"), user, session,
                    )
                    chunks = [c async for c in response.body_iterator]

                first = json.loads(chunks[0].split("data: ", 1)[1])
                self.assertEqual(first["event"], "meta")

                user_row = (await session.execute(
                    select(TavernMessage).where(
                        TavernMessage.session_id == sess.id,
                        TavernMessage.role == "user",
                    )
                )).scalars().one()
                self.assertEqual(first["data"]["user_message_id"], user_row.id)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_stop_before_any_token_writes_no_assistant_row(self):
        """一个字都没出就停：不留空的 assistant 行。"""
        async def scenario():
            engine, session, user, card, sess = await self._setup()
            try:
                await session.commit()
                await self._drive_and_stop(
                    session, card, sess, user, ["还没来得及"], 1,  # 只收 meta
                )
                rows = (await session.execute(
                    select(TavernMessage).where(TavernMessage.session_id == sess.id)
                )).scalars().all()
                self.assertEqual([r.role for r in rows], ["user"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)


class TavernOwnershipTests(unittest.TestCase):
    """跨用户访问一律 404（与"不存在"不可区分，防 id 枚举）。"""

    def _run(self, scenario):
        asyncio.run(scenario())

    async def _two_users(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)()
        alice = User(username="alice", password_hash="x")
        bob = User(username="bob", password_hash="x")
        session.add_all([alice, bob])
        await session.flush()
        card = TavernCard(user_id=bob.id, name="鲍勃的卡")
        session.add(card)
        await session.flush()
        sess = TavernSession(card_id=card.id)
        entry = TavernWorldEntry(card_id=card.id, keywords="x", content="y")
        session.add_all([sess, entry])
        await session.flush()
        msg = TavernMessage(session_id=sess.id, role="user", content="z")
        preset = TavernInstructionPreset(user_id=bob.id, name="鲍勃的指令", content="c")
        rule = TavernRule(user_id=bob.id, name="鲍勃的规则", content="c")
        session.add_all([msg, preset, rule])
        await session.commit()
        return engine, session, alice, bob, card, sess, entry, msg, preset, rule

    def test_cross_user_404(self):
        async def scenario():
            engine, session, alice, bob, card, sess, entry, msg, preset, rule = await self._two_users()
            try:
                for fn, target in (
                    (_get_owned_card, card.id),
                    (_get_owned_entry, entry.id),
                    (_get_owned_session, sess.id),
                    (_get_owned_message, msg.id),
                    (_get_owned_instruction_preset, preset.id),
                    (_get_owned_rule, rule.id),
                ):
                    # 本人可访问
                    self.assertIsNotNone(await fn(session, target, bob))
                    with self.assertRaises(HTTPException) as ctx:
                        await fn(session, target, alice)
                    self.assertEqual(ctx.exception.status_code, 404)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_missing_id_404(self):
        async def scenario():
            engine, session, alice, bob, card, sess, entry, msg, preset, rule = await self._two_users()
            try:
                for fn in (
                    _get_owned_card, _get_owned_entry, _get_owned_session,
                    _get_owned_message, _get_owned_instruction_preset, _get_owned_rule,
                ):
                    with self.assertRaises(HTTPException) as ctx:
                        await fn(session, 99999, bob)
                    self.assertEqual(ctx.exception.status_code, 404)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)


class TavernCardAssistTests(unittest.TestCase):
    """角色卡分栏 AI 辅助。这个接口不落库，只看喂给模型的 prompt 对不对。"""

    _run = TavernContextTests._run

    def _capture(self, coro_factory):
        captured = {}

        async def fake(messages, **kwargs):
            captured["messages"] = messages
            return "  模型写的内容  "

        async def scenario():
            with patch(
                "app.agents.tavern_card_agent.llm_client.get_agent_client",
                return_value=("m", "openai"),
            ), patch(
                "app.agents.tavern_card_agent.llm_client.dispatch_chat_complete",
                side_effect=fake,
            ):
                captured["result"] = await coro_factory()
        self._run(scenario)
        captured["blob"] = json.dumps(captured["messages"], ensure_ascii=False)
        return captured

    def test_generate_when_empty_optimize_when_filled(self):
        empty = self._capture(lambda: tavern_card_agent.assist_field(
            "personality", "", "林越", "", "", "",
        ))
        self.assertIn("从零写出", empty["blob"])
        # 结果两头的空白要剥掉，否则直接落进输入框会带着空行
        self.assertEqual(empty["result"], "模型写的内容")

        filled = self._capture(lambda: tavern_card_agent.assist_field(
            "personality", "表面温和，实际记仇", "林越", "表面温和，实际记仇", "", "",
        ))
        self.assertIn("保留原有的核心设定", filled["blob"])
        self.assertIn("表面温和，实际记仇", filled["blob"])

    def test_other_fields_come_in_as_context(self):
        cap = self._capture(lambda: tavern_card_agent.assist_field(
            "opening_scene", "", "林越", "记仇", "曾是黑塔的守夜人", "",
        ))
        self.assertIn("记仇", cap["blob"])
        self.assertIn("黑塔的守夜人", cap["blob"])

    def test_creator_note_built_from_personality_and_description(self):
        cap = self._capture(lambda: tavern_card_agent.assist_creator_note(
            "林越", "记仇", "曾是黑塔的守夜人", "",
        ))
        self.assertIn("记仇", cap["blob"])
        self.assertIn("黑塔的守夜人", cap["blob"])

    def test_creator_note_never_becomes_input(self):
        """creator_note 只能是产出。它是"AI 看不到的介绍"，喂回模型就破了这条。"""
        request = TavernCardAssistRequest(
            field="personality",
            name="林越",
            personality="记仇",
            description="守夜人",
        )
        self.assertNotIn("creator_note", request.model_dump())

    def test_creator_note_needs_source_material(self):
        async def scenario():
            with self.assertRaises(HTTPException) as ctx:
                await tavern_routes.assist_card_field(
                    TavernCardAssistRequest(field="creator_note", name="林越"), None,
                )
            self.assertEqual(ctx.exception.status_code, 400)
        self._run(scenario)

    def test_unknown_field_rejected(self):
        async def scenario():
            with self.assertRaises(HTTPException) as ctx:
                await tavern_routes.assist_card_field(
                    TavernCardAssistRequest(field="system_instruction"), None,
                )
            self.assertEqual(ctx.exception.status_code, 400)
        self._run(scenario)


class TavernGroupChatTests(unittest.TestCase):
    """群聊：一轮里多个角色依次发言，以及"卡引用卡"的共用世界书。"""

    _run = TavernContextTests._run

    async def _setup_group(self, names=("林越", "沈瑶光"), **extra):
        """建 n 张卡和一条把它们都拉进来的故事线。首张是主卡。"""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)()
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.flush()

        cards = []
        for name in names:
            card = TavernCard(
                user_id=user.id, name=name, creator_note=SENTINEL,
                personality=f"{name}的性格", description=f"{name}的详细设定",
                enabled_rule_ids=[], context_turns=20, **extra,
            )
            session.add(card)
            cards.append(card)
        await session.flush()

        sess = TavernSession(card_id=cards[0].id)
        session.add(sess)
        await session.flush()
        for order, card in enumerate(cards):
            session.add(TavernSessionCard(
                session_id=sess.id, card_id=card.id, sort_order=order,
            ))
        await session.flush()
        await session.commit()
        return engine, session, user, cards, sess

    async def _drive(self, session, sess, user, content, replies, stop_after=None):
        """跑一遍 stream_turn，返回收到的 SSE 事件列表。

        replies 是"每个说话人吐什么"，按调用顺序取。
        """
        calls = {"n": 0}

        async def fake_stream(**_kwargs):
            reply = replies[min(calls["n"], len(replies) - 1)]
            calls["n"] += 1
            for piece in reply:
                yield piece

        maker = async_sessionmaker(session.bind, expire_on_commit=False)
        with patch.object(tavern_routes, "AsyncSessionLocal", maker), patch.object(
            tavern_routes.llm_client, "get_agent_client", return_value=("m", "openai")
        ), patch.object(
            tavern_routes.llm_client, "dispatch_chat_stream_with_usage", fake_stream
        ):
            response = await tavern_routes.stream_turn(
                sess.id, TavernTurnRequest(content=content), user, session,
            )
            events = []
            body = response.body_iterator
            async for chunk in body:
                events.append(json.loads(chunk.split("data: ", 1)[1]))
                if stop_after and len(events) >= stop_after:
                    break
            if stop_after:
                await body.aclose()
                for task in list(tavern_routes._detached_tasks):
                    await task
        return events

    async def _messages(self, session, sess):
        return (await session.execute(
            select(TavernMessage)
            .where(TavernMessage.session_id == sess.id)
            .order_by(TavernMessage.id)
        )).scalars().all()

    # ── 发言顺序 ────────────────────────────────────────────────────────

    def test_unnamed_turn_lets_everyone_speak_in_order(self):
        """不点名：所有人按参与顺序各回一条，说话人记对。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                await self._drive(session, sess, user, "你们好", [["甲"], ["乙"]])
                rows = await self._messages(session, sess)
                self.assertEqual([r.role for r in rows], ["user", "assistant", "assistant"])
                self.assertIsNone(rows[0].card_id)
                self.assertEqual(
                    [rows[1].card_id, rows[2].card_id], [cards[0].id, cards[1].id]
                )
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_second_speaker_sees_first_reply(self):
        """第二个人的上下文里必须有第一个人刚说的话，否则两人各说各话。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                seen = []
                real = tavern_routes.tavern_context.build_tavern_messages

                async def spy(*args, **kwargs):
                    messages, diag = await real(*args, **kwargs)
                    seen.append(messages)
                    return messages, diag

                with patch.object(
                    tavern_routes.tavern_context, "build_tavern_messages", spy
                ):
                    await self._drive(session, sess, user, "你们好", [["第一句"], ["第二句"]])

                self.assertEqual(len(seen), 2)
                joined = "".join(m["content"] for m in seen[1])
                self.assertIn("第一句", joined)
                # 第一个人开口时当然还看不到
                self.assertNotIn("第一句", "".join(m["content"] for m in seen[0]))
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_at_mention_limits_to_one_speaker(self):
        """@点名：只有被点的人回。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                events = await self._drive(
                    session, sess, user, "@沈瑶光 你怎么看", [["我说"]],
                )
                rows = await self._messages(session, sess)
                self.assertEqual([r.role for r in rows], ["user", "assistant"])
                self.assertEqual(rows[1].card_id, cards[1].id)
                # @ 的文本留在消息里：玩家写的是台词，不是命令
                self.assertIn("@沈瑶光", rows[0].content)
                self.assertEqual(
                    [e["data"]["name"] for e in events if e["event"] == "speaker"],
                    [],  # 单人发言不发 speaker 事件
                )
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_at_unknown_name_falls_back_to_everyone(self):
        """@ 了一个不在场的名字：当作没点名，不报错。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                await self._drive(session, sess, user, "@路人甲 在吗", [["甲"], ["乙"]])
                rows = await self._messages(session, sess)
                self.assertEqual(len([r for r in rows if r.role == "assistant"]), 2)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_longest_name_wins_on_prefix_collision(self):
        """「林」和「林越」同场时，@林越 不能被「林」抢走。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group(
                names=("林", "林越"),
            )
            try:
                await self._drive(session, sess, user, "@林越 说话", [["我"]])
                rows = await self._messages(session, sess)
                assistants = [r for r in rows if r.role == "assistant"]
                self.assertEqual(len(assistants), 1)
                self.assertEqual(assistants[0].card_id, cards[1].id)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_speaker_event_precedes_tokens(self):
        """群聊每人开口前发一次 speaker，前端要靠它建气泡。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                events = await self._drive(session, sess, user, "在？", [["甲"], ["乙"]])
                order = [e["event"] for e in events]
                self.assertEqual(order[0], "speaker")
                self.assertEqual(order[1], "meta")
                self.assertEqual(
                    [e["data"]["card_id"] for e in events if e["event"] == "speaker"],
                    [cards[0].id, cards[1].id],
                )
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_user_message_id_only_in_first_meta(self):
        """user_message_id 只在第一个人的 meta 里带，后面几份不重复。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                events = await self._drive(session, sess, user, "在？", [["甲"], ["乙"]])
                metas = [e["data"] for e in events if e["event"] == "meta"]
                self.assertEqual(len(metas), 2)
                self.assertTrue(metas[0]["user_message_id"])
                self.assertNotIn("user_message_id", metas[1])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_model_self_added_name_prefix_stripped(self):
        """群聊提示词里有"谁说的"标注，模型会照格式给自己也加前缀，要去掉。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                await self._drive(
                    session, sess, user, "在？", [["林越：", "我在"], ["乙"]],
                )
                rows = await self._messages(session, sess)
                self.assertEqual(rows[1].content, "我在")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    # ── 上下文组装 ──────────────────────────────────────────────────────

    async def _build(self, session, cards, sess, speaker, history=(), text="在？"):
        return await build_tavern_messages(
            session, list(cards), sess, list(history), text, speaker=speaker,
        )

    def test_onstage_others_get_personality_without_details(self):
        """同场角色只给名字和性格，不给详细设定——省 token，也免得替他发言。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                messages, _ = await self._build(session, cards, sess, cards[0])
                system = messages[0]["content"]
                self.assertIn("沈瑶光的性格", system)
                self.assertNotIn("沈瑶光的详细设定", system)
                # 当前说话人的详细设定要给全
                self.assertIn("林越的详细设定", system)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_creator_note_never_leaks_in_group(self):
        """群聊也不能漏 creator_note，任何一位说话时都不行。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                for speaker in cards:
                    messages, diag = await self._build(session, cards, sess, speaker)
                    self.assertNotIn(SENTINEL, json.dumps(messages, ensure_ascii=False))
                    self.assertNotIn(SENTINEL, json.dumps(diag, ensure_ascii=False))
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_examples_degrade_to_text_in_group(self):
        """多卡时对话示例不拼真实 few-shot 轮，改成 system 里的文字。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group(
                dialogue_examples=[{"user": "你是谁", "assistant": "无名之辈"}],
            )
            try:
                messages, diag = await self._build(session, cards, sess, cards[0])
                # 只剩 system + 玩家这一句，没有多出来的 user/assistant 对
                self.assertEqual(len(messages), 2)
                self.assertEqual([m["role"] for m in messages], ["system", "user"])
                self.assertIn("无名之辈", messages[0]["content"])
                self.assertIn("林越的说话样例", messages[0]["content"])
                self.assertEqual(diag["examples_used"], 1)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_history_lines_labelled_with_speaker(self):
        """群聊历史要标谁说的，否则几个角色的话糊成一团。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                rows = []
                for card, text in ((cards[0], "甲说"), (cards[1], "乙说")):
                    row = TavernMessage(
                        session_id=sess.id, role="assistant",
                        card_id=card.id, content=text,
                    )
                    session.add(row)
                    rows.append(row)
                await session.flush()

                messages, _ = await self._build(session, cards, sess, cards[0], rows)
                history = [m["content"] for m in messages if m["role"] == "assistant"]
                self.assertEqual(history, ["林越：甲说", "沈瑶光：乙说"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_placeholder_resolves_per_text_owner(self):
        """{{char}} 按文本归属替换：别人的性格里写 {{char}} 指的是他自己。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                cards[1].personality = "{{char}}从不解释"
                await session.flush()
                messages, _ = await self._build(session, cards, sess, cards[0])
                self.assertIn("沈瑶光从不解释", messages[0]["content"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_group_rules_are_union_without_duplicates(self):
        """两张卡勾了同一条规则，只注入一遍。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                rule = TavernRule(user_id=user.id, name="r", content="共同规则")
                session.add(rule)
                await session.flush()
                for card in cards:
                    card.enabled_rule_ids = [rule.id]
                await session.flush()

                messages, diag = await self._build(session, cards, sess, cards[0])
                self.assertEqual(messages[0]["content"].count("共同规则"), 1)
                self.assertEqual(diag["rules_used"], 1)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_scan_depth_takes_max_across_cards(self):
        """扫描范围取参与卡里的最大值：取小会让另一张卡的词条静默失效。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                cards[0].scan_depth = 1
                cards[1].scan_depth = 3
                session.add(TavernWorldEntry(
                    card_id=cards[1].id, keywords="黑塔", content="黑塔已经塌了",
                ))
                rows = []
                for text in ("提到黑塔", "换了话题"):
                    row = TavernMessage(session_id=sess.id, role="user", content=text)
                    session.add(row)
                    rows.append(row)
                await session.flush()

                messages, diag = await self._build(session, cards, sess, cards[0], rows)
                self.assertIn("黑塔已经塌了", messages[0]["content"])
                self.assertEqual(len(diag["triggered"]), 1)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    # ── 共用世界书（卡引用卡）────────────────────────────────────────────

    def test_linked_card_entries_trigger_in_solo_chat(self):
        """A 引用 B 的世界书：单聊 A 时 B 的词条也能被触发。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                cards[0].linked_book_card_ids = [cards[1].id]
                session.add(TavernWorldEntry(
                    card_id=cards[1].id, keywords="黑塔", content="黑塔的规矩",
                ))
                await session.flush()

                messages, diag = await self._build(
                    session, [cards[0]], sess, cards[0], text="聊聊黑塔",
                )
                self.assertIn("黑塔的规矩", messages[0]["content"])
                self.assertEqual(len(diag["triggered"]), 1)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_mutual_links_inject_entry_once(self):
        """两张卡互相引用，同一条词条不重复注入。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                cards[0].linked_book_card_ids = [cards[1].id]
                cards[1].linked_book_card_ids = [cards[0].id]
                session.add(TavernWorldEntry(
                    card_id=cards[1].id, keywords="黑塔", content="黑塔的规矩",
                ))
                await session.flush()

                messages, diag = await self._build(
                    session, cards, sess, cards[0], text="聊聊黑塔",
                )
                self.assertEqual(messages[0]["content"].count("黑塔的规矩"), 1)
                self.assertEqual(len(diag["triggered"]), 1)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_linked_entry_placeholder_uses_owner_name(self):
        """引用来的词条里写 {{char}}，指的是它所属那张卡，不是当前说话人。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                cards[0].linked_book_card_ids = [cards[1].id]
                session.add(TavernWorldEntry(
                    card_id=cards[1].id, keywords="黑塔", content="{{char}}守过黑塔",
                ))
                await session.flush()

                messages, _ = await self._build(
                    session, [cards[0]], sess, cards[0], text="聊聊黑塔",
                )
                self.assertIn("沈瑶光守过黑塔", messages[0]["content"])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_cannot_link_other_users_world_book(self):
        """引用别人的卡 id 读不到词条——否则填个 id 就能翻别人的世界书。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                bob = User(username="bob", password_hash="x")
                session.add(bob)
                await session.flush()
                stranger = TavernCard(user_id=bob.id, name="外人", enabled_rule_ids=[])
                session.add(stranger)
                await session.flush()
                session.add(TavernWorldEntry(
                    card_id=stranger.id, keywords="黑塔", content="别人的秘密",
                ))
                cards[0].linked_book_card_ids = [stranger.id]
                await session.flush()

                messages, diag = await self._build(
                    session, [cards[0]], sess, cards[0], text="聊聊黑塔",
                )
                self.assertNotIn("别人的秘密", messages[0]["content"])
                self.assertEqual(diag["triggered"], [])
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_stop_keeps_finished_speakers_intact(self):
        """中途停止：说完的人的消息完整，当前这位只留半段。"""
        async def scenario():
            engine, session, user, cards, sess = await self._setup_group()
            try:
                # speaker+meta+甲+done+speaker+meta+半 = 7 个事件后停
                await self._drive(
                    session, sess, user, "在？",
                    [["甲说完了"], ["半段", "这段不该出现"]], stop_after=7,
                )
                rows = await self._messages(session, sess)
                self.assertEqual([r.role for r in rows], ["user", "assistant", "assistant"])
                self.assertEqual(rows[1].content, "甲说完了")
                self.assertEqual(rows[1].card_id, cards[0].id)
                self.assertEqual(rows[2].content, "半段")
                self.assertEqual(rows[2].card_id, cards[1].id)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
