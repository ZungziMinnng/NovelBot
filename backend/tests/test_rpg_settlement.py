import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.api.routes.rpg import settle_message, update_message
from app import database
from app.database import Base
from app.models import novel, chapter, character, memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, user, tavern, rpg
from app.models import llm_usage, sensitive_word, text_replace_backup
from app.models.rpg import RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgSession
from app.schemas.rpg import RpgMessageOut, RpgMessageUpdate
from app.services.rpg_context import build_rpg_messages, npc_place
from app.services.rpg_memory import event_memory, text_revision
from app.services.rpg_settlement import DOMAINS, SettlementConflict, _event_groups, _filter_milestones, _with_cap, capture, inspect_proposal, normalize_proposal, seed_settlement, state_changes


def proposal(narration, **delta):
    changes = {domain for domain, keys in DOMAINS.items() if any(delta.get(key) for key in keys)}
    return {
        "checks": {domain: "changed" if domain in changes else "unchanged" for domain in DOMAINS},
        "events": [{"kind": "state", "quote": narration, "domains": [domain]} for domain in changes if domain != "memory"],
        **delta,
    }


class SettlementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.store = self.sessions()
        self.user = SimpleNamespace(id=1)
        self.module = RpgModule(user_id=1, name="结算测试", check_mode="never",
                                stat_defs=[{"name": "精力", "initial": 50, "min": 0, "max": 100}],
                                relation_stat_defs=[{"name": "信任", "initial": 10, "min": 0, "max": 100}])
        self.store.add(self.module)
        await self.store.flush()
        self.garden = RpgLocation(module_id=self.module.id, name="灵药园")
        self.npcs = [RpgNpc(module_id=self.module.id, name=name, location="灵药园") for name in ("园丁甲", "园丁乙")]
        self.store.add_all([self.garden, *self.npcs, RpgLocation(module_id=self.module.id, name="柴房")])
        await self.store.flush()
        self.sess = RpgSession(module_id=self.module.id, char_name="旅人", location="柴房", slot="清晨", day=1,
                               stats={"精力": 50}, inventory=[{"name": "钥匙", "qty": 1}], turn_count=1,
                               npc_states={str(npc.id): {"信任": 10} for npc in self.npcs})
        self.store.add(self.sess)
        await self.store.commit()
        self.patcher = patch.object(rpg_turn, "AsyncSessionLocal", self.sessions)
        self.patcher.start()
        self.model_patch = patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("model", "openai"))
        self.model_patch.start()

    async def asyncTearDown(self):
        self.model_patch.stop()
        self.patcher.stop()
        await self.store.close()
        await self.engine.dispose()

    async def make_reply(self, narration, present=None, mode="group", engine_before=None, fixed_location=None):
        await self.store.refresh(self.sess)
        report = seed_settlement(self.sess, 0, engine_before or capture(self.sess), "", fixed_location,
                                 mode, (present or [None])[0] if mode == "private" else None, present)
        row = RpgMessage(session_id=self.sess.id, role="assistant", content=narration, location=self.sess.location,
                         present=present or [], settlement=report)
        self.store.add(row)
        await self.store.commit()
        return row

    async def settle(self, row, data, label=""):
        # label 就是判定档位（大成功/成功/险胜/失败/大失败），默认空串 = 这一轮
        # 没判定。「失败必须有代价」那道门禁只看它，所以要能从测试里递进来
        callback = data if callable(data) else AsyncMock(return_value=(copy.deepcopy(data), 2, 3))
        with patch.object(rpg_turn, "call_json", callback):
            result = await rpg_turn._settle(self.sess.id, row.id, row.content, label, "")
        await self.store.refresh(self.sess)
        await self.store.refresh(row)
        return result

    async def test_narrative_movement_updates_location_roster_and_next_context(self):
        narration = "你抵达灵药园，园丁甲和园丁乙向你招手。"
        row = await self.make_reply(narration)
        result = await self.settle(row, proposal(narration, location="灵药园"))
        self.assertEqual(result["settlement"]["status"], "done")
        self.assertEqual(self.sess.location, "灵药园")
        self.assertTrue(all(self.sess.npc_states[str(npc.id)]["met"] for npc in self.npcs))
        _, diagnostic = await build_rpg_messages(self.store, self.module, self.sess, [row], "向两位园丁问好")
        self.assertEqual({entry["id"] for entry in diagnostic["npcs_here"]}, {npc.id for npc in self.npcs})
        self.assertEqual(row.present, [])

    async def test_other_npc_movement_does_not_block_this_scenes_updates(self):
        actor, background = self.npcs
        self.sess.location = "灵药园"
        self.sess.npc_places = {str(actor.id): "柴房", str(background.id): "柴房"}
        await self.store.commit()
        narration = "园丁甲走进灵药园，关上园门。"
        row = await self.make_reply(narration, present=[actor.id])
        self.sess.npc_places = {str(actor.id): "柴房", str(background.id): "灵药园"}
        row.settlement = {**row.settlement, "protected_paths": [["npc_places", str(background.id)]]}
        await self.store.commit()
        result = await self.settle(row, proposal(
            narration, npc_places={actor.name: "灵药园"}, place_notes={"灵药园": "园门关上了"},
        ))
        self.assertEqual(result["settlement"]["status"], "done", result["settlement"]["domains"])
        self.assertEqual(self.sess.npc_places, {str(actor.id): "灵药园", str(background.id): "灵药园"})
        self.assertEqual(self.sess.place_notes["灵药园"], "园门关上了")
        self.assertNotIn("人工修改", "；".join(result["warnings"]))

    async def test_same_npc_later_position_is_still_protected(self):
        actor = self.npcs[0]
        self.sess.npc_places = {str(actor.id): "柴房"}
        await self.store.commit()
        narration = "园丁甲走进灵药园。"
        row = await self.make_reply(narration, present=[actor.id])
        self.sess.npc_places = {str(actor.id): "灵药园"}
        await self.store.commit()
        result = await self.settle(row, proposal(narration, npc_places={actor.name: "柴房"}))
        self.assertEqual(self.sess.npc_places[str(actor.id)], "灵药园")
        self.assertEqual(result["settlement"]["domains"]["scene"]["status"], "needs_review")
        self.assertNotIn("人工修改", "；".join(result["warnings"]))

    async def test_move_event_does_not_mark_empty_character_changes_for_review(self):
        narration = "沿着石阶往下走，药香渐渐淡了。"
        data = {
            "checks": {"scene": "changed", "stats": "unchanged", "inventory": "unchanged",
                       "characters": "changed", "flags": "unchanged", "memory": "unchanged"},
            "events": [{"kind": "move", "quote": narration, "domains": ["characters"]}],
            "location": "灵药园",
            "npc_places": {self.npcs[0].name: "柴房"},
            "relations": {}, "npc_notes": {},
        }
        issues, _soft, events = inspect_proposal(
            data, narration, self.npcs, [self.garden],
            {"fixed_location": None, "baseline": {"location": "柴房"},
             "origin_present": [npc.id for npc in self.npcs], "mode": "group"},
            self.sess.char_name,
        )
        self.assertEqual(events[0]["domains"], ["scene"])
        self.assertNotIn("已报告变化，但缺少对应更新", issues["characters"])

    async def test_player_arrival_cannot_move_a_colocated_npc_to_a_side_room(self):
        self.sess.location = "藏经阁"
        self.npcs[0].location = "藏经阁"
        self.store.add_all([RpgLocation(module_id=self.module.id, name=name)
                            for name in ("藏经阁", "藏经阁偏殿")])
        await self.store.commit()
        narration = "你沿着廊道拐了个弯，偏殿正厅的门虚掩着。园丁甲坐在偏殿里，笑着与你交谈。"
        row = await self.make_reply(narration, fixed_location="藏经阁")
        data = proposal(narration, location="藏经阁", npc_places={"园丁甲": "藏经阁偏殿"},
                        relations={"园丁甲": {"信任": 1}})
        data["events"] = [
            {"kind": "move", "quote": "你沿着廊道拐了个弯，偏殿正厅的门虚掩着。", "domains": ["scene"], "participants": []},
            {"kind": "relationship", "quote": "园丁甲坐在偏殿里，笑着与你交谈。", "domains": ["characters"], "participants": [self.npcs[0].id]},
        ]
        for attempt in (1, 2):
            result = await self.settle(row, copy.deepcopy(data))
            self.assertEqual(result["settlement"]["status"], "partial")
            self.assertEqual(row.settlement["attempts"], attempt)
            self.assertEqual(self.sess.location, "藏经阁")
            self.assertEqual(npc_place(self.npcs[0], self.sess.slot, self.sess.npc_places), "藏经阁")
            self.assertEqual(self.sess.npc_states[str(self.npcs[0].id)]["信任"], 11)
            self.assertTrue(any("实际离场" in warning for warning in result["warnings"]))

    async def test_colocated_npc_can_leave_with_its_own_move_event(self):
        self.npcs[0].location = "柴房"
        await self.store.commit()
        for narration in ("园丁甲告别你，独自走出柴房，回到灵药园。",
                          "她向你告别，独自走出柴房，回到灵药园。",
                          "你回到柴房，园丁甲独自走进灵药园。"):
            self.sess.npc_places = {}
            await self.store.commit()
            row = await self.make_reply(narration, present=[self.npcs[0].id], fixed_location="柴房")
            data = proposal(narration, npc_places={"园丁甲": "灵药园"})
            data["events"] = [{"kind": "move", "quote": narration, "domains": ["scene"], "participants": [self.npcs[0].id]}]
            result = await self.settle(row, data)
            self.assertEqual(result["settlement"]["status"], "done")
            self.assertEqual(self.sess.location, "柴房")
            self.assertEqual(self.sess.npc_places[str(self.npcs[0].id)], "灵药园")

    async def test_clearing_a_colocated_npc_override_also_requires_departure(self):
        self.sess.npc_places = {str(self.npcs[0].id): "柴房"}
        await self.store.commit()
        row = await self.make_reply("园丁甲站在你面前与你交谈。", present=[self.npcs[0].id], fixed_location="柴房")
        result = await self.settle(row, proposal(row.content, npc_places={"园丁甲": ""}))
        self.assertEqual(result["settlement"]["status"], "partial")
        self.assertEqual(self.sess.npc_places[str(self.npcs[0].id)], "柴房")
        row = await self.make_reply("园丁甲离开柴房，回到灵药园。", present=[self.npcs[0].id], fixed_location="柴房")
        data = proposal(row.content, npc_places={"园丁甲": ""})
        data["events"] = [{"kind": "move", "quote": row.content, "domains": ["scene"], "participants": [self.npcs[0].id]}]
        await self.settle(row, data)
        self.assertNotIn(str(self.npcs[0].id), self.sess.npc_places)

    async def test_arriving_npc_can_join_the_fixed_player_location(self):
        row = await self.make_reply("园丁甲推开柴房的门，走到你面前。", fixed_location="柴房")
        result = await self.settle(row, proposal(row.content, npc_places={"园丁甲": "柴房"}))
        self.assertEqual(result["settlement"]["status"], "done")
        self.assertEqual(self.sess.npc_places[str(self.npcs[0].id)], self.sess.location)

    async def test_scene_repair_can_keep_a_colocated_npc_in_place(self):
        self.npcs[0].location = "柴房"
        await self.store.commit()
        row = await self.make_reply("园丁甲在你面前坐下，与你交谈。", present=[self.npcs[0].id], fixed_location="柴房")
        callback = AsyncMock(side_effect=[
            (proposal(row.content, npc_places={"园丁甲": "灵药园"}), 1, 1),
            (proposal(row.content, npc_places={"园丁甲": "柴房"}), 1, 1),
        ])
        result = await self.settle(row, callback)
        self.assertEqual(callback.await_count, 2)
        self.assertEqual(result["settlement"]["status"], "done")
        self.assertEqual(self.sess.npc_places[str(self.npcs[0].id)], "柴房")

    async def test_an_empty_npc_place_survives_as_a_clear(self):
        # 提示词里写死了「她只是回到自己平时待的地方，就写空串」，所以空串是一种
        # 变化而不是没填。在这里筛掉的话整个 npc_places 会空成 {}，下游看见
        # 「声称有变化却什么都没写」，scene 域连同地点一起被整域打回
        proposal_data = {"npc_places": {self.npcs[0].name: "", "无名氏": 7}}
        self.assertEqual(
            normalize_proposal(proposal_data)["npc_places"], {self.npcs[0].name: ""},
        )

    def _inspect(self, data, narration):
        return inspect_proposal(
            data, narration, self.npcs, [self.garden],
            {"fixed_location": None, "baseline": {"location": "柴房"},
             "origin_present": [npc.id for npc in self.npcs], "mode": "group"},
            self.sess.char_name,
        )

    async def test_a_move_still_lands_when_the_model_forgets_the_paperwork(self):
        # 玩家写「我要去灵药园」，模型地点也填对了，只是漏了 checks.scene 或者
        # 忘了写对应的 event——这两样都是模型没守契约，代价不该是地点纹丝不动。
        # 记进软提示、照常应用
        narration = "你抵达灵药园，园丁甲向你招手。"
        no_checks = {"location": "灵药园",
                     "events": [{"kind": "move", "quote": narration, "domains": ["scene"]}]}
        issues, soft, _events = self._inspect(no_checks, narration)
        self.assertEqual(issues["scene"], [])
        self.assertIn("尚未明确核对", soft["scene"])

        no_event = {"location": "灵药园",
                    "checks": {domain: "changed" if domain == "scene" else "unchanged" for domain in DOMAINS},
                    "events": []}
        issues, soft, _events = self._inspect(no_event, narration)
        self.assertEqual(issues["scene"], [])
        self.assertIn("状态变化缺少关联的原文依据", soft["scene"])

    async def test_a_chatty_line_is_only_a_reminder(self):
        """「你接过了话头」命中易手词表，可那只是一句闲聊。

        判据是**本地正则猜的**，而从前它挂的是硬问题。挂在 memory 上还是最贵
        的那一档：apply_proposal 末尾会把这一轮已经逐字取证过的 facts 整份清掉，
        大事记也跟着不写。那个代价和「疑似」两个字的把握完全不相称
        """
        narration = "你接过了话头，把明天的行程说了一遍。"
        issues, soft, _events = self._inspect({}, narration)
        self.assertEqual(issues["inventory"], [])
        self.assertEqual(issues["memory"], [])
        self.assertTrue(any("疑似漏记关键事件" in line for line in soft["inventory"]))
        self.assertTrue(any("关键事件缺少原文记录" in line for line in soft["memory"]))

    async def test_a_real_handover_is_still_refused(self):
        # 放宽只给「疑似」那两条。东西真的递给了有名有姓的人、却没交上一条
        # transfer 事件，那是模型没守契约，照旧一票否决
        issues, _soft, _events = self._inspect({}, "你把铁钥匙交给园丁甲。")
        self.assertIn("物品交接需要同时核对背包与接收人的持有状态", issues["inventory"])
        self.assertIn("物品交接需要同时核对背包与接收人的持有状态", issues["characters"])

    async def test_a_number_out_of_nowhere_is_still_refused(self):
        # 放宽只给地点：地点另有一层硬校验（必须在登记地点表里、还要过进入条件），
        # 数值和背包没有，缺原文依据就是唯一的防幻觉门禁，照样一票否决
        narration = "你抵达灵药园，园丁甲向你招手。"
        data = {"stats": {"精力": 5},
                "checks": {domain: "changed" if domain == "stats" else "unchanged" for domain in DOMAINS},
                "events": []}
        issues, _soft, _events = self._inspect(data, narration)
        self.assertIn("状态变化缺少关联的原文依据", issues["stats"])

    async def test_a_line_of_history_does_not_have_to_drag_an_event_along(self):
        # 经历自己带原话校验，不该再被「状态变化必须配一条 event」拦一道。
        # 拦了的话模型想记一句「他今天家里出了事」就得顺手编个事件出来交差——
        # 那正是这道闸门要防的事
        narration = "园丁甲蹲在药畦边，半晌才说他家里出了事。"
        data = {
            "npc_history": {self.npcs[0].name: {
                "content": "他家里出了事，一个人蹲在药畦边",
                "quote": "园丁甲蹲在药畦边",
            }},
            "checks": {domain: "changed" if domain == "characters" else "unchanged" for domain in DOMAINS},
            "events": [],
        }
        issues, _soft, _events = self._inspect(data, narration)
        self.assertEqual(issues["characters"], [])

    async def test_a_turning_point_nobody_can_find_in_the_narration_is_dropped(self):
        # 里程碑会一直挂在后面每一轮的上下文里，编出来一条比漏掉一条贵得多
        narration = "园丁甲把最后半块干粮塞给你，说往后别再回这儿了。"
        allowed = {npc.id for npc in self.npcs}
        kept, dropped = _filter_milestones([
            {"type": "决裂", "a": "园丁甲", "b": "你",
             "content": "他给了你干粮，叫你别再回来", "quote": "说往后别再回这儿了"},
            {"type": "表白", "a": "园丁乙", "b": "你",
             "content": "她说她一直等着你", "quote": "她说她一直等着你"},
            # 自造的 type 静默丢，同 task_updates 丢掉 done/failed 之外的 action
            {"type": "结拜", "a": "园丁甲", "b": "你", "content": "你们结拜了"},
        ], narration, self.npcs, allowed)
        self.assertEqual([entry["type"] for entry in kept], ["决裂"])
        # 只有「写了但站不住」那条要往外报：静默丢掉的话它和「模型压根没写」
        # 在报告里长得一模一样
        self.assertEqual(len(dropped), 1)
        self.assertIn("表白", dropped[0])

    async def test_only_item_handover_forces_two_domains_to_agree(self):
        # 从前这里算的是所有事件 domains 的传递闭包：事件 A(scene,stats) 和
        # 事件 B(stats,inventory) 共用 stats 就焊成一组，背包差一个数量能把地点
        # 一起回滚掉。真正要求跨域一致的只有物品交接
        loose = [{"kind": "state", "domains": ["scene", "stats"]},
                 {"kind": "state", "domains": ["stats", "inventory"]}]
        self.assertEqual(_event_groups(loose), [])
        handover = [*loose, {"kind": "transfer", "domains": ["inventory", "characters"]}]
        self.assertEqual(_event_groups(handover), [{"inventory", "characters"}])

    async def test_missing_move_is_repaired_once_using_full_narration(self):
        self.module.settlement_model_ref = "settlement-only"
        self.module.fast_model_ref = "legacy-fast"
        await self.store.commit()
        narration = "你抵达灵药园，园丁甲向你招手。" + "你沿着小径查看药草。" * 400
        row = await self.make_reply(narration)
        corrected = proposal(narration, location="灵药园")
        callback = AsyncMock(side_effect=[(proposal(narration), 1, 1), (corrected, 2, 2)])
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("settlement-client", "openai")) as resolve:
            result = await self.settle(row, callback)
        resolve.assert_called_once_with("memory", "settlement-only")
        self.assertEqual(self.sess.location, "灵药园")
        self.assertEqual(callback.await_count, 2)
        for invocation in callback.call_args_list:
            self.assertEqual(invocation.args[1:3], ("settlement-client", "openai"))
        self.assertIn(narration, callback.call_args_list[0].args[0][0]["content"])
        self.assertEqual(result["aux_input_tokens"], 3)

    async def test_empty_settlement_model_uses_legacy_fast_model(self):
        self.module.settlement_model_ref = ""
        self.module.fast_model_ref = "legacy-fast"
        await self.store.commit()
        row = await self.make_reply("你停下来看看周围。")
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("legacy-client", "openai")) as resolve:
            await self.settle(row, proposal(row.content))
        resolve.assert_called_once_with("memory", "legacy-fast")

    async def test_a_discovery_reported_only_in_the_repair_round_still_lands(self):
        # 修复那一轮是完整重出一份 JSON，模型常在这时候才把人补上。它不属于任何
        # domain，搬 DOMAINS 的那一圈够不着它——不合过来的话，只在修复轮报的人
        # 会凭空消失，玩家看到「发现」永远是空的
        narration = "你抵达灵药园，园丁甲向你招手。一个叫柳娘子的妇人提着竹篮从田埂上走过来。"
        row = await self.make_reply(narration)
        corrected = proposal(narration, location="灵药园")
        corrected["discoveries"] = {"characters": [
            {"name": "柳娘子", "hint": "一个叫柳娘子的妇人提着竹篮从田埂上走过来"}
        ]}
        callback = AsyncMock(side_effect=[(proposal(narration), 1, 1), (corrected, 2, 2)])
        result = await self.settle(row, callback)
        self.assertEqual(callback.await_count, 2)
        self.assertEqual([entry["name"] for entry in result["discoveries"]], ["柳娘子"])

    async def test_a_repair_round_adds_to_what_the_first_round_already_reported(self):
        # 两轮各报一半时要并起来，不能被后一轮盖掉。同一个名字报两遍由
        # filter_discoveries 按名字去重，这里只保证不丢
        narration = ("你抵达灵药园，园丁甲向你招手。一个叫柳娘子的妇人走过来，"
                     "身后跟着个挑担的货郎。")
        row = await self.make_reply(narration)
        first = proposal(narration)
        first["discoveries"] = {"characters": [
            {"name": "柳娘子", "hint": "一个叫柳娘子的妇人走过来"}
        ]}
        corrected = proposal(narration, location="灵药园")
        corrected["discoveries"] = {"characters": [
            {"name": "柳娘子", "hint": "一个叫柳娘子的妇人走过来"},
            {"name": "货郎", "hint": "身后跟着个挑担的货郎"},
        ]}
        callback = AsyncMock(side_effect=[(first, 1, 1), (corrected, 2, 2)])
        result = await self.settle(row, callback)
        self.assertEqual(callback.await_count, 2)
        self.assertEqual(sorted(entry["name"] for entry in result["discoveries"]), ["柳娘子", "货郎"])

    async def test_unrepaired_missing_move_is_visible_and_not_a_success(self):
        narration = "你抵达灵药园，停下了脚步。"
        row = await self.make_reply(narration)
        result = await self.settle(row, proposal(narration))
        self.assertEqual(self.sess.location, "柴房")
        self.assertEqual(result["settlement"]["domains"]["scene"]["status"], "needs_review")
        self.assertEqual(result["settlement"]["status"], "partial")

    async def test_repeated_success_returns_cached_result_without_extra_cost(self):
        narration = "走了许久，你有些疲惫，精力降低。"
        row = await self.make_reply(narration)
        await self.settle(row, proposal(narration, stats={"精力": -5}))
        callback = AsyncMock(side_effect=AssertionError("不应重复调用模型"))
        await self.settle(row, callback)
        self.assertEqual(callback.await_count, 0)
        self.assertEqual(self.sess.stats["精力"], 45)
        self.assertEqual(row.aux_input_tokens, 2)

    async def test_partial_retry_preserves_successful_changes_without_reapplying(self):
        narration = "你走了许久，有些疲惫。"
        row = await self.make_reply(narration)
        initial = proposal(narration, stats={"精力": -5}, inventory="错误格式")
        await self.settle(row, initial)
        self.assertEqual(self.sess.stats["精力"], 45)
        await self.settle(row, proposal(narration))
        self.assertEqual(self.sess.stats["精力"], 45)
        self.assertEqual(row.settlement["status"], "done")

    async def test_edit_then_resettle_replaces_old_delta_and_clears_summaries(self):
        row = await self.make_reply("你走了许久，有些疲惫。")
        await self.settle(row, proposal(row.content, stats={"精力": -5}))
        self.sess.summary, self.sess.thread_summaries = "已经疲惫", {str(self.npcs[0].id): "旧剧情"}
        await self.store.commit()
        await update_message(row.id, RpgMessageUpdate(content="你在原地休息，没有任何变化。"), self.user, self.store)
        self.assertEqual(row.settlement["status"], "stale")
        self.assertEqual(self.sess.summary, "")
        self.assertEqual(self.sess.thread_summaries, {})
        await self.settle(row, proposal(row.content))
        self.assertEqual(self.sess.stats["精力"], 50)
        self.assertEqual(row.content, "你在原地休息，没有任何变化。")

    async def test_retry_keeps_engine_costs_and_does_not_repeat_them(self):
        before = capture(self.sess)
        self.sess.stats = {"精力": 45}
        await self.store.commit()
        row = await self.make_reply("你使用机关，消耗了精力。", engine_before=before)
        await self.settle(row, proposal(row.content, stats={"精力": -5}))
        self.assertEqual(self.sess.stats["精力"], 45)
        await update_message(row.id, RpgMessageUpdate(content="你拉下机关。"), self.user, self.store)
        await self.settle(row, proposal(row.content))
        self.assertEqual(self.sess.stats["精力"], 45)

    async def test_recalculation_preserves_a_manually_removed_note(self):
        identity = str(self.npcs[0].id)
        self.sess.npc_notes = {identity: {"伤势": "旧伤", "衣着": "布衣"}}
        await self.store.commit()
        row = await self.make_reply("园丁甲换了外套。", present=[self.npcs[0].id])
        await self.settle(row, proposal(row.content, npc_notes={f"npc:{identity}": {"衣着": "外套"}}))
        self.sess.npc_notes = {identity: {"衣着": "外套"}}
        await self.store.commit()
        await update_message(row.id, RpgMessageUpdate(content="园丁甲整理了衣服。"), self.user, self.store)
        await self.settle(row, proposal(row.content))
        self.assertEqual(self.sess.npc_notes, {identity: {"衣着": "布衣"}})

    async def test_later_turn_blocks_recalculation(self):
        row = await self.make_reply("你观察四周。")
        self.store.add(RpgMessage(session_id=self.sess.id, role="user", content="接着行动"))
        await self.store.commit()
        with self.assertRaisesRegex(SettlementConflict, "已有新回合"):
            await self.settle(row, proposal(row.content))
        self.assertEqual(self.sess.stats["精力"], 50)

    async def test_clock_change_blocks_recalculation(self):
        row = await self.make_reply("你观察四周。")
        self.sess.slot = "中午"
        await self.store.commit()
        with self.assertRaisesRegex(SettlementConflict, "时间已推进"):
            await self.settle(row, proposal(row.content))

    async def test_concurrent_retries_cannot_apply_twice(self):
        row = await self.make_reply("你走了一段路，有些疲惫。")
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_call(*args, **kwargs):
            entered.set()
            await release.wait()
            return proposal(row.content, stats={"精力": -5}), 1, 1

        with patch.object(rpg_turn, "call_json", slow_call):
            pending = asyncio.create_task(rpg_turn._settle(self.sess.id, row.id, row.content, "", ""))
            await asyncio.wait_for(entered.wait(), 5)
            try:
                with self.assertRaisesRegex(SettlementConflict, "正在结算"):
                    await rpg_turn._settle(self.sess.id, row.id, row.content, "", "")
            finally:
                release.set()
                await pending
        await self.store.refresh(self.sess)
        self.assertEqual(self.sess.stats["精力"], 45)

    async def test_edit_during_model_call_discards_old_result(self):
        row = await self.make_reply("你走了一段路，有些疲惫。")
        original = row.content

        async def edit_while_waiting(*args, **kwargs):
            async with self.sessions() as store:
                await update_message(row.id, RpgMessageUpdate(content="你没有行动。"), self.user, store)
            return proposal(original, stats={"精力": -5}), 1, 1

        with self.assertRaisesRegex(SettlementConflict, "修改或回滚"):
            await self.settle(row, edit_while_waiting)
        await self.store.refresh(self.sess)
        await self.store.refresh(row)
        self.assertEqual(self.sess.stats["精力"], 50)
        self.assertEqual(row.settlement["status"], "stale")

    async def test_llm_failure_is_durable_and_retryable(self):
        row = await self.make_reply("你看着药草。")
        with self.assertRaisesRegex(RuntimeError, "服务中断"):
            await self.settle(row, AsyncMock(side_effect=RuntimeError("服务中断")))
        await self.store.refresh(row)
        self.assertEqual(row.settlement["status"], "failed")
        self.assertEqual(row.content, "你看着药草。")
        self.assertIsNone(row.state_delta)
        await self.settle(row, proposal(row.content))
        self.assertEqual(row.settlement["status"], "done")

    async def test_unregistered_location_is_rejected_and_proposed_is_auditable(self):
        row = await self.make_reply("你进入天外秘境。")
        await self.settle(row, proposal(row.content, location="天外秘境"))
        self.assertEqual(self.sess.location, "柴房")
        self.assertEqual(row.settlement["proposed"]["location"], "天外秘境")
        self.assertNotIn("location", row.settlement["applied"])
        self.assertNotIn("location", row.state_delta)

    async def test_entry_requirements_cannot_be_bypassed_by_narration(self):
        self.garden.enter_requires = {"stats": {"精力": {"op": ">=", "value": 99}}}
        await self.store.commit()
        row = await self.make_reply("你抵达灵药园，停下来。")
        await self.settle(row, proposal(row.content, location="灵药园"))
        self.assertEqual(self.sess.location, "柴房")
        self.assertTrue(any("无法进入" in warning for warning in row.settlement["warnings"]))

    async def test_unknown_npc_cannot_receive_a_state_change(self):
        row = await self.make_reply("园丁甲整理了衣服。", present=[self.npcs[0].id])
        await self.settle(row, proposal(row.content, npc_notes={"npc:99999": {"伤势": "重伤"}}))
        self.assertEqual(self.sess.npc_notes, {})
        self.assertEqual(row.settlement["domains"]["characters"]["status"], "needs_review")

    async def test_incomplete_transfer_changes_neither_inventory_nor_owner(self):
        narration = "你把钥匙交给园丁甲，他收好了。"
        row = await self.make_reply(narration, present=[self.npcs[0].id])
        data = proposal(narration, inventory=[{"name": "钥匙", "qty": -1}])
        data["events"] = [{"kind": "transfer", "quote": narration, "domains": ["inventory", "characters"],
                           "item": "钥匙", "qty": 1, "from": "player", "to": f"npc:{self.npcs[0].id}"}]
        await self.settle(row, data)
        self.assertEqual(self.sess.inventory, [{"name": "钥匙", "qty": 1}])
        self.assertEqual(self.sess.npc_notes, {})

    async def test_complete_transfer_updates_both_sides_once(self):
        identity = self.npcs[0].id
        narration = "你把钥匙交给园丁甲，他收好了。"
        row = await self.make_reply(narration, present=[identity])
        data = proposal(narration, inventory=[{"name": "钥匙", "qty": -1}], npc_notes={f"npc:{identity}": {"持有": "钥匙"}})
        data["events"] = [{"kind": "transfer", "quote": narration, "domains": ["inventory", "characters"],
                           "item": "钥匙", "qty": 1, "from": "player", "to": f"npc:{identity}"}]
        await self.settle(row, data)
        self.assertEqual(self.sess.inventory, [])
        self.assertEqual(self.sess.npc_notes[str(identity)]["持有"], "钥匙")
        await self.settle(row, data)
        self.assertEqual(self.sess.inventory, [])

    async def test_invalid_evidence_is_not_saved_as_long_term_fact(self):
        row = await self.make_reply("园丁甲与你点头致意。", present=[self.npcs[0].id])
        data = proposal(row.content)
        data["events"] = [{"kind": "promise", "quote": "园丁甲答应送你一百枚灵石", "domains": []}]
        await self.settle(row, data)
        self.assertEqual(row.settlement["facts"], [])

    async def test_private_promise_retains_witnesses_and_source(self):
        identity, stranger = [npc.id for npc in self.npcs]
        narration = "园丁甲答应明天帮你查看药草。"
        row = await self.make_reply(narration, present=[identity], mode="private")
        data = proposal(narration)
        data["events"] = [{"kind": "promise", "quote": narration, "summary": "园丁甲答应帮忙查看药草", "domains": [],
                           "participants": [identity], "witnesses": [identity, stranger], "visibility": "public"}]
        await self.settle(row, data)
        self.assertEqual(row.settlement["facts"][0]["witnesses"], [identity])
        self.assertEqual(self.sess.chronicle, [])
        self.assertIn(narration, event_memory([row], {identity}, "还记得你答应了什么吗"))
        self.assertEqual(event_memory([row], {stranger}, "还记得你答应了什么吗"), "")
        self.assertEqual(event_memory([row], {identity, stranger}, "还记得你答应了什么吗"), "")
        self.assertIn(f"#{row.id}", event_memory([row], set(), "回忆承诺"))

    async def test_edited_source_is_excluded_from_recall(self):
        row = RpgMessage(id=1, role="assistant", content="旧约定", settlement={
            "status": "done", "revision": text_revision("旧约定"),
            "facts": [{"kind": "promise", "quote": "旧约定", "witnesses": [], "visibility": "witnessed"}],
        })
        row.content = "新约定"
        self.assertEqual(event_memory([row], set(), "回忆"), "")

    async def test_recall_reports_participants_for_second_hop(self):
        """第二跳：入选往事牵涉的 NPC id 从出参吐出来，供上层补卡。

        提到「药园失火」→ 命中这条往事 → participants 里的人被收集，
        build_rpg_messages 靠这份 id 给放火的人也出完整卡，而不是只剩一句 summary。
        """
        content = "药园失火那晚，园丁甲把火扑灭了。"
        row = RpgMessage(id=1, role="assistant", content=content, settlement={
            "status": "done", "revision": text_revision(content),
            "facts": [{"kind": "rescue", "quote": content, "summary": "园丁甲扑灭药园大火",
                       "participants": [7, 12], "witnesses": [], "visibility": "public"}],
        })
        hop: set[int] = set()
        recalled = event_memory([row], set(), "回忆药园失火", out_participants=hop)
        self.assertIn("药园失火", recalled)
        self.assertEqual(hop, {7, 12})

    async def test_unsettled_message_is_recallable_by_its_own_text(self):
        """结算失败的回合靠正文也能召回。

        旧实现只扫 settlement["facts"]，于是结算失败、改稿后 revision 对不上、
        或没被任何事实引用的回合，整段内容谁也搜不到——玩家报的"找不回细节"
        主要是这个，不是排序不准。
        """
        broken = RpgMessage(id=41, role="assistant", content="药园失火那晚我在场。",
                            settlement={"status": "error", "facts": []})
        self.assertIn("药园失火那晚我在场", event_memory([broken], set(), "回忆药园失火"))

    async def test_irrelevant_message_is_not_excerpted(self):
        """无关消息不进摘录：两个排序列表必须同筛。

        rrf_fuse 取的是并集，只筛词面分那一侧的话，被淘汰的候选会从 BM25 那一路
        原样回来——jieba 切出的单字（「你」「把」）足够让它命中。实测问「答应过
        什么、药园那把火」会把「买了一把断刃」顶进摘录额度。
        """
        promise = RpgMessage(id=1, role="assistant", content="她答应替你保守秘密。")
        unrelated = RpgMessage(id=2, role="assistant", content="你在北市买了一把断刃。")
        recalled = event_memory([promise, unrelated], set(), "还记得你答应过我什么吗")
        self.assertIn("#1", recalled)
        self.assertNotIn("#2", recalled)

    async def test_raw_excerpt_obeys_the_presence_roster(self):
        """正文召回的可见性判据：本轮听众得全在当时的在场名单里。

        消息没有 visibility 字段，所以这条比事实那道闸门更严（见 rpg_memory 里的
        ponytail 注释）。宁可少召回，不能让她知道她当时不在场的事。
        """
        row = RpgMessage(id=7, role="assistant", content="药园失火那晚我们都在场。",
                         present=[7])
        self.assertEqual(event_memory([row], {9}, "回忆药园失火"), "")
        self.assertIn("药园失火", event_memory([row], {7}, "回忆药园失火"))
        self.assertIn("药园失火", event_memory([row], set(), "回忆药园失火"))

    async def test_window_message_is_not_excerpted_again(self):
        """窗口内那几条的整段正文已经原样进 prompt，再摘一次就是重复占额度。"""
        in_window = RpgMessage(id=9, role="assistant", content="药园失火那晚我们都在场。")
        older = RpgMessage(id=3, role="assistant", content="药园失火是有人投毒。")
        recalled = event_memory([in_window, older], set(), "回忆药园失火", window_ids={9})
        self.assertNotIn("#9", recalled)
        self.assertIn("#3", recalled)

    async def test_witness_gate_is_not_bypassed_by_raw_excerpt(self):
        """结算有效的回合不补正文候选，否则就绕开了 witnesses 闸门。

        结算会把见证人收窄到比在场名单更小（见
        test_private_promise_retains_witnesses_and_source）：两个人都在屋里，
        但只有一个人真看见了。补正文候选的话，另一个人就能从正文那条路读到
        事实闸门刚拦下的同一段内容。
        """
        content = "药园失火那晚只有她看见了纵火的人。"
        row = RpgMessage(id=11, role="assistant", content=content, present=[3, 5], settlement={
            "status": "done", "revision": text_revision(content),
            "facts": [{"kind": "promise", "quote": content, "witnesses": [3],
                       "visibility": "witnessed"}],
        })
        self.assertEqual(event_memory([row], {5}, "回忆药园失火"), "")
        self.assertIn("药园失火", event_memory([row], {3}, "回忆药园失火"))

    async def test_retry_endpoint_checks_ownership_and_omits_internal_baseline(self):
        row = await self.make_reply("你看着药草。")
        with self.assertRaises(HTTPException) as raised:
            await settle_message(row.id, SimpleNamespace(id=2), self.store)
        self.assertEqual(raised.exception.status_code, 404)
        with patch.object(rpg_turn, "call_json", AsyncMock(return_value=(proposal(row.content), 1, 1))):
            result = await settle_message(row.id, self.user, self.store)
        payload = RpgMessageOut.model_validate(result).model_dump()
        self.assertEqual(payload["settlement"]["status"], "done")
        self.assertNotIn("baseline", payload["settlement"])

    async def test_legacy_reply_without_baseline_is_not_blindly_applied(self):
        row = RpgMessage(session_id=self.sess.id, role="assistant", content="你看着药草。")
        self.store.add(row)
        await self.store.commit()
        with self.assertRaisesRegex(SettlementConflict, "没有独立结算基线"):
            await self.settle(row, proposal(row.content))

    async def test_editing_earlier_reply_requires_rewind_without_invalidating_memories(self):
        first = await self.make_reply("你在原地休息。")
        await self.settle(first, proposal(first.content))
        second = await self.make_reply("园丁甲答应带路。")
        await self.settle(second, proposal(second.content))
        previous_status = second.settlement["status"]
        with self.assertRaises(HTTPException) as caught:
            await update_message(first.id, RpgMessageUpdate(content="你继续睡觉。"), self.user, self.store)
        self.assertEqual(caught.exception.status_code, 409)
        await self.store.refresh(second)
        self.assertEqual(second.settlement["status"], previous_status)
        self.assertNotIn("invalidated_by", second.settlement)

    async def test_failed_recalculation_does_not_resurrect_previous_revision(self):
        row = await self.make_reply("你走了许久，有些疲惫。")
        await self.settle(row, proposal(row.content, stats={"精力": -5}))
        await update_message(row.id, RpgMessageUpdate(content="你没有行动。"), self.user, self.store)
        with self.assertRaises(RuntimeError):
            await self.settle(row, AsyncMock(side_effect=RuntimeError("断网")))
        await self.store.refresh(row)
        await self.settle(row, proposal(row.content))
        self.assertEqual(self.sess.stats["精力"], 50)

    async def test_explicit_removal_clears_recovered_injury(self):
        identity = self.npcs[0].id
        self.sess.npc_notes = {str(identity): {"伤势": "肩伤", "衣服": "布衣"}}
        await self.store.commit()
        row = await self.make_reply("园丁甲的伤势痊愈了。", present=[identity])
        data = proposal(row.content, npc_notes={f"npc:{identity}": {"伤势": None}})
        await self.settle(row, data)
        self.assertEqual(self.sess.npc_notes, {str(identity): {"衣服": "布衣"}})

    async def test_dead_npc_cannot_silently_return_to_life(self):
        identity = self.npcs[0].id
        self.sess.npc_notes = {str(identity): {"存续": "死亡"}}
        await self.store.commit()
        row = await self.make_reply("园丁甲站在花丛中。", present=[identity])
        await self.settle(row, proposal(row.content, npc_notes={f"npc:{identity}": {"存续": "存活"}}))
        self.assertEqual(self.sess.npc_notes[str(identity)]["存续"], "死亡")
        self.assertTrue(any("存续" in warning for warning in row.settlement["warnings"]))

    async def test_same_name_npcs_require_ids_for_unambiguous_updates(self):
        for npc in self.npcs:
            npc.name = "园丁"
        await self.store.commit()
        row = await self.make_reply("园丁整理衣服。", present=[npc.id for npc in self.npcs])
        await self.settle(row, proposal(row.content, npc_notes={"园丁": {"衣服": "蓝衣"}}))
        self.assertEqual(self.sess.npc_notes, {})
        await self.settle(row, proposal(row.content, npc_notes={f"npc:{self.npcs[0].id}": {"衣服": "蓝衣"}}))
        self.assertEqual(self.sess.npc_notes, {str(self.npcs[0].id): {"衣服": "蓝衣"}})

    async def test_a_rewritten_appearance_is_applied_and_reported(self):
        # 药剂改造这类「永远回不去」的变化。写进 npc_notes 会被那条 10 条的
        # 上限淘汰掉（身体改造写一次就再不刷新，永远排在淘汰队列最前面），
        # 所以它有自己的一列，注入时压过作者写的 appearance
        identity = self.npcs[0].id
        narration = "园丁甲喝下那碗药，胸口肉眼可见地鼓了起来。"
        row = await self.make_reply(narration, present=[identity])
        await self.settle(row, proposal(
            narration, npc_appearance={f"npc:{identity}": {"胸部": "服药后长出，已定形"}}))
        self.assertEqual(self.sess.npc_appearance, {str(identity): {"胸部": "服药后长出，已定形"}})

    async def test_an_override_for_someone_not_in_front_of_you_is_refused(self):
        # 和近况同一道门，而且更该守：门外的人连近况都不让记，
        # 而外貌改写是**把这个人在你眼前的样子永久改掉**。
        #
        # 旁白刻意不提那个人的名字：allowed 是「在场 ∪ 正文里被点名的」，
        # 点了名就等于他这一轮真的出场了，那种情况下写他是合理的
        away = self.npcs[1].id
        narration = "你在柴房里坐了一会儿，药味还没散。"
        row = await self.make_reply(narration, present=[self.npcs[0].id])
        await self.settle(row, proposal(
            narration, npc_appearance={f"npc:{away}": {"胸部": "服药后长出"}}))
        self.assertEqual(self.sess.npc_appearance, {})

    async def test_transfer_quantity_cannot_exceed_inventory(self):
        identity = self.npcs[0].id
        row = await self.make_reply("你把两把钥匙交给园丁甲，他收好了。", present=[identity])
        data = proposal(row.content, inventory=[{"name": "钥匙", "qty": -2}], npc_notes={f"npc:{identity}": {"持有": "钥匙×2"}})
        data["events"] = [{"kind": "transfer", "quote": row.content, "domains": ["inventory", "characters"],
                           "item": "钥匙", "qty": 2, "from": "player", "to": f"npc:{identity}"}]
        await self.settle(row, data)
        self.assertEqual(self.sess.inventory, [{"name": "钥匙", "qty": 1}])
        self.assertEqual(self.sess.npc_notes, {})

    async def test_public_event_requires_publication_evidence(self):
        row = await self.make_reply("药园失火的消息已经传遍全镇。")
        data = proposal(row.content)
        data["events"] = [{"kind": "public", "quote": row.content, "summary": "药园失火的消息传遍全镇", "visibility": "public"}]
        await self.settle(row, data)
        self.assertEqual(self.sess.chronicle, ["药园失火的消息传遍全镇"])
        self.assertIn(row.content, event_memory([row], {self.npcs[1].id}, "回忆药园失火"))

    async def test_engine_relation_cost_is_not_applied_twice(self):
        identity = str(self.npcs[0].id)
        before = capture(self.sess)
        self.sess.npc_states = {identity: {"信任": 15}}
        await self.store.commit()
        row = await self.make_reply("园丁甲更加信任你了。", present=[int(identity)], engine_before=before)
        await self.settle(row, proposal(row.content, relations={f"npc:{identity}": {"信任": 5}}))
        self.assertEqual(self.sess.npc_states[identity]["信任"], 15)

    async def test_bad_optional_event_does_not_discard_valid_stats(self):
        row = await self.make_reply("走了许久，你感觉疲惫。")
        data = proposal(row.content, stats={"精力": -5})
        data["events"].append({"kind": [], "quote": row.content})
        await self.settle(row, data)
        self.assertEqual(self.sess.stats["精力"], 45)
        self.assertEqual(row.settlement["domains"]["memory"]["status"], "needs_review")

    async def test_manual_removal_stays_removed_across_multiple_retries(self):
        identity = str(self.npcs[0].id)
        self.sess.npc_notes = {identity: {"衣服": "布衣"}}
        await self.store.commit()
        row = await self.make_reply("你原地休息。", present=[int(identity)])
        data = proposal(row.content)
        data["checks"]["memory"] = "错误"
        await self.settle(row, data)
        self.sess.npc_notes = {}
        await self.store.commit()
        await self.settle(row, data)
        await self.settle(row, proposal(row.content))
        self.assertEqual(self.sess.npc_notes, {})

    async def test_failed_scene_event_does_not_enter_public_chronicle(self):
        row = await self.make_reply("你抵达天外秘境的消息已经传遍全镇。")
        data = proposal(row.content, location="天外秘境")
        data["events"] = [{"kind": "move", "quote": row.content, "domains": ["scene"], "visibility": "public"}]
        await self.settle(row, data)
        self.assertEqual(self.sess.location, "柴房")
        self.assertEqual(self.sess.chronicle, [])
        self.assertEqual(row.settlement["facts"], [])

    async def test_new_turn_waits_for_edited_reply_to_be_settled(self):
        from app.api.routes.rpg import stream_turn
        from app.schemas.rpg import RpgTurnRequest

        row = await self.make_reply("你休息了一会儿。")
        await update_message(row.id, RpgMessageUpdate(content="你在看风景。"), self.user, self.store)
        with self.assertRaises(HTTPException) as raised:
            await stream_turn(self.sess.id, RpgTurnRequest(content="继续"), self.user, self.store)
        self.assertEqual(raised.exception.status_code, 409)
        messages = list((await self.store.execute(select(RpgMessage))).scalars())
        self.assertEqual(len(messages), 1)

    async def test_existing_database_upgrade_preserves_old_messages_and_repeats_safely(self):
        row = await self.make_reply("旧存档的剧情保持原样。")
        identity = row.id
        async with self.engine.begin() as connection:
            await connection.execute(text("ALTER TABLE rpg_messages DROP COLUMN settlement"))
        with patch.object(database, "engine", self.engine):
            await database._run_migrations()
            await database._run_migrations()
        restored = await self.store.get(RpgMessage, identity, populate_existing=True)
        self.assertEqual(restored.content, "旧存档的剧情保持原样。")
        self.assertIsNone(restored.settlement)

    async def test_reported_location_must_match_actual_arrival(self):
        row = await self.make_reply("你抵达灵药园，停下来。")
        await self.settle(row, proposal(row.content, location="柴房"))
        self.assertEqual(row.settlement["domains"]["scene"]["status"], "needs_review")
        self.assertTrue(any("结算地点尚未对应" in warning for warning in row.settlement["warnings"]))

    async def test_misclassified_transfer_still_requires_both_sides(self):
        row = await self.make_reply("你把钥匙交给园丁甲，他收好了。", present=[self.npcs[0].id])
        await self.settle(row, proposal(row.content, inventory=[{"name": "钥匙", "qty": -1}]))
        self.assertEqual(self.sess.inventory, [{"name": "钥匙", "qty": 1}])
        self.assertEqual(row.settlement["domains"]["inventory"]["status"], "needs_review")


    # ── 判定失败必须有代价 ────────────────────────────────────────────────
    #
    # 这是「数值不是事实来源」最贵的一种表现：骰子说没成，正文写「你勉力撑住」，
    # 结算交上来一份空 delta——失败的唯一后果是多看了一段字。失败不疼，判定就
    # 只是掷骰子的动画，整套数值系统的压力全从这个口子漏掉。
    #
    # 两级：先打回去走 repair 轮（正身），repair 也不肯给才由引擎立一条处境标记
    # （下限）。引擎**不猜该扣哪一项数值**——这里没有任何依据能选中某一项，
    # 猜错一个数比不给更糟（同 confirm_item_claim 里不给 effects 的理由）。

    FAIL = "他侧身一躲，你的手扑了个空。"

    async def test_a_failed_roll_with_an_empty_delta_goes_back_for_repair(self):
        # 第一轮交空 delta，被判为硬问题；第二轮（repair）补上扣数值就放行。
        # 断言 45 而不是「小于 50」：要钉住 repair 那一份真的入了账，
        # 而不是被引擎兜底的 flag 顶过去了
        row = await self.make_reply(self.FAIL)
        repaired = proposal(self.FAIL, stats={"精力": -5})
        calls = [{"checks": {domain: "unchanged" for domain in DOMAINS}, "events": []}, repaired]
        callback = AsyncMock(side_effect=[(copy.deepcopy(payload), 2, 3) for payload in calls])
        await self.settle(row, callback, label="失败")
        self.assertEqual(callback.await_count, 2)
        self.assertEqual(self.sess.stats["精力"], 45)
        self.assertNotIn("这一次失手了", self.sess.flags or {})

    async def test_the_engine_marks_the_setback_when_repair_gives_nothing_either(self):
        # 两轮都空。这一条是整道门禁的下限：数值一项都没动，但世界至少知道
        # 这次没成——flag 能被世界书词条和 GM 接住，「什么都没发生」不能
        row = await self.make_reply(self.FAIL)
        empty = {"checks": {domain: "unchanged" for domain in DOMAINS}, "events": []}
        await self.settle(row, empty, label="大失败")
        self.assertIs((self.sess.flags or {}).get("这一次失手了"), True)
        # flag_days 必须跟着立起来，否则「某事之后 N 天」判不过（走 apply_flags
        # 而不是自己拼一个 dict，就是为了这个）
        self.assertEqual((self.sess.flag_days or {}).get("这一次失手了"), self.sess.day)
        self.assertTrue(any("没给出代价" in warning for warning in row.settlement["warnings"]))

    async def test_a_success_with_an_empty_delta_is_left_alone(self):
        # 成功而什么都没变是完全正常的一轮（「你推开门，屋里空无一人」）。
        # 这条门禁只管失败档，不能顺手把所有空 delta 都打回
        row = await self.make_reply("你推开门，屋里空无一人。")
        empty = {"checks": {domain: "unchanged" for domain in DOMAINS}, "events": []}
        result = await self.settle(row, empty, label="成功")
        self.assertEqual(result["settlement"]["status"], "done")
        self.assertNotIn("这一次失手了", self.sess.flags or {})

    async def test_a_turn_without_any_roll_is_left_alone(self):
        # 掷骰默认是关的（check_mode="never"），那时 label 是空串。这条测试钉的是
        # 「作者没开判定的模组，行为和这一批之前逐字不变」
        row = await self.make_reply(self.FAIL)
        empty = {"checks": {domain: "unchanged" for domain in DOMAINS}, "events": []}
        result = await self.settle(row, empty, label="")
        self.assertEqual(result["settlement"]["status"], "done")
        self.assertNotIn("这一次失手了", self.sess.flags or {})

    async def test_the_prompt_asks_for_a_cost_before_the_gate_has_to(self):
        # 先在提示词里说一句，比等它交了空 delta 再打回去便宜一整轮调用。
        # 成功那一档不能出现这句话——那会诱导模型给成功也编一笔损失
        from app.prompts.loader import render
        common = dict(
            narration=self.FAIL, stats={}, location="", place_note="", inventory=[],
            flags={}, npcs=[], note_keys=[], relation_names=[], step_caps={},
            engine_note="", chronicle=[], tasks=[], has_clock=False,
        )
        failed = render("rpg_settle.jinja2", outcome_label="失败", outcome_failed=True, **common)
        self.assertIn("失败必须留下代价", failed)
        won = render("rpg_settle.jinja2", outcome_label="成功", outcome_failed=False, **common)
        self.assertNotIn("失败必须留下代价", won)

    async def test_a_cost_the_engine_already_charged_counts_as_paid(self):
        """点按钮那条路的账已经结过了，模型交空 delta 是对的。

        effects 是作者写死的，引擎扣完才轮到判定。这时候再要一份代价就是双花：
        玩家点一次「强行撬锁」，精力要掉两遍。判据是 engine_before 和 baseline
        之间有没有差，口径同 _block_engine_duplicates。
        """
        await self.store.refresh(self.sess)
        before = capture(self.sess)
        before["stats"] = {"精力": 60}  # 引擎这一轮已经扣掉了 10
        row = await self.make_reply(self.FAIL, engine_before=before)
        empty = {"checks": {domain: "unchanged" for domain in DOMAINS}, "events": []}
        result = await self.settle(row, empty, label="失败")
        self.assertEqual(result["settlement"]["status"], "done")
        self.assertNotIn("这一次失手了", self.sess.flags or {})

    # ── 每轮顺带产出的那 3 条建议 ──────────────────────────────────────────
    #
    # 这条路和主动的「帮我想想」共用 rpg_suggestions 的收口，但**只改输出格式、
    # 不补新资料**：模板里只教了 free / item。下面钉的是收口本身。

    async def _suggesting(self, suggestions):
        narration = "你把钥匙插进锁孔，锁芯咔哒一声。"
        row = await self.make_reply(narration)
        data = proposal(narration)
        data["suggestions"] = suggestions
        await self.settle(row, data)
        return row.suggestions

    async def test_an_item_suggestion_is_structured_against_the_module_table(self):
        self.store.add(rpg.RpgItem(module_id=self.module.id, name="钥匙", usable=True))
        await self.store.commit()
        got = await self._suggesting([
            {"kind": "item", "name": "钥匙", "text": "拿钥匙撬开那把锁"},
            {"kind": "free", "text": "先退回柴房"},
        ])
        self.assertEqual(got[0], {
            "text": "拿钥匙撬开那把锁", "kind": "item", "name": "钥匙", "action_id": None,
        })
        self.assertEqual(got[1]["kind"], "free")

    async def test_an_item_the_player_does_not_own_degrades_to_free(self):
        """模组里有绳梯，背包里没有 —— 点了必然弹黄条，所以降级；正文留着。"""
        self.store.add(rpg.RpgItem(module_id=self.module.id, name="绳梯", usable=True))
        await self.store.commit()
        got = await self._suggesting([{"kind": "item", "name": "绳梯", "text": "架起绳梯"}])
        self.assertEqual(got[0], {
            "text": "架起绳梯", "kind": "free", "name": "", "action_id": None,
        })

    async def test_an_invented_item_name_degrades_to_free(self):
        got = await self._suggesting([{"kind": "item", "name": "万能钥匙", "text": "试试看"}])
        self.assertEqual(got[0]["kind"], "free")
        self.assertEqual(got[0]["text"], "试试看")

    async def test_plain_strings_from_an_old_override_still_work(self):
        """老覆写吐的是 list[str]，降级成 free 恰好等价于加这个功能之前。"""
        got = await self._suggesting(["推门进去", "喊一声看有没有人应", "数到三", "第四条"])
        self.assertEqual([g["text"] for g in got][:3], ["推门进去", "喊一声看有没有人应", "数到三"])
        self.assertTrue(all(g["kind"] == "free" for g in got))
        self.assertEqual(len(got), 3)


class ChangeSummaryTests(unittest.TestCase):
    """给玩家看的「这一轮变了什么」。NPC 的关系数值要落到具体的人身上。"""

    def test_a_named_relation_change_is_listed_person_by_person(self):
        before = {"npc_states": {"3": {"信任": 10, "met": True}}}
        after = {"npc_states": {"3": {"信任": 13, "met": True}}}
        _applied, lines = state_changes(before, after, npc_names={"3": "赫敏"})
        self.assertIn("赫敏的信任 +3", lines)
        # 逐项列过了就不再打一遍笼统标签，否则同一笔关系报两遍
        self.assertNotIn("人物关系或相识记录已更新", lines)

    def test_a_change_that_is_only_met_still_gets_the_generic_label(self):
        # met 是 bool，而 isinstance(True, int) 为真。不显式排除的话这一笔会报成
        # 「赫敏的met +1」——逐项列了个出来，笼统标签又恰好被它挡掉
        before = {"npc_states": {"3": {"信任": 10, "met": False}}}
        after = {"npc_states": {"3": {"信任": 10, "met": True}}}
        _applied, lines = state_changes(before, after, npc_names={"3": "赫敏"})
        self.assertEqual(lines, ["人物关系或相识记录已更新"])

    def test_an_unnamed_npc_falls_back_to_the_generic_label(self):
        # 查不到名字就说不了人话，那一笔整条跳过、落回笼统标签
        before = {"npc_states": {"3": {"信任": 10}}}
        after = {"npc_states": {"3": {"信任": 13}}}
        _applied, lines = state_changes(before, after, npc_names={"9": "赫敏"})
        self.assertEqual(lines, ["人物关系或相识记录已更新"])

    def test_the_old_call_keeps_the_generic_label(self):
        # 可选参数向后兼容：不传 npc_names 的调用点和加这一手之前逐字一致
        before = {"npc_states": {"3": {"信任": 10}}}
        after = {"npc_states": {"3": {"信任": 13}}}
        _applied, lines = state_changes(before, after)
        self.assertEqual(lines, ["人物关系或相识记录已更新"])


class StatCapTests(unittest.TestCase):
    """提示词里的数值要带分母：只给 62，模型不知道这是高还是低。"""

    def test_a_definition_with_a_ceiling_is_written_as_a_fraction(self):
        self.assertEqual(_with_cap({"好感": {"max": 100}}, "好感", 62), "62/100")

    def test_a_definition_without_a_ceiling_keeps_the_bare_number(self):
        # 钱、声望没有 max。拼成 "300/None" 会让模型以为有一道看不见的天花板
        self.assertEqual(_with_cap({"资金": {"max": None}}, "资金", 300), 300)

    def test_an_undefined_name_is_left_alone_too(self):
        self.assertEqual(_with_cap({}, "精力", 80), 80)

    def test_the_template_shows_the_fraction_and_says_what_the_slash_means(self):
        from app.prompts.loader import render
        prompt = render(
            "rpg_settle.jinja2", narration="", outcome_label="", outcome_failed=False,
            stats={"精力": "20/100"}, location="", place_note="", inventory=[], flags={},
            npcs=[], note_keys=[], relation_names=[], step_caps={}, engine_note="",
            chronicle=[], tasks=[], has_clock=False,
        )
        self.assertIn("精力 20/100", prompt)
        self.assertIn("斜杠后面是上限", prompt)


if __name__ == "__main__":
    unittest.main()
