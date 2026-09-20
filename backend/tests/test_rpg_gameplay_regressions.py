import asyncio
import copy
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import select, text

import test_rpg_movement as movement
import test_rpg_settlement as settlement_tests
from app import database
from app.models import llm_usage, sensitive_word, text_replace_backup
from app.agents import rpg_turn
from app.api.routes.rpg import (
    advance_time, create_save, move_to, restore_save, rewind_before_message,
    settle_message, stream_turn, update_message,
)
from app.models.rpg import RpgAction, RpgItem, RpgMessage, RpgModule, RpgSave, RpgSession, RpgSkill
from app.schemas.rpg import RpgMessageUpdate, RpgMoveIn, RpgSaveCreate, RpgTurnRequest
from app.services.rpg_settlement import DOMAINS, capture, seed_settlement
from app.services.rpg_operation import retain_task


class GameplayRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.world = movement.MovementTurnTests()
        await self.world.asyncSetUp()
        self.db = self.world.db
        self.sess = self.world.sess
        self.session_id = self.sess.id
        self.garden_name = self.world.garden.name
        self.user = self.world.user
        self.module = await self.db.get(RpgModule, self.sess.module_id)
        self.module.stat_defs = [{"name": "energy", "min": 0, "max": 100}]
        self.sess.stats = {"energy": 30}
        await self.db.commit()
        self.factory_patch = patch.object(rpg_turn, "AsyncSessionLocal", self.world.sessions)
        self.factory_patch.start()

    async def asyncTearDown(self):
        self.factory_patch.stop()
        await self.world.asyncTearDown()

    async def messages(self):
        return list((await self.db.execute(select(RpgMessage).where(
            RpgMessage.session_id == self.session_id,
        ).order_by(RpgMessage.id).execution_options(populate_existing=True))).scalars())

    async def pending_reply(self, status):
        report = seed_settlement(self.sess, 0, capture(self.sess), "", self.sess.location,
                                 "group", None, [])
        report["status"] = status
        row = RpgMessage(session_id=self.session_id, role="assistant", content="Nothing changes.",
                         settlement=report)
        self.db.add(row)
        await self.db.commit()
        return row

    async def test_opening_edit_remains_playable_and_save_restores_original(self):
        opening = RpgMessage(session_id=self.session_id, role="assistant", content="Original opening.")
        self.db.add(opening)
        await self.db.commit()
        save = await create_save(self.session_id, RpgSaveCreate(label="opening"), self.user, self.db)
        save_id = save.id
        await update_message(opening.id, RpgMessageUpdate(content="Edited opening."), self.user, self.db)
        self.assertIsNone(opening.settlement)
        await self.world._turn("Look around")
        await restore_save(save_id, self.user, self.db)
        messages = await self.messages()
        self.assertEqual([row.content for row in messages], ["Original opening."])
        self.assertIsNone(messages[0].settlement)

    async def test_earlier_edit_is_rejected_without_poisoning_later_turns(self):
        first = await self.pending_reply("done")
        self.db.add(RpgMessage(session_id=self.session_id, role="user", content="Later"))
        await self.db.commit()
        original = first.content
        with self.assertRaises(HTTPException) as caught:
            await update_message(first.id, RpgMessageUpdate(content="Changed"), self.user, self.db)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual((await self.messages())[0].content, original)
        self.assertEqual((await self.messages())[0].settlement["status"], "done")

    async def test_unfinished_latest_settlement_blocks_new_turn_and_clock(self):
        for status in ("failed", "pending", "running", "stale"):
            await self.db.refresh(self.sess)
            row = await self.pending_reply(status)
            row_id = row.id
            for operation in (
                lambda: stream_turn(self.session_id, RpgTurnRequest(content="Next"), self.user, self.db),
                lambda: advance_time(self.session_id, self.user, self.db),
                lambda: move_to(self.session_id, RpgMoveIn(target=self.garden_name), self.user, self.db),
            ):
                with self.assertRaises(HTTPException) as caught:
                    await operation()
                self.assertEqual(caught.exception.status_code, 409)
                self.assertIn("最新剧情", caught.exception.detail)
            row = await self.db.get(RpgMessage, row_id)
            await self.db.delete(row)
            await self.db.commit()

    async def partially_settled_reply(self):
        row = await self.pending_reply("pending")
        row.content = "You walk for a while and lose some energy."
        await self.db.commit()
        data = settlement_tests.proposal(row.content, stats={"energy": -5}, inventory="invalid")
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("model", "openai")), \
             patch.object(rpg_turn, "call_json", AsyncMock(return_value=(data, 1, 1))):
            for attempt in (1, 2):
                row = await settle_message(row.id, self.user, self.db)
                self.assertEqual(row.settlement["status"], "partial")
                self.assertEqual(row.settlement["attempts"], attempt)
                await self.db.refresh(self.sess)
                self.assertEqual(self.sess.stats, {"energy": 25})
                self.assertEqual(self.sess.inventory, [])
        return row

    async def test_partial_retry_can_continue_without_reapplying_changes(self):
        row = await self.partially_settled_reply()
        original = copy.deepcopy(row.settlement)
        await self.world._turn("Next")
        await self.db.refresh(row)
        self.assertEqual(row.settlement, original)
        self.assertGreater(len(await self.messages()), 1)

    async def test_partial_retry_allows_movement_and_ending_the_time_slot(self):
        self.module.time_slots = ["清晨", "正午", "傍晚"]
        await self.db.commit()
        row = await self.partially_settled_reply()
        original = copy.deepcopy(row.settlement)
        result = await move_to(self.session_id, RpgMoveIn(target=self.garden_name), self.user, self.db)
        self.assertEqual(result.session.location, self.garden_name)
        previous_clock = (result.session.day, result.session.slot)
        result = await advance_time(self.session_id, self.user, self.db)
        self.assertNotEqual((result.session.day, result.session.slot), previous_clock)
        await self.db.refresh(row)
        self.assertEqual(row.settlement, original)

    async def test_historical_unfinished_reports_do_not_block_a_settled_latest_turn(self):
        historical = []
        for status in ("partial", "failed", "pending", "running"):
            historical.append(await self.pending_reply(status))
        await self.pending_reply("done")
        expected = [copy.deepcopy(row.settlement) for row in historical]
        result = await move_to(self.session_id, RpgMoveIn(target=self.garden_name), self.user, self.db)
        self.assertEqual(result.session.location, self.garden_name)
        await advance_time(self.session_id, self.user, self.db)
        await self.world._turn("Next")
        self.assertEqual([row.settlement for row in (await self.messages())[:4]], expected)

    async def test_historical_edited_narration_still_requires_rollback(self):
        await self.pending_reply("stale")
        await self.pending_reply("done")
        for operation in (
            lambda: stream_turn(self.session_id, RpgTurnRequest(content="Next"), self.user, self.db),
            lambda: advance_time(self.session_id, self.user, self.db),
            lambda: move_to(self.session_id, RpgMoveIn(target=self.garden_name), self.user, self.db),
        ):
            with self.assertRaises(HTTPException) as caught:
                await operation()
            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn("回滚重玩", caught.exception.detail)

    async def test_new_user_message_does_not_hide_a_failed_latest_settlement(self):
        await self.pending_reply("done")
        await self.pending_reply("failed")
        self.db.add(RpgMessage(session_id=self.session_id, role="user", content="Interrupted request"))
        await self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            await stream_turn(self.session_id, RpgTurnRequest(content="Next"), self.user, self.db)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("结算失败", caught.exception.detail)

    async def test_failed_settlement_can_be_retried_before_continuing(self):
        row = await self.pending_reply("failed")
        data = {"checks": {domain: "unchanged" for domain in DOMAINS}}
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("model", "openai")), \
             patch.object(rpg_turn, "call_json", AsyncMock(return_value=(data, 1, 1))):
            reply = await settle_message(row.id, self.user, self.db)
        self.assertEqual(reply.settlement["status"], "done")
        await self.db.refresh(self.sess)
        await self.world._turn("Next")

    async def test_summoned_npc_is_in_both_message_snapshots(self):
        npc = self.world.npcs[0]
        action = RpgAction(module_id=self.module.id, name="Summon", needs_target=True,
                           target_anywhere=True, summons_target=True)
        self.db.add(action)
        await self.db.commit()
        await self.world._turn("Summon", action_id=action.id, target_npc=npc.name)
        self.assertTrue(all(npc.id in row.present for row in await self.messages()))

    async def test_action_clock_and_separate_costs_reach_prompt_stream_and_saved_report(self):
        self.module.time_slots = ["早", "晚"]
        self.module.stat_defs = [{"name": "energy", "min": 0, "max": 100, "reset_daily": True}]
        self.sess.slot = "晚"
        self.sess.stats = {"energy": 50}
        action = RpgAction(module_id=self.module.id, name="Work", effects={"energy": -30}, cost_slot=True)
        self.db.add(action)
        await self.db.commit()
        data = {"checks": {domain: "unchanged" for domain in DOMAINS}}
        events, messages = await self.world._turn("Work", data, action_id=action.id)
        engine_facts = next(payload["facts"] for event, payload in events if event == "engine_result")
        self.assertIn("行动效果：energy-30（50 → 20）", engine_facts)
        self.assertTrue(any("跨天恢复：energy+50（20 → 70" in fact for fact in engine_facts))
        self.assertIn("行动时间：第 1 天 · 晚 → 第 2 天 · 早", engine_facts)
        self.assertIn("本轮行动从「第 1 天 · 晚」开始，到「第 2 天 · 早」结束", messages[-1]["content"])
        report = next(payload["report"] for event, payload in events if event == "settlement")
        self.assertEqual(report["engine_facts"], engine_facts)
        self.assertEqual((await self.messages())[-1].settlement["engine_facts"], engine_facts)
        self.assertEqual(self.sess.stats["energy"], 70)

    async def test_budget_exhaustion_uses_the_same_action_time_contract(self):
        self.module.time_slots = ["早", "晚"]
        self.module.slot_budget = 3
        self.sess.slot = "早"
        self.sess.slot_actions = 2
        action = RpgAction(module_id=self.module.id, name="Work", effects={"energy": -10})
        self.db.add(action)
        await self.db.commit()
        data = {"checks": {domain: "unchanged" for domain in DOMAINS}}
        events, messages = await self.world._turn("Work", data, action_id=action.id)
        self.assertEqual(self.sess.slot, "晚")
        self.assertEqual(self.sess.slot_actions, 0)
        self.assertIn("本轮行动从「第 1 天 · 早」开始，到「第 1 天 · 晚」结束", messages[-1]["content"])
        engine_facts = next(payload["facts"] for event, payload in events if event == "engine_result")
        self.assertIn("行动时间：第 1 天 · 早 → 第 1 天 · 晚", engine_facts)

    async def test_daily_recovery_cancelling_cost_does_not_allow_a_second_charge(self):
        self.module.time_slots = ["早", "晚"]
        self.module.stat_defs = [{"name": "energy", "min": 0, "max": 100, "reset_daily": True}]
        self.sess.slot = "晚"
        self.sess.stats = {"energy": 70}
        action = RpgAction(module_id=self.module.id, name="Work", effects={"energy": -30}, cost_slot=True)
        self.db.add(action)
        await self.db.commit()
        data = {
            "checks": {**{domain: "unchanged" for domain in DOMAINS}, "stats": "changed"},
            "stats": {"energy": -30},
            "events": [{"kind": "state", "quote": "你来到药园，与园丁甲和园丁乙打了个招呼。",
                        "summary": "行动消耗精力", "domains": ["stats"]}],
        }
        await self.world._turn("Work", data, action_id=action.id)
        self.assertEqual(self.sess.stats["energy"], 70)

    async def test_relation_gate_without_target_uses_full_roster(self):
        npc = self.world.npcs[0]
        npc.relation_enabled = True
        self.module.relation_stat_defs = [{"name": "trust", "min": 0, "max": 100}]
        self.sess.npc_states = {str(npc.id): {"trust": 80}}
        action = RpgAction(module_id=self.module.id, name="Unlock", needs_target=False,
                           requires={"relations": [{"npc": npc.name, "stat": "trust", "op": ">=", "value": 50}]},
                           effects={"energy": 10})
        self.db.add(action)
        await self.db.commit()
        await rpg_turn._resolve_engine(self.session_id, action.id, "", "", "")
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.stats["energy"], 40)

    async def test_unowned_item_and_unlearned_skill_do_not_change_stats(self):
        self.db.add_all([
            RpgItem(module_id=self.module.id, name="tool", usable=True, consumable=False, effects={"energy": 10}),
            RpgSkill(module_id=self.module.id, name="magic", usable=True, cooldown=3, effects={"energy": 20}),
        ])
        await self.db.commit()
        await rpg_turn._resolve_engine(self.session_id, None, "tool", "", "")
        await rpg_turn._resolve_engine(self.session_id, None, "", "", "", skill_name="magic")
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.stats, {"energy": 30})
        self.assertEqual(self.sess.skills, [])
        self.assertEqual(self.sess.slot_actions, 0)

    async def test_insufficient_cost_rejects_entire_action(self):
        self.module.stat_defs += [{"name": "reward", "min": 0, "max": 100}]
        action = RpgAction(module_id=self.module.id, name="Train", effects={"energy": -50, "reward": 10})
        self.db.add(action)
        await self.db.commit()
        await rpg_turn._resolve_engine(self.session_id, action.id, "", "", "")
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.stats, {"energy": 30})
        self.assertEqual(self.sess.slot_actions, 0)

    async def test_bulk_item_use_requires_full_quantity_and_cost(self):
        self.sess.inventory = [{"name": "food", "qty": 2}]
        self.db.add(RpgItem(module_id=self.module.id, name="food", usable=True,
                            consumable=True, effects={"energy": -20}))
        await self.db.commit()
        for quantity in (2, 3):
            await rpg_turn._resolve_engine(self.session_id, None, "food", "", "", item_qty=quantity)
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.inventory, [{"name": "food", "qty": 2}])
        self.assertEqual(self.sess.stats, {"energy": 30})

    async def test_cost_slot_does_not_also_charge_next_slot(self):
        self.module.time_slots = ["morning", "noon", "night"]
        self.module.slot_budget = 1
        self.sess.slot = "morning"
        action = RpgAction(module_id=self.module.id, name="Work", cost_slot=True)
        self.db.add(action)
        await self.db.commit()
        await rpg_turn._resolve_engine(self.session_id, action.id, "", "", "")
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.slot, "noon")
        self.assertEqual(self.sess.slot_actions, 0)

    async def test_replay_keeps_movement_and_persists_full_item_request(self):
        self.sess.inventory = [{"name": "potion", "qty": 3}]
        self.db.add(RpgItem(module_id=self.module.id, name="potion", consumable=True,
                            usable=True, effects={"energy": 10}))
        await self.db.commit()
        await move_to(self.session_id, RpgMoveIn(target=self.world.garden.name), self.user, self.db)
        await self.world._turn("Use potion", item_name="potion", item_qty=2, mode="solo", attr="energy")
        player = next(row for row in await self.messages() if row.role == "user")
        request = copy.deepcopy(player.turn_request)
        self.assertEqual(request["item_qty"], 2)
        self.assertEqual(request["mode"], "solo")
        self.assertEqual(request["attr"], "energy")
        await rewind_before_message(player.id, self.user, self.db)
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.location, self.world.garden.name)
        self.assertEqual(self.sess.stats["energy"], 30)
        await self.world._turn("Use potion", **request)
        self.assertEqual(self.sess.stats["energy"], 50)
        self.assertEqual(self.sess.inventory, [{"name": "potion", "qty": 1}])

    async def test_stream_lock_rejects_second_turn_and_move_then_releases(self):
        async def fake_turn(*args, **kwargs):
            yield "token", "story"

        with patch.object(rpg_turn, "run_turn", fake_turn):
            response = await stream_turn(self.session_id, RpgTurnRequest(content="First"), self.user, self.db)
            async with self.world.sessions() as other:
                with self.assertRaises(HTTPException) as caught:
                    await stream_turn(self.session_id, RpgTurnRequest(content="Second"), self.user, other)
                self.assertEqual(caught.exception.status_code, 409)
                with self.assertRaises(HTTPException):
                    await move_to(self.session_id, RpgMoveIn(target=self.world.garden.name), self.user, other)
            async for _ in response.body_iterator:
                pass
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.operation_token, "")
        self.assertEqual(self.sess.turn_count, 1)

    async def test_expired_operation_can_recover_after_server_restart(self):
        self.sess.operation_token = "crashed"
        self.sess.operation_until = datetime.utcnow() - timedelta(seconds=1)
        await self.db.commit()
        await move_to(self.session_id, RpgMoveIn(target=self.world.garden.name), self.user, self.db)
        self.assertEqual(self.sess.location, self.world.garden.name)

    async def test_existing_database_gains_lease_and_replay_columns_without_losing_progress(self):
        async with self.world.engine.begin() as connection:
            for table, column in (
                ("rpg_sessions", "operation_token"), ("rpg_sessions", "operation_until"),
                ("rpg_messages", "turn_request"), ("rpg_messages", "before_save_id"),
            ):
                await connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
        with patch.object(database, "engine", self.world.engine):
            await database._run_migrations()
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.stats, {"energy": 30})
        self.assertEqual(self.sess.operation_token, "")
        self.assertIsNone(self.sess.operation_until)
        async with self.world.engine.connect() as connection:
            columns = (await connection.execute(text("PRAGMA table_info(rpg_messages)"))).all()
        self.assertTrue({"turn_request", "before_save_id"}.issubset({row[1] for row in columns}))

    async def test_orphaned_running_settlement_can_retry_after_lease_expires(self):
        row = await self.pending_reply("running")
        row.settlement = {**row.settlement, "started_at": datetime.utcnow().isoformat()}
        self.sess.operation_token = "crashed"
        self.sess.operation_until = datetime.utcnow() - timedelta(seconds=1)
        await self.db.commit()
        data = {"checks": {domain: "unchanged" for domain in DOMAINS}}
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("model", "openai")), \
             patch.object(rpg_turn, "call_json", AsyncMock(return_value=(data, 1, 1))):
            reply = await settle_message(row.id, self.user, self.db)
        self.assertEqual(reply.settlement["status"], "done")

    async def test_lock_covers_detached_settlement_after_stream_closes(self):
        completed = asyncio.Event()

        async def fake_turn(*args, **kwargs):
            retain_task(asyncio.create_task(completed.wait()))
            yield "token", "story"

        with patch.object(rpg_turn, "run_turn", fake_turn):
            response = await stream_turn(self.session_id, RpgTurnRequest(content="First"), self.user, self.db)
            await anext(response.body_iterator)
            closing = asyncio.create_task(response.body_iterator.aclose())
            await asyncio.sleep(0)
            try:
                async with self.world.sessions() as other:
                    with self.assertRaises(HTTPException):
                        await stream_turn(self.session_id, RpgTurnRequest(content="Second"), self.user, other)
            finally:
                completed.set()
                await asyncio.wait_for(closing, 2)
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.operation_token, "")

    async def test_stream_error_and_stop_save_partial_reply_before_unlock(self):
        for stop in (False, True):
            async def broken_stream(**kwargs):
                yield "Saved fragment."
                raise RuntimeError("connection reset")

            with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("model", "openai")), \
                 patch.object(rpg_turn.llm_client, "dispatch_chat_stream_with_usage", broken_stream):
                response = await stream_turn(self.session_id, RpgTurnRequest(content="Continue"), self.user, self.db)
                async for chunk in response.body_iterator:
                    event = json.loads(chunk.removeprefix("data: ").strip())["event"]
                    if stop and event == "token":
                        await response.body_iterator.aclose()
                        break
            messages = await self.messages()
            self.assertEqual(messages[-1].content, "Saved fragment.")
            self.assertEqual(messages[-1].settlement["status"], "pending")
            await self.db.refresh(self.sess)
            self.assertEqual(self.sess.operation_token, "")
            await rewind_before_message(messages[-2].id, self.user, self.db)


if __name__ == "__main__":
    unittest.main()
