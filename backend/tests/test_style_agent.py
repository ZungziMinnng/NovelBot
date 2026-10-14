"""文风库模型侧：映射合并、示例形状、单段失败不拖垮整次取用。

模型返回全被 patch，守的是「不管模型怎么写，落库形状和取用形状都对」。
"""
import types
import unittest
from unittest.mock import AsyncMock, patch

from app.agents import style_agent
from app.services.llm_json import JsonCallError
from app.services.style_extract import apply_replacements


class ApplyReplacementsTests(unittest.TestCase):
    def test_longer_key_wins(self):
        mapping = {"萧炎": "林轩", "萧炎帝": "天帝"}
        self.assertEqual(apply_replacements("萧炎帝与萧炎", mapping), "天帝与林轩")

    def test_skips_empty_key_and_identity(self):
        self.assertEqual(apply_replacements("甲乙", {"": "X", "甲": "甲", "乙": "丙"}), "甲丙")

    def test_single_pass_swap(self):
        # 换出来的名字不能再被后面的键命中
        mapping = {"林远": "苏晴", "苏晴": "林远"}
        self.assertEqual(apply_replacements("林远对苏晴说", mapping), "苏晴对林远说")


class StyleAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.call = AsyncMock(return_value=({}, 0, 0))
        patch_call = patch("app.services.llm_json.call_json", new=self.call)
        patch_call.start()
        self.addCleanup(patch_call.stop)
        patch_client = patch(
            "app.services.llm_client.get_agent_client", return_value=("m", "openai")
        )
        self.get_client = patch_client.start()
        self.addCleanup(patch_client.stop)
        # 重排模型要 GPU，测试里原样返回 = 纯词表粗筛
        patch_rerank = patch(
            "app.services.reranker.rerank_hits", side_effect=lambda q, h, k: (h, False)
        )
        self.rerank = patch_rerank.start()
        self.addCleanup(patch_rerank.stop)

    def _profile(self, **kwargs):
        base = {"style_desc": "", "characters": [], "scenes": []}
        base.update(kwargs)
        return types.SimpleNamespace(**base)

    def _reply(self, keywords=None, locate=None, analysis=None, inputs=None):
        """按 prompt 内容分派回复：各类别的摘句是并发调的，不能按调用顺序排。"""
        self.prompts: list[str] = []

        def fake(messages, *args, **kwargs):
            prompt = messages[1]["content"]
            self.prompts.append(prompt)
            if "特征词" in prompt:
                value = keywords
            elif "逐字复制" in prompt:
                value = locate
            elif "文风分析师" in prompt:
                value = analysis
            else:
                value = inputs
            return ((value(prompt) if callable(value) else value) or {}, 0, 0)

        return fake

    async def test_analyze_keeps_only_verbatim_excerpts_and_types_by_category(self):
        fight = "萧炎挥剑斩向对面，剑光如雪，对面举刀硬挡，被震退三步。"
        self.call.side_effect = self._reply(
            locate={"items": [
                # 换行被模型动过，比对要容忍
                {"index": 0, "excerpt": "萧炎挥剑斩向对面，剑光如雪，\n对面举刀硬挡，被震退三步。",
                 "summary": "萧炎出剑压住对面"},
                {"index": 0, "excerpt": "萧炎挥剑斩向对面的敌人，剑光如雪，对面硬挡。", "summary": "改过字"},
                {"index": 0, "excerpt": "萧炎挥剑斩向对面", "summary": "太短"},
            ]},
            analysis={
                "characters": [{"name": "萧炎", "aliases": [], "role": "主角", "neutral": "林轩"}],
                "scenes": [{"index": 0, "speakers": ["萧炎"]}],
            },
        )

        out = await style_agent.analyze([], [(0, fight)], ["打斗"], {})

        self.assertEqual(len(out["scenes"]), 1)
        scene = out["scenes"][0]
        self.assertEqual(scene["scene_type"], "打斗")  # 类型就是提取时的类别
        self.assertTrue(scene["text"].startswith("林轩挥剑"))
        self.assertEqual(scene["summary"], "林轩出剑压住对面")
        self.assertEqual(scene["speakers"], ["林轩"])
        self.assertEqual(scene["input"], "")  # 字段必须在

    async def test_analyze_merges_mapping_and_renames_excerpts(self):
        first = "萧炎挥剑斩向对面，云岚宗的山门前没有人挡得住。"
        second = "炎帝举刀硬挡，云岚宗的山门依旧没有人，天快黑了。"
        self.call.side_effect = self._reply(
            locate={"items": [
                {"index": 0, "excerpt": first, "summary": "萧炎挥剑压制对面"},
                {"index": 1, "excerpt": second, "summary": "炎帝硬挡一刀"},
            ]},
            analysis={
                "style_desc": "萧炎自称炎帝。",
                "characters": [
                    {"name": "萧炎", "aliases": ["炎帝"], "role": "主角", "neutral": "林轩"},
                    {"name": "药老", "aliases": [], "role": "配角", "neutral": ""},
                ],
                "replacements": {"云岚宗": "某宗"},
                "scenes": [
                    {"index": 1, "speakers": ["炎帝", ""]},
                    {"index": 9, "speakers": ["萧炎"]},
                ],
            },
        )

        stats = {"person": "第三人称", "top_phrases": ["萧炎道", "云岚宗", "冷笑一声"]}
        out = await style_agent.analyze([], [(0, first), (1, second)], ["打斗"], stats)

        self.assertEqual(stats["top_phrases"], ["冷笑一声"])  # 专名不进高频词组
        self.assertEqual(out["style_desc"], "林轩自称林轩。")
        self.assertEqual(out["characters"], [
            {"name": "林轩", "role": "主角"},
            {"name": "药老", "role": "配角"},  # neutral 为空 → 保留原名
        ])
        self.assertEqual(len(out["scenes"]), 2)  # 模型漏报的摘录也在，越界编号忽略
        self.assertEqual(out["scenes"][0]["speakers"], [])
        self.assertEqual(out["scenes"][0]["text"], "林轩挥剑斩向对面，某宗的山门前没有人挡得住。")
        self.assertEqual(out["scenes"][1]["summary"], "林轩硬挡一刀")  # 别名也换
        self.assertEqual(out["scenes"][1]["speakers"], ["林轩"])

    async def test_custom_category_triggers_keyword_call(self):
        eat = "他坐在桌边，拿起筷子夹菜，碗里还有半碗饭，没人说话。"
        fight = "萧炎挥剑斩向对面，剑光如雪，对面举刀硬挡，被震退三步。"
        self.call.side_effect = self._reply(
            keywords={"keywords": {"吃饭场景": ["筷子", "夹菜"]}},
            locate={"items": [{"index": 0, "excerpt": eat, "summary": "他在吃饭"}]},
        )

        out = await style_agent.analyze([], [(0, fight), (1, eat)], ["吃饭场景"], {})

        self.assertEqual(len([p for p in self.prompts if "特征词" in p]), 1)
        locate_prompts = [p for p in self.prompts if "逐字复制" in p]
        self.assertIn(eat, locate_prompts[0])
        self.assertNotIn(fight, locate_prompts[0])  # 零分的块不进候选
        self.assertEqual(out["scenes"][0]["scene_type"], "吃饭场景")

        # 预设类别有写死的词表，不问模型
        self.call.side_effect = self._reply(
            locate={"items": [{"index": 0, "excerpt": fight, "summary": "打起来了"}]},
        )
        await style_agent.analyze([], [(0, fight), (1, eat)], ["打斗"], {})
        self.assertFalse(any("特征词" in p for p in self.prompts))

    async def test_nothing_found_raises(self):
        fight = "萧炎挥剑斩向对面，剑光如雪，对面举刀硬挡，被震退三步。"
        self.call.side_effect = self._reply(locate={"items": []})

        with self.assertRaisesRegex(ValueError, "没找到"):
            await style_agent.analyze([], [(0, fight)], ["打斗"], {})
        self.assertFalse(any("文风分析师" in p for p in self.prompts))

    async def test_analyze_fills_input_from_batches(self):
        excerpts = [{"category": "打斗", "text": f"第{i}段，萧炎在场。", "summary": ""} for i in range(12)]

        def inputs(prompt):
            # 12 段拆两批（0~9、10~11）
            if "【0】" in prompt:
                return {"items": [
                    {"index": 0, "input": "萧炎挥剑砍过去"},
                    {"index": 11, "input": "越界的段号"},
                ]}
            return {"items": [
                {"index": 10, "input": "萧炎等着"},
                {"index": 0, "input": "也不许改第 0 段"},
            ]}

        self.call.side_effect = self._reply(
            analysis={"replacements": {"萧炎": "林轩"}, "scenes": []}, inputs=inputs
        )
        with patch("app.agents.style_agent._locate", new=AsyncMock(return_value=excerpts)):
            out = await style_agent.analyze([], [(0, "块。")], ["打斗"], {})

        self.assertEqual(len(self.prompts), 3)  # 分析 + 两批输入
        self.assertIn("第0段，林轩在场。", self.prompts[1])
        self.assertEqual(out["scenes"][0]["input"], "林轩挥剑砍过去")  # 输入里的专名也要换
        self.assertEqual(out["scenes"][10]["input"], "林轩等着")
        self.assertEqual(out["scenes"][11]["input"], "")  # 段号只在本批内有效

    async def test_analyze_failing_batch_leaves_input_empty(self):
        excerpts = [{"category": "打斗", "text": f"第{i}段。", "summary": ""} for i in range(11)]

        def inputs(prompt):
            if "【0】" in prompt:
                return {"items": [{"index": 0, "input": "继续"}]}
            raise JsonCallError("boom")

        self.call.side_effect = self._reply(inputs=inputs)
        with patch("app.agents.style_agent._locate", new=AsyncMock(return_value=excerpts)):
            out = await style_agent.analyze([], [(0, "块。")], ["打斗"], {})

        self.assertEqual(out["scenes"][0]["input"], "继续")
        self.assertEqual(out["scenes"][10]["input"], "")

    async def test_adapt_novel_user_matches_writer_shape(self):
        text = "他走进酒馆。"
        profile = self._profile(
            style_desc="冷硬短句",
            scenes=[{"scene_type": "日常", "text": text, "speakers": []}],
        )
        self.call.return_value = ({"instruction": "写他进门被拦下。"}, 0, 0)

        out = await style_agent.adapt(profile, "novel", [0])

        example = out["examples"][0]
        self.assertIn("=== 写作方向", example["user"])
        self.assertIn(f"约{len(text)}字", example["user"])
        self.assertEqual(example["assistant"], text)

    async def test_adapt_novel_ignores_stored_player_input(self):
        # 存的是游戏的玩家输入，不是剧情节拍；小说一律现反推
        text = "他走进酒馆。"
        profile = self._profile(scenes=[
            {"scene_type": "日常", "text": text, "speakers": [], "input": "林轩走进酒馆"},
        ])
        self.call.return_value = ({"instruction": "林轩进门，被掌柜拦下，从不耐烦到让步。"}, 0, 0)

        out = await style_agent.adapt(profile, "novel", [0])

        example = out["examples"][0]
        self.assertEqual(self.call.await_count, 1)
        self.assertTrue(example["user"].endswith("从不耐烦到让步。"))
        self.assertEqual(example["assistant"], text)

    async def test_analyze_skips_generic_and_shared_aliases(self):
        text = "萧炎看着妻子，又看了看师兄薰儿，云岚宗的人都在。萧炎没说话，妻子也没说话。"
        self.call.side_effect = self._reply(
            locate={"items": [{"index": 0, "excerpt": text, "summary": ""}]},
            analysis={"characters": [
                {"name": "萧炎", "aliases": ["炎", "老大"], "role": "主角", "neutral": "林轩"},
                {"name": "薰儿", "aliases": ["妻子", "老大"], "role": "配角", "neutral": "苏婉"},
                {"name": "师兄", "aliases": [], "role": "配角", "neutral": "王五"},
            ]},
        )

        out = await style_agent.analyze([], [(0, text)], ["环境描写"], {})

        scene = out["scenes"][0]["text"]
        self.assertIn("看着妻子", scene)  # 称谓别名不换
        self.assertIn("师兄苏婉", scene)  # 称谓当名字的角色整个丢掉
        self.assertNotIn("王五", scene)
        self.assertEqual([c["name"] for c in out["characters"]], ["林轩", "苏婉"])

    async def test_analyze_joins_style_card(self):
        excerpt = {"category": "打斗", "text": "萧炎挥剑斩向对面。", "summary": ""}
        self.call.side_effect = self._reply(analysis={
            "style_card": {"句子节奏": "短句多", "叙述视角": "贴着萧炎", "用词质感": " "},
            "style_desc": "旧字段",
            "characters": [{"name": "萧炎", "aliases": [], "role": "主角", "neutral": "林轩"}],
        })
        with patch("app.agents.style_agent._locate", new=AsyncMock(return_value=[excerpt])):
            out = await style_agent.analyze([], [(0, "块。")], ["打斗"], {})
        # 按固定栏目顺序、空栏不要、专名照换
        self.assertEqual(out["style_desc"], "【叙述视角】贴着林轩\n【句子节奏】短句多")

    async def test_whole_scene_skips_model_locate(self):
        chapter = "\n".join(f"第{i}段，他走过长街，雨下个不停，灯一盏盏亮起来。" for i in range(60))
        self.call.side_effect = self._reply(analysis={})

        out = await style_agent.analyze([], [], ["整场景"], {}, "", [chapter])

        self.assertFalse(any("逐字复制" in p for p in self.prompts))
        self.assertEqual(out["scenes"][0]["scene_type"], "整场景")
        self.assertGreaterEqual(len(out["scenes"][0]["text"]), 800)

    async def test_rerank_reorders_shortlist(self):
        a = "他挥剑。剑鞘挂在墙上，屋里没人。"
        b = "他一剑刺穿对方的肩膀，对方挥刀反砍。"
        self.rerank.side_effect = lambda q, h, k: (list(reversed(h)), True)
        self.call.side_effect = self._reply(locate={"items": []})
        with self.assertRaises(ValueError):
            await style_agent.analyze([], [(0, a), (1, b)], ["打斗"], {})
        query = self.rerank.call_args.args[0]
        self.assertIn("交手", query)  # 用类别描述，不是类别名
        locate = next(p for p in self.prompts if "逐字复制" in p)
        # 词表分 b 高排前面，重排倒过来后 a 在前
        self.assertLess(locate.index(a), locate.index(b))

    async def test_trial_returns_text_and_gaps(self):
        profile = self._profile(
            style_desc="短句。",
            stats={"avg_sentence_len": 8, "person": "第三人称"},
            scenes=[
                {"scene_type": "日常", "text": "他走了。", "speakers": []},
                {"scene_type": "整场景", "text": "他推开门，屋里没人，桌上的茶还是热的。", "speakers": []},
            ],
        )
        long_text = "他慢慢地走过那条又长又窄而且总是下着雨的老街，一直走到了尽头才停下来。" * 3
        with patch(
            "app.services.llm_client.dispatch_chat_complete", new=AsyncMock(return_value=long_text)
        ) as dispatch:
            out = await style_agent.trial(profile, [], "9")

        prompt = dispatch.await_args.args[0][0]["content"]
        self.assertLess(prompt.index("他推开门"), prompt.index("他走了。"))  # 没选段落时长的在前
        self.assertIn("用第三人称", prompt)
        self.get_client.assert_called_with("memory", "9")
        self.assertEqual(out["text"], long_text)
        self.assertEqual([g["key"] for g in out["gaps"]], ["avg_sentence_len"])

    async def test_trial_empty_profile_raises(self):
        with self.assertRaisesRegex(ValueError, "没法试写"):
            await style_agent.trial(self._profile(), [])

    async def test_adapt_tavern_filters_and_renames(self):
        profile = self._profile(scenes=[
            {"scene_type": "对话", "text": "A 段。", "speakers": ["林轩"]},
            {"scene_type": "对话", "text": "B 段。", "speakers": ["苏婉"]},
        ])
        self.call.return_value = (
            {"pairs": [{"user": "你来了。", "assistant": "林轩点头。"}, {"user": "", "assistant": "x"}]},
            0, 0,
        )

        out = await style_agent.adapt(
            profile, "tavern", [0, 1], character="林轩", name_map={"林轩": "陆沉"}
        )

        self.assertEqual(self.call.await_count, 1)  # 苏婉那段没进模型
        self.assertEqual(out["examples"], [{"user": "你来了。", "assistant": "陆沉点头。"}])

    async def test_adapt_tavern_without_matching_speaker_raises(self):
        profile = self._profile(
            scenes=[{"scene_type": "对话", "text": "B 段。", "speakers": ["苏婉"]}]
        )
        with self.assertRaisesRegex(ValueError, "没有"):
            await style_agent.adapt(profile, "tavern", [0], character="林轩")

    async def test_adapt_narration_renames_everyone_on_both_sides(self):
        profile = self._profile(
            characters=[{"name": "苏婉", "role": "配角"}, {"name": "林轩", "role": "主角"}],
            scenes=[
                {"scene_type": "打斗", "text": "林轩举剑迎上去，苏婉退开。", "speakers": [], "input": "林轩挥剑砍向对面"},
                {"scene_type": "描写", "text": "风停了。", "speakers": [], "input": ""},
            ],
        )

        # 配角也要换：原来只换主角，苏婉会原样留在示例里
        out = await style_agent.adapt(
            profile, "rpg_narration", [0, 1], name_map={"林轩": "陆沉", "苏婉": "温言", "路人": " "}
        )

        self.assertEqual(out["examples"], [  # 没输入的那段跳过
            {"user": "陆沉挥剑砍向对面", "assistant": "陆沉举剑迎上去，温言退开。"},
        ])
        self.assertEqual(self.call.await_count, 0)
        self.get_client.assert_not_called()

    async def test_adapt_narration_without_input_raises(self):
        profile = self._profile(
            scenes=[{"scene_type": "描写", "text": "风停了。", "speakers": [], "input": "  "}],
        )
        with self.assertRaisesRegex(ValueError, "重新导入"):
            await style_agent.adapt(profile, "rpg_narration", [0])
        self.get_client.assert_not_called()

    async def test_adapt_skips_failed_chunk(self):
        profile = self._profile(scenes=[
            {"scene_type": "日常", "text": "第一段。", "speakers": []},
            {"scene_type": "日常", "text": "第二段。", "speakers": []},
        ])
        self.call.side_effect = [JsonCallError("boom"), ({"instruction": "写下去。"}, 0, 0)]

        out = await style_agent.adapt(profile, "novel", [0, 1])

        self.assertEqual(len(out["examples"]), 1)

    async def test_adapt_all_failed_raises(self):
        profile = self._profile(
            scenes=[{"scene_type": "日常", "text": "第一段。", "speakers": []}]
        )
        self.call.side_effect = JsonCallError("boom")

        with self.assertRaisesRegex(ValueError, "转换失败"):
            await style_agent.adapt(profile, "novel", [0])

    async def test_model_ref_reaches_client(self):
        excerpt = {"category": "打斗", "text": "萧炎挥剑斩向对面，剑光如雪。", "summary": ""}
        with patch("app.agents.style_agent._locate", new=AsyncMock(return_value=[excerpt])):
            await style_agent.analyze(["段。"], [(0, "块。")], ["打斗"], {}, "7")
        self.get_client.assert_called_with("memory", "7")

        profile = self._profile(scenes=[{"scene_type": "日常", "text": "段。", "speakers": []}])
        self.call.return_value = ({"instruction": "写。"}, 0, 0)
        await style_agent.adapt(profile, "novel", [0], model_ref="8")
        self.get_client.assert_called_with("memory", "8")

    async def test_adapt_bad_indexes_and_mode(self):
        profile = self._profile(scenes=[{"scene_type": "日常", "text": "段。", "speakers": []}])
        with self.assertRaisesRegex(ValueError, "没有可用"):
            await style_agent.adapt(profile, "novel", [5])
        with self.assertRaisesRegex(ValueError, "未知模式"):
            await style_agent.adapt(profile, "xx", [0])


if __name__ == "__main__":
    unittest.main()
