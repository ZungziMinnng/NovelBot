"""prose_lint 密度类检查：双门槛、对话不参与、句号结巴的清零规则。

密度项一律 advisory——阈值是统计口径，不能拿来打回重写。
"""
import unittest

from app.services import prose_lint


def kinds(text):
    return {f["label"].split("（")[0] for f in prose_lint.lint(text)}


def severities(text, keyword):
    return {f["severity"] for f in prose_lint.lint(text) if keyword in f["label"]}


class DensityGateTests(unittest.TestCase):
    def test_short_text_never_reports_density(self):
        """样本不足 200 可见字时密度不可靠，一律不报。"""
        text = "他抖了一下。她顿了一下。他扫了一眼。她愣了一下。他停了一下。她转了一圈。"
        self.assertNotIn("小动作口癖", kinds(text))

    def test_micro_action_needs_both_gates(self):
        """次数够但密度不够（长章里散落几处）不报。"""
        # 填充句每句不同，避免触发已有的整句复读检测
        filler = "".join(
            f"他沿着长街往北走了第{i}段路，两侧店铺陆续上板，风把幌子吹得直响。"
            for i in range(40)
        )
        text = filler + "他抖了一下。她顿了一下。他扫了一眼。她愣了一下。他停了一下。"
        self.assertNotIn("小动作口癖", kinds(text))

    def test_micro_action_reported_when_dense(self):
        text = ("他抖了一下，又顿了一阵，随后扫了一眼四周，才咳了一声。" * 12)
        self.assertIn("小动作口癖", kinds(text))
        self.assertEqual(severities(text, "小动作口癖"), {"advisory"})

    def test_metaphor_density_reported(self):
        text = ("那声音像刀，仿佛在割风，好似有人在暗处喘息，犹如潮水漫过脚背，宛如旧梦。" * 8)
        self.assertIn("比喻过密", kinds(text))

    def test_metaphor_excludes_non_metaphor_xiang(self):
        """头像/图像/不像/像素 不是比喻，不该被算进密度。"""
        text = ("他翻着旧头像和图像文件，屏幕上像素发灰，这景象不像他记忆里的样子。" * 12)
        self.assertNotIn("比喻过密", kinds(text))

    def test_cliche_density_reported(self):
        text = ("他不由自主地深吸一口气，心中一凛，眼中闪过一丝寒意，嘴角勾起，缓缓地站定。" * 8)
        self.assertIn("陈词滥调过密", kinds(text))

    def test_clean_prose_reports_nothing(self):
        """正常人写的段落必须零命中，否则阈值没资格上线。"""
        text = "".join(
            f"灶上第{i}壶水开了，壶盖被顶起半寸，白汽扑在窗纸上。"
            f"他把第{i}根柴往里推，火苗贴着锅底舔上去，锅沿渗出一圈水痕。"
            f"院外第{i}个人叫他的名字，声调拖得很长，尾音撞在墙上折回来。"
            f"他没应，先把壶提下来倒了第{i}碗，放在桌沿等它凉透。"
            for i in range(6)
        )
        self.assertEqual(kinds(text), set())


class DialogueExclusionTests(unittest.TestCase):
    def test_dialogue_not_counted_in_density(self):
        """台词里的口癖是正常口语，不算叙述层密度。"""
        text = "".join(
            f"“他抖了一下，我也顿了一下，你不由自主地深吸一口气，第{i}回了。”\n"
            for i in range(30)
        )
        self.assertEqual(kinds(text), set())


class StutterTests(unittest.TestCase):
    def test_consecutive_short_narration_reported(self):
        text = "他起身。他推门。风很冷。天没亮。街是空的。他走了。"
        self.assertIn("连续 6 句都是 5 字以内的短叙述句", kinds(text))

    def test_five_in_a_row_is_fine(self):
        text = "他起身。他推门。风很冷。天没亮。街是空的。"
        self.assertEqual(kinds(text), set())

    def test_pure_dialogue_line_resets_the_run(self):
        """整行台词清零而不是跳过：台词天然短，跳过会把两段短句连成一串误报。"""
        text = (
            "他起身。他推门。风很冷。\n"
            "“走吧。”\n"
            "天没亮。街是空的。他走了。\n"
        )
        self.assertEqual(kinds(text), set())

    def test_long_sentence_breaks_the_run(self):
        text = "他起身。他推门。风很冷。他在门口站了很久才想起没带钥匙。天没亮。街是空的。他走了。"
        self.assertEqual(kinds(text), set())

    def test_stutter_is_advisory_only(self):
        text = "他起身。他推门。风很冷。天没亮。街是空的。他走了。"
        self.assertEqual(severities(text, "短叙述句"), {"advisory"})


class NegationParadeTests(unittest.TestCase):
    def test_mei_you_parade_still_blocking(self):
        text = "没有风声，没有脚步，只有炉火在响。"
        hits = [f for f in prose_lint.lint(text) if "否定排比" in f["label"]]
        self.assertTrue(hits)
        self.assertEqual(hits[0]["severity"], "blocking")

    def test_bare_mei_parade_now_caught(self):
        text = "没水，没粮，连一床干被子都找不出来。"
        self.assertTrue([f for f in prose_lint.lint(text) if "否定排比" in f["label"]])

    def test_bu_x_parade_not_caught(self):
        """「不X」在正常汉语里太常见，收进来会大面积误报。"""
        text = "他不快，不慢，只是照着自己的步子走。"
        self.assertFalse([f for f in prose_lint.lint(text) if "否定排比" in f["label"]])


if __name__ == "__main__":
    unittest.main()
