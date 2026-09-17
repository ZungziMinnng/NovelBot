"""RPG 提示词模板：默认模板能渲染、用户覆盖能生效、写坏了能拦住。

拦得住比渲染得出重要：这些模板是用户可以在设置页里随便改的，一个
{{ 不存在的变量 }} 必须在保存那一刻报错，而不是等到玩家按下回车才炸。
"""
import unittest

from fastapi import HTTPException
from jinja2 import TemplateError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.rpg_prompts import PromptUpdate, list_prompts, reset_prompt, update_prompt
from app.models.user import User
# 这行看着没用，其实是 load-bearing：SQLAlchemy 配 mapper 时要能按类名找到
# Chapter、Card 这些字符串关系指向的类。少 import 一个模块就是
# InvalidRequestError，报的还是别的表
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, prompt_rule, tavern as _tavern, rpg as _rpg
from app.services import rpg_prompts
from app.services.auth import current_user_var


class _FakeUser:
    def __init__(self, overrides=None):
        self.rpg_prompts = overrides


class RpgPromptTests(unittest.TestCase):
    def setUp(self):
        self.token = current_user_var.set(_FakeUser())

    def tearDown(self):
        current_user_var.reset(self.token)

    def test_every_default_template_validates(self):
        # 12 = GM / 裁决 / 判定注入 / 结算 / 建议 / 梗概 / 外场简报 / 角色自由行动 / 帮我写
        #      / 构思向导对话 / 构思向导抽取 / 一键生成
        self.assertEqual(len(rpg_prompts.PROMPTS), 14)
        for name in rpg_prompts.PROMPTS:
            with self.subTest(name=name):
                rpg_prompts.validate(name, rpg_prompts.default_content(name))

    def test_falls_back_to_the_default_file(self):
        text = rpg_prompts.render("rpg_gm.jinja2", char_name="阿隼", reply_length=300)
        self.assertIn("阿隼", text)
        self.assertIn("300", text)

    def test_override_wins_and_does_not_leak_to_others(self):
        current_user_var.set(_FakeUser({"rpg_gm.jinja2": "演 {{ char_name }}"}))
        self.assertEqual(
            rpg_prompts.render("rpg_gm.jinja2", char_name="阿隼", reply_length=0),
            "演 阿隼",
        )
        current_user_var.set(_FakeUser())
        self.assertIn("主持人", rpg_prompts.render("rpg_gm.jinja2", char_name="阿隼", reply_length=0))

    def test_bad_templates_are_rejected(self):
        for content in (
            "{% if %}",                       # 语法坏了
            "{{ 不存在的变量 }}",              # 变量表里没有
            "{{ char_name.__class__.__mro__ }}",  # 想从沙箱里爬出去
            "{% include 'writer.jinja2' %}",  # 想读别的模板
        ):
            with self.subTest(content=content):
                with self.assertRaises(Exception):
                    rpg_prompts.validate("rpg_gm.jinja2", content)

    def test_empty_collections_path_is_validated_too(self):
        # 只渲染一遍（全都有值）的话，空列表那条路径永远没被走过。
        # 下面这个模板有值时好好的，第一局还没有判定记录时就炸
        with self.assertRaises(Exception):
            rpg_prompts.validate(
                "rpg_adjudicate.jinja2", "{{ action }} 上次是 {{ ledger[0].band }}"
            )

    def test_missing_runtime_variable_fails_loudly(self):
        current_user_var.set(_FakeUser({"rpg_gm.jinja2": "{{ reply_length }}"}))
        with self.assertRaises(TemplateError):
            rpg_prompts.render("rpg_gm.jinja2", char_name="阿隼")


class RpgPromptRouteTests(unittest.IsolatedAsyncioTestCase):
    """设置页那三个端点。存的是每用户一份 JSON，所以隔离性也得测
    ——写错成共享的话，一个人改模板全站跟着变，界面上看不出来。
    """

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.owner = User(username="owner", password_hash="unused")
        self.other = User(username="other", password_hash="unused")
        self.db.add_all([self.owner, self.other])
        await self.db.commit()
        self.token = current_user_var.set(self.owner)

    async def asyncTearDown(self):
        current_user_var.reset(self.token)
        await self.db.close()
        await self.engine.dispose()

    async def test_defaults_validate_and_list(self):
        prompts = await list_prompts(self.owner)
        self.assertEqual(len(prompts), 14)
        for prompt in prompts:
            self.assertFalse(prompt.customized)
            self.assertEqual(prompt.content, prompt.default_content)
            rpg_prompts.validate(prompt.name, prompt.content)

    async def test_persistence_isolation_and_reset(self):
        name = "rpg_gm.jinja2"
        saved = await update_prompt(name, PromptUpdate(content="你好 {{ char_name }}"), self.owner, self.db)
        self.assertTrue(saved.customized)
        async with self.sessions() as fresh_db:
            fresh_owner = await fresh_db.get(User, self.owner.id)
            self.assertEqual(fresh_owner.rpg_prompts[name], "你好 {{ char_name }}")
        self.assertEqual(rpg_prompts.render(name, char_name="阿隼"), "你好 阿隼")

        current_user_var.set(self.other)
        self.assertNotIn(name, self.other.rpg_prompts)
        self.assertTrue(all(not prompt.customized for prompt in await list_prompts(self.other)))

        current_user_var.set(self.owner)
        restored = await reset_prompt(name, self.owner, self.db)
        self.assertFalse(restored.customized)
        self.assertEqual(restored.content, restored.default_content)

    async def test_invalid_templates_do_not_persist(self):
        for content in (" ", "{% if %}", "{{ unknown }}", "{{ char_name.__class__.__mro__ }}", "{% include 'writer.jinja2' %}"):
            with self.subTest(content=content):
                with self.assertRaises(HTTPException) as raised:
                    await update_prompt("rpg_gm.jinja2", PromptUpdate(content=content), self.owner, self.db)
                self.assertEqual(raised.exception.status_code, 400)
                self.assertEqual(self.owner.rpg_prompts, {})

    async def test_unknown_names_rejected(self):
        for name in ("writer.jinja2", "../config.py"):
            with self.assertRaises(HTTPException) as raised:
                await update_prompt(name, PromptUpdate(content="test"), self.owner, self.db)
            self.assertEqual(raised.exception.status_code, 404)
            with self.assertRaises(HTTPException):
                await reset_prompt(name, self.owner, self.db)


if __name__ == "__main__":
    unittest.main()
