import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.api.routes.rpg import stream_turn
from app.database import Base
from app.models import novel, chapter, character, memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, user, tavern, rpg
from app.models.rpg import RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgSave, RpgSession
from app.schemas.rpg import RpgTurnRequest


class MovementTargetTests(unittest.TestCase):
    def setUp(self):
        self.locations = [
            RpgLocation(name="灵药园柴房"), RpgLocation(name="灵药园"),
            RpgLocation(name="灵药园"),
        ]

    def test_explicit_commands_resolve_to_the_exact_place(self):
        for content in ("灵药园", "前往灵药园", "我去灵药园", "我要进入灵药园。", "走到「灵药园」！"):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, self.locations), "灵药园")
        self.assertEqual(rpg_turn.movement_target("回到灵药园柴房", self.locations), "灵药园柴房")

    def test_mentions_questions_negation_and_unknown_places_do_not_move(self):
        for content in (
            "灵药园里有谁", "去灵药园吗？", "灵药园？", "我不去灵药园", "不要前往灵药园",
            "她前往灵药园", "我问他灵药园在哪里", "等天亮再去灵药园", "前往灵药园并回到柴房",
            "去灵药园后院", "前往不存在的地方",
        ):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, self.locations), "")


class MovementTurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = SimpleNamespace(id=1)
        module = RpgModule(user_id=1, name="移动测试", check_mode="never")
        self.db.add(module)
        await self.db.flush()
        self.garden = RpgLocation(module_id=module.id, name="灵药园", description="两位园丁正在照料药草。")
        self.npcs = [
            RpgNpc(module_id=module.id, name="园丁甲", location="灵药园", persona="沉稳"),
            RpgNpc(module_id=module.id, name="园丁乙", location="灵药园", persona="热情"),
        ]
        self.db.add_all([
            self.garden, *self.npcs,
            RpgLocation(module_id=module.id, name="灵药园柴房", connections=["灵药园"]),
        ])
        self.sess = RpgSession(
            module_id=module.id, char_name="旅人", location="灵药园柴房", slot="清晨",
            stats={"精力": 50}, status="alive", turn_count=0,
        )
        self.db.add(self.sess)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _turn(self, content, delta=None, **kwargs):
        captured = []

        async def stream(messages, **options):
            captured.extend(messages)
            yield "你来到药园，与园丁甲和园丁乙打了个招呼。"
            yield ("usage", 1, 1)

        with (
            patch.object(rpg_turn, "AsyncSessionLocal", self.sessions),
            patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("model", "openai")),
            patch.object(rpg_turn.llm_client, "dispatch_chat_stream_with_usage", stream),
            patch.object(rpg_turn, "call_json", AsyncMock(return_value=(delta or {}, 1, 1))),
            patch.object(rpg_turn, "_maybe_summarize", AsyncMock()),
            patch.object(rpg_turn, "idle_npc_activities", AsyncMock()),
        ):
            response = await stream_turn(
                self.sess.id, RpgTurnRequest(content=content, **kwargs), self.user, self.db,
            )
            events = []
            async for chunk in response.body_iterator:
                text = chunk.decode() if isinstance(chunk, bytes) else chunk
                payload = json.loads(text.removeprefix("data: ").strip())
                events.append((payload["event"], payload["data"]))
        self.assertFalse([data for event, data in events if event == "error"])
        await self.db.refresh(self.sess)
        return events, captured

    async def test_free_movement_updates_state_context_and_both_message_snapshots(self):
        events, messages = await self._turn("前往灵药园")
        self.assertEqual(self.sess.location, "灵药园")
        self.assertIn("灵药园", self.sess.visited)
        first_state = next(data for event, data in events if event == "state")
        self.assertEqual(first_state["location"], "灵药园")
        first_state_index = next(index for index, (event, _) in enumerate(events) if event == "state")
        first_token_index = next(index for index, (event, _) in enumerate(events) if event == "token")
        self.assertLess(first_state_index, first_token_index)
        meta = next(data for event, data in events if event == "meta" and "npcs_here" in data)
        expected_ids = {npc.id for npc in self.npcs}
        self.assertEqual({npc["id"] for npc in meta["npcs_here"]}, expected_ids)
        self.assertTrue(all(self.sess.npc_states[str(npc.id)]["met"] for npc in self.npcs))
        self.assertIn("园丁甲", messages[0]["content"])
        self.assertIn("园丁乙", messages[0]["content"])
        rows = list((await self.db.execute(
            select(RpgMessage).where(RpgMessage.session_id == self.sess.id).order_by(RpgMessage.id)
        )).scalars())
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row.location, "灵药园")
            self.assertEqual(set(row.present), expected_ids)
        saved = (await self.db.execute(select(RpgSave).where(RpgSave.session_id == self.sess.id))).scalars().first()
        self.assertEqual(saved.state["location"], "灵药园柴房")

    async def test_a_bare_place_name_moves_without_a_location_delta(self):
        await self._turn("灵药园")
        self.assertEqual(self.sess.location, "灵药园")

    async def test_settlement_cannot_undo_the_engine_movement(self):
        await self._turn("前往灵药园", {"location": "灵药园柴房"})
        self.assertEqual(self.sess.location, "灵药园")

    async def test_enter_requirements_are_enforced_even_if_settlement_claims_arrival(self):
        self.garden.enter_requires = {"stats": {"精力": {"op": ">=", "value": 200}}}
        await self.db.commit()
        events, _ = await self._turn("前往灵药园", {"location": "灵药园"})
        self.assertEqual(self.sess.location, "灵药园柴房")
        meta = next(data for event, data in events if event == "meta" and "npcs_here" in data)
        self.assertEqual(meta["npcs_here"], [])

    async def test_a_place_mentioned_in_conversation_does_not_move(self):
        await self._turn("灵药园里有谁")
        self.assertEqual(self.sess.location, "灵药园柴房")

    async def test_explicit_move_field_uses_the_same_destination_snapshots(self):
        await self._turn("出发", move_to="灵药园")
        rows = list((await self.db.execute(select(RpgMessage))).scalars())
        self.assertTrue(all(row.location == "灵药园" for row in rows))
