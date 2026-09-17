"""模组构思向导：对话组装、分步抽取、白名单清洗。

清洗是这个功能的命门。RPG 的数据靠名字互相引用——角色的关系数值起点、道具/动作
的 effects、角色的所在地点，引用的名字对不上就静默失效、不报错。所以抽出来的
每个引用都必须按前面已定的名字过滤，丢掉的还要说出来（dropped），不能咽下去。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.agents import rpg_wizard
from app.api.routes import rpg as rpg_routes
from app.schemas.rpg import RpgWizardExtractIn
from app.services import rpg_prompts


class StageWiringTests(unittest.TestCase):
    def test_stage_ids_all_have_a_template_branch(self):
        """每一步的 id 在对话模板和抽取模板里都要有对应分支，不然那一步渲染出来
        是空的、模型没指令。"""
        chat = rpg_prompts.default_content("rpg_wizard.jinja2")
        extract = rpg_prompts.default_content("rpg_wizard_extract.jinja2")
        for stage in rpg_wizard.STAGES:
            with self.subTest(stage=stage):
                self.assertIn(f"'{stage}'", chat)
                self.assertIn(f"'{stage}'", extract)

    def test_both_templates_are_registered(self):
        self.assertIn("rpg_wizard.jinja2", rpg_prompts.PROMPTS)
        self.assertIn("rpg_wizard_extract.jinja2", rpg_prompts.PROMPTS)
        self.assertIn("rpg_wizard_full.jinja2", rpg_prompts.PROMPTS)

    def test_prompt_limits_the_wizard_to_form_fields(self):
        prompt = rpg_prompts.default_content("rpg_wizard.jinja2")
        self.assertIn("猎物系统", prompt)
        self.assertIn("不要设计或追问字段外的系统", prompt)


class PickModelTests(unittest.TestCase):
    """向导下拉里选的那个模型说了算。

    下拉第一项是「模组默认模型」（value 空串），所以空 = 跟模组走。这条规矩的
    反面代价很具体：**作者选了 A 模型，实际连的却是主页设置里的默认模型**——
    请求里带了选择、路由没接，日志里只看得到默认模型的名字，从界面上完全看不出
    是哪一步丢的。三个入口（对话 / 抽取 / 一键生成）走同一个函数，就是为了
    不让它们各自漂走。
    """

    def test_a_chosen_model_wins(self):
        self.assertEqual(rpg_wizard.pick_model("12", "3"), "12")

    def test_nothing_chosen_follows_the_module(self):
        self.assertEqual(rpg_wizard.pick_model("", "3"), "3")

    def test_blank_is_the_same_as_nothing(self):
        self.assertEqual(rpg_wizard.pick_model("   ", "3"), "3")

    def test_an_empty_pair_stays_empty(self):
        # 两边都空 = 交给 resolve_model_ref 回落到全局默认，这里不替它决定
        self.assertEqual(rpg_wizard.pick_model("", ""), "")


class ExtractCleaningTests(unittest.IsolatedAsyncioTestCase):
    async def _extract(self, stage, parsed, known=None):
        async def fake_call_json(*_args, **_kwargs):
            return parsed, 0, 0

        with patch.object(rpg_wizard.llm_json, "call_json", fake_call_json):
            with patch.object(
                rpg_wizard.llm_client, "get_fast_client", return_value=("m", "openai")
            ):
                return await rpg_wizard.extract_stage(stage, "对话", known or {}, "7")

    async def test_world_fields_are_trimmed_and_named(self):
        out = await self._extract("world", {
            "genre": "都市怪谈", "worldview": "霓虹下的旧城", "opening_scene": "你醒在天台",
            "system_instruction": "冷硬", "narration_sample": "雨还在下",
        })
        self.assertEqual(out["genre"], "都市怪谈")
        self.assertEqual(out["worldview"], "霓虹下的旧城")
        self.assertEqual(out["dropped"], [])

    async def test_stat_initial_is_clamped_and_display_defaulted(self):
        out = await self._extract("stats", {
            "stat_defs": [
                # initial 超上限、display 非法 → 夹住 + 落默认（有上限落「条」）
                {"name": "精力", "initial": 999, "min": 0, "max": 100, "display": "彩虹", "on_zero": "死亡"},
                # 无上限 → display 落「数字」；on_zero 非法 → 落「无」
                {"name": "资金", "initial": 200, "min": 0, "max": None, "on_zero": "破产"},
                {"name": "", "initial": 1},  # 空名字整条丢掉
            ],
            "relation_stat_defs": [{"name": "好感", "initial": 0, "min": 0, "max": 100}],
        })
        stats = {s["name"]: s for s in out["stat_defs"]}
        self.assertEqual(len(stats), 2)
        self.assertEqual(stats["精力"]["initial"], 100)
        self.assertEqual(stats["精力"]["display"], "条")
        self.assertEqual(stats["精力"]["on_zero"], "死亡")
        self.assertEqual(stats["资金"]["display"], "数字")
        self.assertEqual(stats["资金"]["on_zero"], "无")
        self.assertEqual(len(out["relation_stat_defs"]), 1)

    async def test_location_connections_to_unknown_places_are_dropped(self):
        out = await self._extract("places", {
            "default_location": "酒馆",
            "locations": [
                {"name": "酒馆", "description": "烟味", "connections": ["后巷", "月球"]},
                {"name": "后巷", "description": "潮湿", "connections": []},
            ],
        })
        conns = {loc["name"]: loc["connections"] for loc in out["locations"]}
        self.assertEqual(conns["酒馆"], ["后巷"])
        self.assertTrue(any("月球" in d for d in out["dropped"]))
        self.assertEqual(out["default_location"], "酒馆")

    async def test_time_slots_are_trimmed_and_deduplicated(self):
        out = await self._extract("slots", {
            "time_slots": [" 清晨 ", "白天", "清晨", "", None],
        })
        self.assertEqual(out["time_slots"], ["清晨", "白天"])

    async def test_default_location_not_in_list_is_cleared(self):
        out = await self._extract("places", {
            "default_location": "皇宫",
            "locations": [{"name": "酒馆", "description": "烟味", "connections": []}],
        })
        self.assertEqual(out["default_location"], "")
        self.assertTrue(any("皇宫" in d for d in out["dropped"]))

    async def test_npc_relation_and_location_are_whitelisted(self):
        out = await self._extract(
            "cast",
            {"npcs": [{
                "name": "老陈",
                "persona": "话少",
                "location": "酒馆",
                "initial_state": {"好感": 20, "戒心": 50},  # 戒心不在白名单
            }, {
                "name": "阿蓝",
                "location": "皇宫",  # 不在白名单 → 留空
                "initial_state": {},
            }, {
                "name": "",  # 空名字整条丢掉
            }]},
            known={"relation_names": ["好感"], "location_names": ["酒馆", "后巷"]},
        )
        npcs = {n["name"]: n for n in out["npcs"]}
        self.assertEqual(len(npcs), 2)
        self.assertEqual(npcs["老陈"]["initial_state"], {"好感": 20})
        self.assertEqual(npcs["老陈"]["location"], "酒馆")
        self.assertEqual(npcs["阿蓝"]["location"], "")
        self.assertTrue(any("戒心" in d for d in out["dropped"]))
        self.assertTrue(any("皇宫" in d for d in out["dropped"]))

    async def test_item_and_action_effects_are_whitelisted(self):
        out = await self._extract(
            "things",
            {
                "items": [{
                    "name": "醒酒药",
                    "effects": {"精力": 20, "醉意": -30},  # 醉意不在玩家数值里
                }],
                "actions": [{
                    "name": "请她喝一杯",
                    "effects": {"资金": -10},
                    "relation_effects": {"好感": 5, "智力": 1},  # 智力不是关系数值
                }],
            },
            known={"stat_names": ["精力", "资金"], "relation_names": ["好感"]},
        )
        self.assertEqual(out["items"][0]["effects"], {"精力": 20})
        self.assertEqual(out["actions"][0]["effects"], {"资金": -10})
        self.assertEqual(out["actions"][0]["relation_effects"], {"好感": 5})
        self.assertTrue(any("醉意" in d for d in out["dropped"]))
        self.assertTrue(any("智力" in d for d in out["dropped"]))

    async def test_malformed_npc_fields_keep_the_character_and_report_dropped_data(self):
        for malformed in ([{"name": "好感", "value": 20}], "好感：20", 20):
            with self.subTest(malformed=malformed):
                out = await self._extract("cast", {
                    "npcs": [{
                        "name": "老陈", "persona": "话少", "location": "酒馆",
                        "initial_state": malformed, "profile_sections": malformed,
                    }],
                }, known={"relation_names": ["好感"], "location_names": ["酒馆"]})
                self.assertEqual(len(out["npcs"]), 1)
                self.assertEqual(out["npcs"][0]["name"], "老陈")
                self.assertEqual(out["npcs"][0]["persona"], "话少")
                self.assertEqual(out["npcs"][0]["location"], "酒馆")
                self.assertEqual(out["npcs"][0]["initial_state"], {})
                self.assertEqual(out["npcs"][0]["profile_sections"], {})
                self.assertEqual(len(out["dropped"]), 2)
                self.assertTrue(all("老陈" in message for message in out["dropped"]))

    async def test_malformed_effects_do_not_abort_the_final_step(self):
        out = await self._extract("things", {
            "items": [{"name": "药", "effects": ["精力+10"]}],
            "actions": [{"name": "交谈", "effects": "精力-5", "relation_effects": 10}],
        })
        self.assertEqual(out["items"][0]["name"], "药")
        self.assertEqual(out["items"][0]["effects"], {})
        self.assertEqual(out["actions"][0]["effects"], {})
        self.assertEqual(out["actions"][0]["relation_effects"], {})
        self.assertEqual(len(out["dropped"]), 3)

    async def test_action_group_survives_extraction_and_missing_group_is_empty(self):
        """分组是模拟器主页分栏的唯一依据，抽取时丢了它整屏按钮就全挤进「其他」。

        另一半同样要钉住：模型没给 group 时得是空串而不是缺键——前端
        `action.group || ''` 之后要拿去比较分组名，None 会变成字符串 "None" 那一栏。
        """
        out = await self._extract("things", {
            "actions": [
                {"name": "招聘秘书", "group": " 人事 "},
                {"name": "处理商业"},
            ],
        })
        self.assertEqual(out["actions"][0]["group"], "人事")
        self.assertEqual(out["actions"][1]["group"], "")

    async def test_malformed_stage_lists_raise_a_readable_extraction_error(self):
        for stage, field in (
            ("stats", "stat_defs"), ("stats", "relation_stat_defs"),
            ("places", "locations"), ("slots", "time_slots"),
            ("cast", "npcs"), ("things", "items"), ("things", "actions"),
        ):
            for malformed in ({"name": "老陈"}, "老陈", 5):
                with self.subTest(stage=stage, field=field, malformed=malformed):
                    with self.assertRaisesRegex(rpg_wizard.llm_json.JsonCallError, field):
                        await self._extract(stage, {field: malformed})

    async def test_empty_whitelist_drops_all_references(self):
        """前面没定数值，道具的 effects 应全部清空——不能悬空引用一个不存在的表。"""
        out = await self._extract(
            "things",
            {"items": [{"name": "药", "effects": {"体力": 10}}], "actions": []},
            known={},
        )
        self.assertEqual(out["items"][0]["effects"], {})
        self.assertTrue(any("体力" in d for d in out["dropped"]))


class ExtractRouteTests(unittest.IsolatedAsyncioTestCase):
    async def _request(self, parsed):
        with (
            patch.object(rpg_routes, "_get_owned_module", AsyncMock(return_value=SimpleNamespace(model_ref="7"))),
            patch.object(rpg_wizard.llm_client, "get_fast_client", return_value=("m", "openai")),
            patch.object(rpg_wizard.llm_json, "call_json", AsyncMock(return_value=(parsed, 0, 0))),
        ):
            return await rpg_routes.wizard_extract(
                1, RpgWizardExtractIn(stage="cast", messages=[{"role": "user", "content": "确认老陈"}]),
                user=None, db=None,
            )

    async def test_characters_reach_the_preview_despite_malformed_optional_fields(self):
        out = await self._request({"npcs": [{"name": "老陈", "initial_state": [20], "profile_sections": "档案"}]})
        self.assertEqual(out.npcs[0]["name"], "老陈")
        self.assertEqual(len(out.dropped), 2)

    async def test_bad_character_list_returns_a_readable_502(self):
        with self.assertRaises(HTTPException) as caught:
            await self._request({"npcs": "老陈"})
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("npcs", caught.exception.detail)

    async def test_unexpected_failure_is_logged_and_has_a_response_detail(self):
        with (
            patch.object(rpg_wizard, "extract_stage", AsyncMock(side_effect=RuntimeError("broken"))),
            self.assertLogs(rpg_routes.logger, level="ERROR") as logs,
            self.assertRaises(HTTPException) as caught,
        ):
            await self._request({})
        self.assertEqual(caught.exception.status_code, 500)
        self.assertIn("后台日志", caught.exception.detail)
        self.assertTrue(any("broken" in message for message in logs.output))


class FullGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_sends_user_content_for_gemini_compatible_providers(self):
        async def dispatch(messages, **kwargs):
            contents = [message for message in messages if message["role"] != "system" and message["content"].strip()]
            if not contents:
                raise ValueError("GenerateContentRequest.contents: contents is not specified")
            self.assertEqual(contents[-1], {"role": "user", "content": "雨夜港口"})
            self.assertEqual(messages[0]["role"], "system")
            return "{}", 0, 0

        for api_format in ("openai", "gemini"):
            for kind in ("full", "npc", "location", "item", "action"):
                with (
                    self.subTest(api_format=api_format, kind=kind),
                    patch.object(rpg_wizard.llm_client, "get_fast_client", return_value=("m", api_format)),
                    patch.object(rpg_wizard.llm_client, "dispatch_chat_complete_with_usage", dispatch),
                ):
                    if kind == "full":
                        await rpg_wizard.generate_full(" 雨夜港口 ", False, "rpg", "7")
                    else:
                        await rpg_wizard.generate_batch(kind, " 雨夜港口 ", 3, {}, False, "7")

    async def test_full_generation_uses_cleaned_names_as_reference_whitelist(self):
        parsed = {
            "genre": "都市悬疑",
            "worldview": "雨夜港口",
            "time_slots": ["夜晚", "夜晚"],
            "stat_defs": [{"name": "理智", "initial": 50, "min": 0, "max": 100}],
            "relation_stat_defs": [{"name": "信任", "initial": 0, "min": -100, "max": 100}],
            "locations": [{"name": "码头", "description": "雾气", "connections": ["不存在"]}],
            "default_location": "码头",
            "npcs": [{"name": "侦探", "location": "码头", "initial_state": {"信任": 10, "敌意": 5}, "profile_sections": {"background": "曾在旧城区长大"}}],
            "items": [{"name": "手电", "effects": {"理智": -1, "体力": 2}}],
            "actions": [{"name": "调查", "effects": {"理智": 1}, "relation_effects": {"信任": 1}}],
        }

        async def fake_call_json(*_args, **_kwargs):
            return parsed, 0, 0

        with patch.object(rpg_wizard.llm_json, "call_json", fake_call_json):
            with patch.object(rpg_wizard.llm_client, "get_fast_client", return_value=("m", "openai")):
                out = await rpg_wizard.generate_full("雨夜港口的侦探", False, "rpg", "7")

        self.assertEqual(out["time_slots"], ["夜晚"])
        self.assertTrue(out["stat_defs"][0]["effect"])
        self.assertEqual(out["npcs"][0]["initial_state"], {"信任": 10})
        self.assertEqual(out["npcs"][0]["profile_sections"], {"background": "曾在旧城区长大"})
        self.assertEqual(out["items"][0]["effects"], {"理智": -1})
        self.assertTrue(any("不存在" in d for d in out["dropped"]))
        self.assertTrue(any("敌意" in d for d in out["dropped"]))
        self.assertTrue(any("体力" in d for d in out["dropped"]))


class GenerateBatchTests(unittest.IsolatedAsyncioTestCase):
    """单摊一键生成。白名单由路由查库传进来，清洗复用向导那几个函数，
    额外剔掉和已有的重名的——作者要的是补新的，不是覆盖。"""

    async def _gen(self, kind, parsed, known=None):
        async def fake_call_json(*_args, **_kwargs):
            return parsed, 0, 0

        with patch.object(rpg_wizard.llm_json, "call_json", fake_call_json):
            with patch.object(
                rpg_wizard.llm_client, "get_fast_client", return_value=("m", "openai")
            ):
                return await rpg_wizard.generate_batch(
                    kind, "生成几个", 3, known or {}, False, "7"
                )

    async def test_location_can_connect_to_existing_places(self):
        """新地点连回模组里已有的地点不该被丢——单摊补充的常见需求。"""
        out = await self._gen(
            "location",
            {"locations": [
                {"name": "藏书阁", "description": "满是灰", "connections": ["大礼堂", "火星"]},
            ]},
            known={"existing_names": ["大礼堂", "宿舍"]},
        )
        self.assertEqual(out["locations"][0]["connections"], ["大礼堂"])
        self.assertTrue(any("火星" in d for d in out["dropped"]))
        # 单摊补充不碰起始地点
        self.assertNotIn("default_location", out)

    async def test_duplicate_names_are_skipped(self):
        out = await self._gen(
            "item",
            {"items": [
                {"name": "治伤药水", "effects": {}},
                {"name": "解毒剂", "effects": {}},
            ]},
            known={"existing_names": ["治伤药水"], "stat_names": []},
        )
        names = [it["name"] for it in out["items"]]
        self.assertEqual(names, ["解毒剂"])
        self.assertTrue(any("治伤药水" in d for d in out["dropped"]))

    async def test_npc_references_are_whitelisted(self):
        out = await self._gen(
            "npc",
            {"npcs": [{
                "name": "斯内普", "location": "地牢",
                "initial_state": {"好感": -10, "恐惧": 5},
            }]},
            known={"relation_names": ["好感"], "location_names": ["大礼堂"], "existing_names": []},
        )
        self.assertEqual(out["npcs"][0]["initial_state"], {"好感": -10})
        self.assertEqual(out["npcs"][0]["location"], "")
        self.assertTrue(any("恐惧" in d for d in out["dropped"]))

    async def test_action_only_returns_actions(self):
        """道具那一摊生成动作不该混进 items 键。"""
        out = await self._gen(
            "action",
            {"actions": [{"name": "祈祷", "effects": {"信仰": 5}}]},
            known={"stat_names": ["信仰"], "existing_names": []},
        )
        self.assertIn("actions", out)
        self.assertNotIn("items", out)
        self.assertEqual(out["actions"][0]["effects"], {"信仰": 5})

    async def test_unknown_kind_is_a_noop(self):
        out = await self._gen("faction", {"factions": []})
        self.assertEqual(out, {"dropped": []})

    async def test_kinds_covers_every_kind_the_route_accepts(self):
        """KINDS 是这里的白名单，路由的 _GENERATE_MODELS 是那边的。漏一个的后果很闷：
        请求过得去、模型压根没调，前端只看到「没生成出能用的内容」。技能和任务就这么
        哑了一阵。"""
        from app.api.routes.rpg import _GENERATE_MODELS

        self.assertEqual(set(rpg_wizard.KINDS), set(_GENERATE_MODELS))

    async def test_skill_and_task_actually_reach_the_model(self):
        out = await self._gen(
            "skill",
            {"skills": [{"name": "疾风步", "cooldown": 2, "effects": {"体力": -5}}]},
            known={"stat_names": ["体力"], "existing_names": []},
        )
        self.assertEqual(out["skills"][0]["effects"], {"体力": -5})
        out = await self._gen(
            "task",
            {"tasks": [{"name": "送信", "objective": "把信交到老周手上", "effects": {}}]},
            known={"stat_names": [], "existing_names": []},
        )
        self.assertEqual(out["tasks"][0]["objective"], "把信交到老周手上")


if __name__ == "__main__":
    unittest.main()
