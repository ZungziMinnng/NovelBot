"""章纲计划字段：解析、枚举对齐、剥离计划行、渲染注入行。"""
import unittest

from app.services import outline_plan


class ParsePlanTests(unittest.TestCase):
    RAW = (
        "本章定位：高压\n"
        "情绪基调：爽快\n"
        "情绪强度：4\n"
        "章尾钩子：紧急危机\n"
        "钩子强度：5\n"
        "主角在拍卖会上拿下丹药，被长老当场拦下。"
    )

    def test_parses_all_fields(self):
        self.assertEqual(outline_plan.parse_plan(self.RAW), {
            "chapter_role": "高压", "emotion_tone": "爽快", "emotion_intensity": 4,
            "hook_type": "紧急危机", "hook_strength": 5,
        })

    def test_missing_fields_absent_not_zero(self):
        """抽不到的键不出现，避免用 **plan 时把 0/'' 覆盖掉模型未指定的列。"""
        plan = outline_plan.parse_plan("第1章：开场\n主角登场。")
        self.assertEqual(plan, {})

    def test_halfwidth_colon(self):
        self.assertEqual(outline_plan.parse_plan("本章定位: 推进")["chapter_role"], "推进")

    def test_enum_alignment_tolerates_suffix(self):
        self.assertEqual(outline_plan.parse_plan("本章定位：高压章")["chapter_role"], "高压")
        self.assertEqual(outline_plan.parse_plan("章尾钩子：留白钩子")["hook_type"], "留白")

    def test_unknown_enum_dropped(self):
        self.assertNotIn("chapter_role", outline_plan.parse_plan("本章定位：随便写写"))
        self.assertNotIn("hook_type", outline_plan.parse_plan("章尾钩子：某种钩"))

    def test_out_of_range_intensity_not_matched(self):
        self.assertNotIn("emotion_intensity", outline_plan.parse_plan("情绪强度：9"))


class CleanPlanTests(unittest.TestCase):
    def test_valid_json_plan(self):
        self.assertEqual(outline_plan.clean_plan({
            "chapter_role": "推进", "emotion_tone": "紧张", "emotion_intensity": 3,
            "hook_type": "倒计时", "hook_strength": 2,
        }), {
            "chapter_role": "推进", "emotion_tone": "紧张", "emotion_intensity": 3,
            "hook_type": "倒计时", "hook_strength": 2,
        })

    def test_garbage_dropped_not_raised(self):
        self.assertEqual(outline_plan.clean_plan({
            "chapter_role": "瞎写", "emotion_intensity": "很高", "hook_strength": 0,
        }), {})

    def test_ignores_unrelated_keys(self):
        plan = outline_plan.clean_plan({"chapter": 3, "content": "x", "chapter_role": "高压"})
        self.assertEqual(plan, {"chapter_role": "高压"})


class StripPlanTests(unittest.TestCase):
    def test_strips_plan_lines_keeps_body(self):
        body = outline_plan.strip_plan_lines(ParsePlanTests.RAW)
        self.assertEqual(body, "主角在拍卖会上拿下丹药，被长老当场拦下。")

    def test_never_returns_empty(self):
        """全是计划行时不能把大纲清空，否则本章大纲直接丢了。"""
        only_plan = "本章定位：高压\n钩子强度：5"
        self.assertTrue(outline_plan.strip_plan_lines(only_plan))

    def test_leaves_normal_text_alone(self):
        text = "主角进城，发现城门贴着通缉令。"
        self.assertEqual(outline_plan.strip_plan_lines(text), text)


class FormatPlanTests(unittest.TestCase):
    def test_renders_populated_fields(self):
        line = outline_plan.format_plan(
            chapter_role="高压", emotion_tone="爽快", emotion_intensity=4,
            hook_type="紧急危机", hook_strength=5,
        )
        self.assertIn("本章定位：高压", line)
        self.assertIn("强度 4/5", line)
        self.assertIn("「紧急危机」", line)

    def test_empty_plan_renders_empty(self):
        self.assertEqual(outline_plan.format_plan(), "")

    def test_partial_plan_skips_blanks(self):
        line = outline_plan.format_plan(hook_type="留白")
        self.assertEqual(line, "章尾用「留白」收束")


class HookListSyncTests(unittest.TestCase):
    def test_writer_template_lists_every_hook_type(self):
        """模板里的 13 式必须与 HOOK_TYPES 同源，少一个就是清单不同步。"""
        from app.prompts.loader import render
        tpl = render("writer.jinja2", genre="玄幻", writing_style="爽文", target_words=3000)
        for name in outline_plan.HOOK_TYPES:
            self.assertIn(name, tpl, f"writer.jinja2 缺钩子写法「{name}」")


if __name__ == "__main__":
    unittest.main()
