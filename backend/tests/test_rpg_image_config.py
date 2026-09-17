"""出图设置的两层合并。模组那份是默认，某个人那份是稀疏覆写。

这几条卡的都是「写成 `or` 就悄悄坏掉、界面上还一切正常」的地方。
"""
import unittest

from app.services.rpg_image import lora_key, merge_image_config, resolve_workflow


class MergeTests(unittest.TestCase):
    def test_nothing_overridden_means_the_module_wins(self):
        base = {"workflow": "anime", "style": "anime", "pose": "坐姿", "extra": "8k"}
        self.assertEqual(merge_image_config(base, {}), base)

    def test_an_empty_string_is_an_override_not_a_blank(self):
        """「不指定姿势」「不加补充词」存的就是空串。写成 `over.get(k) or base.get(k)`
        会把它吞回模组那一档，那几个按钮就永远点不出效果。"""
        merged = merge_image_config(
            {"pose": "站姿全身像", "style": "anime", "extra": "8k"},
            {"pose": "", "style": "", "extra": ""},
        )
        self.assertEqual(merged["pose"], "")
        self.assertEqual(merged["style"], "")
        self.assertEqual(merged["extra"], "")

    def test_only_the_keys_present_are_taken_over(self):
        merged = merge_image_config(
            {"workflow": "anime", "pose": "坐姿"}, {"pose": "躺姿，全身"},
        )
        self.assertEqual(merged["workflow"], "anime")   # 没覆写，跟模组
        self.assertEqual(merged["pose"], "躺姿，全身")   # 覆写了

    def test_neither_side_set_it_means_the_key_stays_out(self):
        """漏进一个 `pose: None` 会让下游的 `?? 默认值` 判断走错分支。"""
        self.assertNotIn("pose", merge_image_config({"style": "anime"}, {}))

    def test_null_columns_read_as_empty(self):
        self.assertEqual(merge_image_config(None, None), {})

    def test_prompt_form_and_frame_follow_the_same_rule(self):
        """后端目前不读这两项（转 tag 是前端调接口做的、尺寸由前端算完传进请求体），
        但合并规则必须和前端 imageConfig.ts 一致——不然「跟随模组」在两边算出
        不同结果，预览那句话和实际发出去的就不是一句。"""
        merged = merge_image_config(
            {"prompt_form": "sd_tags", "frame": "cg_wide"}, {"frame": "portrait"},
        )
        self.assertEqual(merged["prompt_form"], "sd_tags")  # 没覆写，跟模组
        self.assertEqual(merged["frame"], "portrait")       # 覆写了

    def test_a_module_on_tags_with_an_npc_left_alone_stays_on_tags(self):
        """最常见的用法：整个模组切到光辉，每个 NPC 都不单独设。
        漏掉这条的话每个人都会退回中文，图全部走偏而且没有任何报错。"""
        merged = merge_image_config({"prompt_form": "sd_tags"}, {})
        self.assertEqual(merged["prompt_form"], "sd_tags")


class LoraTests(unittest.TestCase):
    def test_loras_merge_one_by_one_not_wholesale(self):
        """模组关了 A、这个人只调了 B 的权重，是两件互不相干的决定，都该生效。
        整套替换的话，碰一下 B 就把「关掉 A」抹掉了，A 又悄悄回到图里。"""
        base = {"loras": {"anime": {
            "A.safetensors": {"on": False, "strength": 0},
            "B.safetensors": {"on": True, "strength": 0.8},
        }}}
        over = {"loras": {"anime": {"B.safetensors": {"on": True, "strength": 1.4}}}}
        got = merge_image_config(base, over)["loras"]["anime"]
        self.assertFalse(got["A.safetensors"]["on"])
        self.assertEqual(got["B.safetensors"]["strength"], 1.4)

    def test_a_group_only_one_side_has_still_comes_through(self):
        merged = merge_image_config(
            {"loras": {"anime": {"A": {"on": True, "strength": 1}}}},
            {"loras": {"real": {"B": {"on": True, "strength": 1}}}},
        )
        self.assertEqual(set(merged["loras"]), {"anime", "real"})

    def test_an_empty_workflow_is_keyed_as_the_backend_default(self):
        """选了「默认」又调 LoRA 时，存和取必须落在同一个组名上，
        否则调好的权重出图时读不到、凭空消失。"""
        self.assertEqual(lora_key({}), "npc_portrait")
        self.assertEqual(lora_key({"workflow": "  "}), "npc_portrait")
        self.assertEqual(lora_key({"workflow": " anime "}), "anime")

    def test_switching_workflow_picks_up_that_workflows_group(self):
        """换工作流是换一整套 LoRA，两套设置不能混。"""
        base = {"workflow": "", "loras": {
            "npc_portrait": {"A": {"on": True, "strength": 1}},
            "anime": {"B": {"on": True, "strength": 0.5}},
        }}
        wf, loras, _ckpt = resolve_workflow(base, {"workflow": "anime"})
        self.assertEqual(wf, "anime")
        self.assertEqual(set(loras), {"B"})

    def test_no_loras_anywhere_gives_an_empty_dict(self):
        self.assertEqual(
            resolve_workflow({"workflow": "anime"}, {}), ("anime", {}, ""),
        )


class CkptTests(unittest.TestCase):
    def test_checkpoints_merge_one_workflow_at_a_time(self):
        """模组把 anime 那份指到 A、这个人只改了 real 那份，两件事互不相干，
        都该留下。整套替换的话，碰一下 real 就把 anime 那一下抹掉了。"""
        base = {"checkpoints": {"anime": "A.safetensors", "real": "C.safetensors"}}
        over = {"checkpoints": {"real": "D.safetensors"}}
        got = merge_image_config(base, over)["checkpoints"]
        self.assertEqual(got, {"anime": "A.safetensors", "real": "D.safetensors"})

    def test_neither_side_set_it_means_the_key_stays_out(self):
        self.assertNotIn("checkpoints", merge_image_config({"style": "anime"}, {}))

    def test_only_sd_tags_lets_the_base_model_through(self):
        """底模只在英文 tag 形态下生效。中文自然语言那套（Z-Image）不吃
        checkpoint，配了也不该发出去。"""
        cfg = {"workflow": "anime", "prompt_form": "sd_tags",
               "checkpoints": {"anime": "A.safetensors"}}
        self.assertEqual(resolve_workflow(cfg, {})[2], "A.safetensors")
        for form in ("natural_zh", "", None):
            other = {**cfg, "prompt_form": form}
            self.assertEqual(resolve_workflow(other, {})[2], "", form)

    def test_switching_workflow_picks_up_that_workflows_base_model(self):
        """底模按工作流名分组，换工作流就是换一整套——不然会把 SDXL 的底模
        带到另一份工作流上，出来的图直接不对。"""
        cfg = {"workflow": "anime", "prompt_form": "sd_tags", "checkpoints": {
            "npc_portrait": "P.safetensors", "anime": "A.safetensors",
        }}
        self.assertEqual(resolve_workflow(cfg, {})[2], "A.safetensors")
        self.assertEqual(
            resolve_workflow(cfg, {"workflow": "npc_portrait"})[2], "P.safetensors",
        )


if __name__ == "__main__":
    unittest.main()
