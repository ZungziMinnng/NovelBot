"""RPG 提示词模板：默认模板能渲染、用户覆盖能生效、写坏了能拦住。

拦得住比渲染得出重要：这些模板是用户可以在设置页里随便改的，一个
{{ 不存在的变量 }} 必须在保存那一刻报错，而不是等到玩家按下回车才炸。
"""
import unittest

from jinja2 import TemplateError

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
        self.assertEqual(len(rpg_prompts.PROMPTS), 6)
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


if __name__ == "__main__":
    unittest.main()
