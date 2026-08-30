"""黄金三章开篇要求：注入范围、三章不串档、自定义提示词下不丢。

前三章决定一本书能不能被平台推出去，所以这块是硬要求而非文风偏好，
必须像护栏一样走追加路径，不能被自定义写手提示词整段替换掉。
"""
import unittest

from app.agents.writer import OPENING_CHAPTERS, _compose_system_prompt, _opening_block
from app.prompts.loader import render


def base(chapter_number=None):
    kwargs = dict(genre="仙侠", writing_style="冷峻", target_words=3000)
    if chapter_number is not None:
        kwargs["chapter_number"] = chapter_number
    return render("writer.jinja2", **kwargs)


class InjectRangeTests(unittest.TestCase):
    def test_first_three_chapters_get_the_block(self):
        for n in range(1, OPENING_CHAPTERS + 1):
            self.assertTrue(_opening_block(n), f"第{n}章应有开篇要求")

    def test_fourth_chapter_onward_has_none(self):
        for n in (OPENING_CHAPTERS + 1, 10, 300):
            self.assertEqual(_opening_block(n), "", f"第{n}章不该有开篇要求")

    def test_missing_or_bogus_chapter_number_is_silent(self):
        """章号取不到时不注入，也不报错——不能让开篇要求漏进第 500 章。"""
        for bad in (None, "", "1", 0, -1, 1.0, True):
            self.assertEqual(_opening_block(bad), "", f"{bad!r} 不该注入")


class NoCrossTalkTests(unittest.TestCase):
    def test_each_chapter_states_its_own_task(self):
        for n, marker in ((1, "第一章的任务"), (2, "第二章的任务"), (3, "第三章的任务")):
            block = _opening_block(n)
            self.assertIn(marker, block)
            others = {"第一章的任务", "第二章的任务", "第三章的任务"} - {marker}
            for other in others:
                self.assertNotIn(other, block, f"第{n}章串进了{other}")

    def test_chapter_one_demands_protagonist_early(self):
        self.assertIn("300 字", _opening_block(1))

    def test_payoff_requirement_only_lands_on_chapter_three(self):
        """爽点兑现是第三章的活。第一章要求兑现会把开局写成高潮。"""
        self.assertNotIn("爽点", _opening_block(1))
        self.assertIn("爽点必须落地", _opening_block(3))

    def test_every_chapter_declares_priority(self):
        for n in range(1, OPENING_CHAPTERS + 1):
            self.assertIn("优先服从", _opening_block(n))


class ContinuityLineTests(unittest.TestCase):
    def test_chapter_one_is_not_told_to_continue_from_previous(self):
        """第一章没有上一章，这条指令自相矛盾，曾让开篇写得像半路开始。"""
        self.assertNotIn("衔接上一章", base(1))

    def test_later_chapters_keep_the_continuity_line(self):
        for n in (2, 3, 4, 99):
            self.assertIn("衔接上一章", base(n), f"第{n}章丢了衔接要求")

    def test_absent_chapter_number_keeps_old_behavior(self):
        """有调用点忘传章号时保持改动前的输出，不静默改变老书行为。"""
        self.assertIn("衔接上一章", base(None))


class ComposeTests(unittest.TestCase):
    def test_custom_prompt_still_carries_opening(self):
        """自定义提示词整段替换模板，开篇要求必须照旧追加。"""
        content, source = _compose_system_prompt(
            "你是我的专属写手", base(1),
            {"chapter_number": 1, "writing_style": "冷峻", "_rules_block": "规则X"},
        )
        self.assertIn("第一章的任务", content)
        self.assertEqual(source, "custom+rules+opening")
        # 顺序：自定义 → 风格 → 规则 → 开篇
        self.assertLess(content.index("规则X"), content.index("第一章的任务"))

    def test_source_marks_absence_after_third_chapter(self):
        _, source = _compose_system_prompt(
            "", base(4), {"chapter_number": 4, "_rules_block": "规则X"},
        )
        self.assertEqual(source, "template+rules")

    def test_opening_survives_user_disabling_all_rules(self):
        """规则全关是用户的选择，但开篇要求是平台硬要求，不跟着一起消失。"""
        content, source = _compose_system_prompt(
            "", base(1), {"chapter_number": 1, "_rules_block": ""},
        )
        self.assertIn("第一章的任务", content)
        self.assertEqual(source, "template+norules+opening")


if __name__ == "__main__":
    unittest.main()
