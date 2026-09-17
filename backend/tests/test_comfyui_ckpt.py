"""底模覆写：按 input 键名扫，一处不落。

这东西坏掉的样子很隐蔽——只改上第一个加载器，前面几步用新模型、高清修复还用
旧的，图看着「有点怪」但没有任何报错。所以这里逐处断言，而不是只看总数。
"""
import unittest
from unittest.mock import patch

from app.services.comfyui import apply_ckpt, inspect_ckpts


def _wf():
    """照光辉那份工作流的形状搭：三个加载器各写一遍底模，高清修复脚本里
    另有一个 hires_ckpt_name（键名和 class_type 都跟加载器不一样）。"""
    return {
        "646": {"class_type": "easy fullLoader",
                "inputs": {"ckpt_name": "old.safetensors", "seed": 1}},
        "649": {"class_type": "easy fullLoader",
                "inputs": {"ckpt_name": "old.safetensors"}},
        "724": {"class_type": "easy fullLoader",
                "inputs": {"ckpt_name": "old.safetensors", "positive": "%PROMPT%"}},
        "798": {"class_type": "HighRes-Fix Script",
                "inputs": {"hires_ckpt_name": "old.safetensors", "hires_steps": 20}},
        "775": {"class_type": "KSampler (Efficient)", "inputs": {"seed": 1, "steps": 40}},
    }


class ApplyCkptTests(unittest.TestCase):
    def test_every_occurrence_is_rewritten_not_just_the_first(self):
        wf = _wf()
        apply_ckpt(wf, "new.safetensors")
        self.assertEqual(wf["646"]["inputs"]["ckpt_name"], "new.safetensors")
        self.assertEqual(wf["649"]["inputs"]["ckpt_name"], "new.safetensors")
        self.assertEqual(wf["724"]["inputs"]["ckpt_name"], "new.safetensors")
        # 高清修复必须跟着换：它是同一个 latent 接着去噪（denoise 0.4 上下），
        # 漏掉这处就是「主模型换了、高清还在用旧的」，风格会漂
        self.assertEqual(wf["798"]["inputs"]["hires_ckpt_name"], "new.safetensors")

    def test_nothing_else_is_touched(self):
        wf = _wf()
        apply_ckpt(wf, "new.safetensors")
        self.assertEqual(wf["724"]["inputs"]["positive"], "%PROMPT%")
        self.assertEqual(wf["798"]["inputs"]["hires_steps"], 20)
        self.assertEqual(wf["775"]["inputs"], {"seed": 1, "steps": 40})

    def test_an_empty_name_leaves_the_workflow_alone(self):
        """空 = 不覆盖，用工作流里写死那个。"""
        wf = _wf()
        apply_ckpt(wf, "")
        self.assertEqual(wf["646"]["inputs"]["ckpt_name"], "old.safetensors")
        self.assertEqual(wf["798"]["inputs"]["hires_ckpt_name"], "old.safetensors")

    def test_a_workflow_without_checkpoints_is_not_an_error(self):
        """走 UNETLoader 单文件的工作流（默认的 npc_portrait 就是）里没有
        ckpt_name。用户填了底模只是没效果，不该在出图时炸。"""
        wf = {"1": {"class_type": "UNETLoader",
                    "inputs": {"unet_name": "a.safetensors"}}}
        apply_ckpt(wf, "new.safetensors")
        self.assertEqual(wf["1"]["inputs"], {"unet_name": "a.safetensors"})


class InspectCkptTests(unittest.TestCase):
    def test_reports_every_slot_so_the_frontend_can_warn(self):
        """四个槽位都要报出来：前端靠它显示「覆盖后这 4 处会统一成同一个」，
        工作流内部本来就不一致时那句提示才有依据。"""
        with patch("app.services.comfyui.load_workflow", return_value=_wf()):
            slots = inspect_ckpts("whatever")
        self.assertEqual(len(slots), 4)
        self.assertEqual({s["node"] for s in slots}, {"646", "649", "724", "798"})
        self.assertEqual({s["key"] for s in slots}, {"ckpt_name", "hires_ckpt_name"})
        self.assertEqual({s["name"] for s in slots}, {"old.safetensors"})

    def test_no_slots_means_the_frontend_draws_no_control(self):
        """空列表 = 这份工作流不认底模，前端据此不画控件，
        免得出现一个填了没反应的下拉。"""
        with patch("app.services.comfyui.load_workflow", return_value={
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": "a.safetensors"}},
        }):
            self.assertEqual(inspect_ckpts("whatever"), [])


if __name__ == "__main__":
    unittest.main()
