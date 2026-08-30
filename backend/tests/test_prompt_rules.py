"""规则广场解析测试：三态语义 + 护栏永不静默消失。"""
import asyncio
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user  # noqa: F401
from app.models.novel import Novel
from app.models.prompt_rule import PromptRule
from app.models.user import User
from app.prompts.loader import render
from app.services.prompt_rules import resolve_rules_block

GUARDRAILS = render("writer_guardrails.jinja2").strip()


class PromptRulesTests(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    async def _setup(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)()
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.flush()
        novel = Novel(title="书", user_id=user.id)
        session.add(novel)
        await session.flush()
        return engine, session, user, novel

    def _builtin(self, user_id, content=GUARDRAILS):
        return PromptRule(
            user_id=user_id, name="去AI味", content=content,
            category="guardrail", enabled=True,
            is_builtin=True, builtin_key="writer_guardrails", sort_order=0,
        )

    def test_null_selection_uses_builtin(self):
        """从未配置 → 内置规则，且输出与模板逐字节相同（老书零行为变化）。"""
        async def scenario():
            engine, session, user, novel = await self._setup()
            try:
                session.add(self._builtin(user.id))
                await session.commit()
                self.assertIsNone(novel.enabled_rule_ids)
                block = await resolve_rules_block(session, novel)
                self.assertEqual(block, GUARDRAILS)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_null_selection_empty_table_falls_back(self):
        """种子没跑/失败 → 必须回退到模板，绝不返回空。"""
        async def scenario():
            engine, session, user, novel = await self._setup()
            try:
                await session.commit()
                block = await resolve_rules_block(session, novel)
                self.assertEqual(block, GUARDRAILS)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_null_selection_all_disabled_falls_back(self):
        """内置规则被全部停用但用户从未配置本书 → 仍然兜底。"""
        async def scenario():
            engine, session, user, novel = await self._setup()
            try:
                rule = self._builtin(user.id)
                rule.enabled = False
                session.add(rule)
                await session.commit()
                block = await resolve_rules_block(session, novel)
                self.assertEqual(block, GUARDRAILS)
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_empty_list_is_explicit_optout(self):
        """[] = 用户显式全关，必须返回空，不能兜底。"""
        async def scenario():
            engine, session, user, novel = await self._setup()
            try:
                session.add(self._builtin(user.id))
                novel.enabled_rule_ids = []
                await session.commit()
                block = await resolve_rules_block(session, novel)
                self.assertEqual(block, "")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_explicit_selection_join_order(self):
        """显式勾选按库里的 sort_order 拼接，不按数组顺序。"""
        async def scenario():
            engine, session, user, novel = await self._setup()
            try:
                a = PromptRule(user_id=user.id, name="A", content="规则A", enabled=True, sort_order=1)
                b = PromptRule(user_id=user.id, name="B", content="规则B", enabled=True, sort_order=2)
                session.add_all([a, b])
                await session.flush()
                # 故意倒序传入
                novel.enabled_rule_ids = [b.id, a.id]
                await session.commit()
                block = await resolve_rules_block(session, novel)
                self.assertEqual(block, "规则A\n\n规则B")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_disabled_rule_excluded_from_explicit_selection(self):
        async def scenario():
            engine, session, user, novel = await self._setup()
            try:
                a = PromptRule(user_id=user.id, name="A", content="规则A", enabled=True, sort_order=1)
                b = PromptRule(user_id=user.id, name="B", content="规则B", enabled=False, sort_order=2)
                session.add_all([a, b])
                await session.flush()
                novel.enabled_rule_ids = [a.id, b.id]
                await session.commit()
                block = await resolve_rules_block(session, novel)
                self.assertEqual(block, "规则A")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_cross_user_rule_ignored(self):
        """别人的规则 id 就算写进本书也不生效。"""
        async def scenario():
            engine, session, user, novel = await self._setup()
            try:
                bob = User(username="bob", password_hash="x")
                session.add(bob)
                await session.flush()
                mine = PromptRule(user_id=user.id, name="我的", content="我的规则", enabled=True, sort_order=1)
                theirs = PromptRule(user_id=bob.id, name="他的", content="他的规则", enabled=True, sort_order=0)
                session.add_all([mine, theirs])
                await session.flush()
                novel.enabled_rule_ids = [mine.id, theirs.id]
                await session.commit()
                block = await resolve_rules_block(session, novel)
                self.assertEqual(block, "我的规则")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_stale_id_after_delete_is_harmless(self):
        """规则删除后残留的 id 不报错，静默忽略。"""
        async def scenario():
            engine, session, user, novel = await self._setup()
            try:
                a = PromptRule(user_id=user.id, name="A", content="规则A", enabled=True, sort_order=1)
                session.add(a)
                await session.flush()
                novel.enabled_rule_ids = [a.id, 99999]
                await session.commit()
                block = await resolve_rules_block(session, novel)
                self.assertEqual(block, "规则A")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_blank_content_rule_skipped(self):
        """内容为空的规则不该在拼接处留下空行。"""
        async def scenario():
            engine, session, user, novel = await self._setup()
            try:
                a = PromptRule(user_id=user.id, name="A", content="规则A", enabled=True, sort_order=1)
                blank = PromptRule(user_id=user.id, name="空", content="   ", enabled=True, sort_order=2)
                c = PromptRule(user_id=user.id, name="C", content="规则C", enabled=True, sort_order=3)
                session.add_all([a, blank, c])
                await session.flush()
                novel.enabled_rule_ids = [a.id, blank.id, c.id]
                await session.commit()
                block = await resolve_rules_block(session, novel)
                self.assertEqual(block, "规则A\n\n规则C")
            finally:
                await session.close()
                await engine.dispose()
        self._run(scenario)

    def test_writer_prompt_identical_to_old_include(self):
        """老书（未配置规则、无自定义提示词）拼出的 prompt 里，护栏块与 include 时代逐字节相同。

        改动前 writer.jinja2 末行是 {% include "writer_guardrails.jinja2" %}，护栏改由规则
        广场注入后，这里验证注入结果与当年 include 出来的完全一致——模板正文本身会随功能
        增补而变（如章尾钩子清单），所以不再整体比对。
        """
        from app.agents.writer import _compose_system_prompt

        kwargs = dict(genre="仙侠", writing_style="冷峻", target_words=5000)
        base = render("writer.jinja2", **kwargs)
        content, source = _compose_system_prompt("", base, {"_rules_block": GUARDRAILS})

        self.assertEqual(source, "template+rules")
        # 护栏块整段落在末尾，且与模板渲染结果逐字节一致
        self.assertTrue(content.endswith(render("writer_guardrails.jinja2").strip()))
        # 模板正文（去掉护栏）仍以字数要求收尾，中间不该被规则块插队
        body = content[: -len(render("writer_guardrails.jinja2").strip())]
        self.assertIn("目标字数 5000 字", body)
        self.assertIn("章节结尾必须留下", body)

    def test_writer_prompt_marks_missing_rules(self):
        """显式全关时 system_source 要能一眼看出规则块没了。"""
        from app.agents.writer import _compose_system_prompt

        base = render("writer.jinja2", genre="仙侠", writing_style="冷峻", target_words=5000)
        content, source = _compose_system_prompt("", base, {"_rules_block": ""})
        self.assertEqual(source, "template+norules")
        self.assertNotIn("一致性与文风底线", content)

    def test_writer_prompt_custom_keeps_rules(self):
        """自定义提示词分支：风格与规则都要追加，顺序不变。"""
        from app.agents.writer import _compose_system_prompt

        content, source = _compose_system_prompt(
            "你是我的专属写手", "（模板不该出现）",
            {"writing_style": "冷峻", "_rules_block": "规则X"},
        )
        self.assertEqual(content, "你是我的专属写手\n\n【文章风格】\n冷峻\n\n规则X")
        self.assertEqual(source, "custom+rules")

    def test_db_error_falls_back(self):
        """数据库出问题只能退化成今天的行为，不能退化成裸 prompt。"""
        async def scenario():
            engine, session, user, novel = await self._setup()
            try:
                await session.close()  # 关掉 session，制造查询异常
                block = await resolve_rules_block(session, novel)
                self.assertEqual(block, GUARDRAILS)
            finally:
                await engine.dispose()
        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
