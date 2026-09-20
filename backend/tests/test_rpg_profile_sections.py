"""详细档案的键。

RPG 的详细档案（profile_sections）存中文键，而且**键就是拼进提示词的标签**
（rpg_context 的 _one_npc 拿 key 当标题直接拼）。向导早期版本照酒馆那套发了英文键
——酒馆是「存英文、显示时翻中文」，方向正好相反——于是内容在库里躺着、也照发进了
提示词（标签是 background：），编辑器按中文键取却永远是空的。

这两条用例钉住的就是：读出来的时候一定归一到中文，且外貌只占一个位置。
"""
import unittest
from datetime import datetime

from app.models.rpg import normalize_profile_sections
from app.schemas.rpg import RpgNpcOut


class NormalizeTests(unittest.TestCase):
    def test_english_keys_become_chinese(self):
        sections, appearance = normalize_profile_sections({
            "background": "出身矿工家庭。",
            "abilities": "会看矿脉。",
            "relationships": "欠老周三块钱。",
        })
        self.assertEqual(sections, {
            "背景故事": "出身矿工家庭。",
            "能力特长": "会看矿脉。",
            "关系网络": "欠老周三块钱。",
        })
        self.assertEqual(appearance, "")

    def test_an_unknown_key_is_kept_as_is(self):
        # 认不出的键原样留着：它照样是模型填的内容，悄悄吃掉比留着糟
        sections, _ = normalize_profile_sections({"mood": "不提从前。"})
        self.assertEqual(sections, {"mood": "不提从前。"})

    def test_the_section_appearance_steps_aside_for_the_real_field(self):
        sections, appearance = normalize_profile_sections(
            {"appearance": "左脸一道疤，缺了半只耳朵。", "background": "矿工。"},
            "左脸一道疤。",
        )
        self.assertEqual(appearance, "左脸一道疤。")
        self.assertEqual(sections, {"背景故事": "矿工。"})

    def test_the_section_appearance_fills_an_empty_field(self):
        # 模型漏填了顶层那一栏，分栏里却有——搬家，不是丢掉
        _, appearance = normalize_profile_sections({"外貌身材": "左脸一道疤。"}, "")
        self.assertEqual(appearance, "左脸一道疤。")

    def test_blank_entries_do_not_occupy_a_section(self):
        sections, appearance = normalize_profile_sections(
            {"background": "   ", "abilities": None, "relationships": "有。"}, "",
        )
        self.assertEqual(sections, {"关系网络": "有。"})
        self.assertEqual(appearance, "")


class RpgNpcOutTests(unittest.TestCase):
    def test_the_payload_carries_chinese_keys(self):
        # 编辑器按 PROFILE_KEYS 那三个中文键取值，向导生成的模组原先三个框全是空的。
        # 归一就发生在读出来的这一步，前端拿到手时已经是中文
        now = datetime(2026, 9, 18)
        out = RpgNpcOut.model_validate({
            "id": 1, "module_id": 1, "name": "纲手", "role": "npc",
            "avatar_url": "", "description": "", "persona": "",
            "appearance": "百豪之术维持的完美肉体",
            "location": "", "slot_locations": {}, "keywords": "",
            "ai_scheduled": False,
            "profile_sections": {
                "background": "前代火影，退位后过着闲散的生活，经常在酒馆买醉",
                "appearance": "百豪之术维持的完美肉体",
            },
            "dialogue_examples": [], "initial_state": {}, "relation_enabled": False,
            "relation_stat_names": [], "sort_order": 0,
            "created_at": now, "updated_at": now,
        })
        self.assertEqual(out.profile_sections, {
            "背景故事": "前代火影，退位后过着闲散的生活，经常在酒馆买醉",
        })
        # 分栏里那份外貌并回顶层字段，不在档案里再占一格
        self.assertEqual(out.appearance, "百豪之术维持的完美肉体")


if __name__ == "__main__":
    unittest.main()
