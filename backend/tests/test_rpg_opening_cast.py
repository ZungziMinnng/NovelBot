import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.api.routes import rpg as routes
from app.database import Base
from app.models import (
    novel, chapter, character, memory, model_library, writer_preset, prompt_rule,
    world_entity, location, api_provider, novel_note, faction, technique, volume,
    worldview_change, world_rule, story_thread, glossary_entry, user, tavern, rpg,
    llm_usage, sensitive_word, text_replace_backup,
)
from app.models.rpg import RpgMessage, RpgModule, RpgNpc, RpgSession
from app.schemas.rpg import RpgModuleCreate, RpgModuleUpdate, RpgSessionCreate
from app.services.rpg_context import build_rpg_messages, here_npcs, npc_place
from app.services.rpg_state import advance_slot, apply_npc_place, spend_slot_action


class OpeningCastTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.store = self.sessions()
        self.user = SimpleNamespace(id=1)
        created = await routes.create_module(RpgModuleCreate(
            name="Opening cast", default_location="Market", opening_scene="Shopping together.",
            time_slots=["Morning", "Evening"], slot_budget=1,
        ), self.user, self.store)
        self.module = await self.store.get(RpgModule, created.id)
        self.wife = RpgNpc(module_id=created.id, name="Wife", location="Bedroom",
                           slot_locations={"Morning": "Kitchen", "Evening": "Bedroom"})
        self.vendor = RpgNpc(module_id=created.id, name="Vendor", location="Market",
                             slot_locations={"Evening": "Home"})
        self.store.add_all([self.wife, self.vendor])
        await self.store.commit()
        updated = await routes.update_module(
            created.id, RpgModuleUpdate(opening_npc_ids=[self.wife.id]), self.user, self.store,
        )
        self.assertEqual(updated.opening_npc_ids, [self.wife.id])

    async def asyncTearDown(self):
        await self.store.close()
        await self.engine.dispose()

    async def open(self, **values):
        return await routes.create_session(
            self.module.id, RpgSessionCreate(char_name="Player", **values), self.user, self.store,
        )

    async def test_opening_overrides_schedule_without_changing_home_or_following(self):
        session = await self.open()
        self.assertEqual(session.npc_places, {str(self.wife.id): "Market"})
        self.assertEqual(session.npc_followers, [])
        message = (await self.store.execute(select(RpgMessage).where(
            RpgMessage.session_id == session.id,
        ))).scalar_one()
        self.assertEqual(set(message.present), {self.wife.id, self.vendor.id})
        _, diagnostic = await build_rpg_messages(self.store, self.module, session, [message], "Hello")
        self.assertIn(self.wife.id, {entry["id"] for entry in diagnostic["npcs_here"]})
        self.assertEqual({npc.id for npc in here_npcs(
            [self.wife, self.vendor], session.location, session.slot, session.npc_places,
        )}, {self.wife.id, self.vendor.id})
        await self.store.refresh(self.wife)
        self.assertEqual(self.wife.location, "Bedroom")
        self.assertEqual(self.wife.slot_locations, {"Morning": "Kitchen", "Evening": "Bedroom"})

    async def test_selection_only_affects_new_sessions_and_clear_restores_routine(self):
        first = await self.open()
        await routes.update_module(
            self.module.id, RpgModuleUpdate(opening_npc_ids=[]), self.user, self.store,
        )
        second = await self.open()
        await self.store.refresh(first)
        self.assertEqual(first.npc_places, {str(self.wife.id): "Market"})
        self.assertEqual(second.npc_places, {})
        self.assertEqual(npc_place(self.wife, second.slot, second.npc_places), "Kitchen")

    async def test_independent_opening_locations_control_presence_and_prompt(self):
        placements = {str(self.wife.id): "Restroom", str(self.vendor.id): "Stall"}
        updated = await routes.update_module(
            self.module.id, RpgModuleUpdate(opening_npc_locations=placements), self.user, self.store,
        )
        self.assertEqual(updated.opening_npc_locations, placements)
        loaded = await routes.get_module(self.module.id, self.user, self.store)
        self.assertEqual(loaded.opening_npc_locations, placements)
        session = await self.open(location="Stall")
        self.assertEqual(session.location, "Stall")
        self.assertEqual(session.npc_places, placements)
        message = (await self.store.execute(select(RpgMessage).where(
            RpgMessage.session_id == session.id,
        ))).scalar_one()
        self.assertEqual(message.present, [self.vendor.id])
        _, diagnostic = await build_rpg_messages(self.store, self.module, session, [message], "Hello")
        self.assertEqual({entry["id"] for entry in diagnostic["npcs_here"]}, {self.vendor.id})
        self.assertEqual(self.wife.location, "Bedroom")
        self.assertEqual(self.wife.slot_locations["Morning"], "Kitchen")
        self.assertEqual(session.npc_followers, [])

    async def test_fixed_opening_location_does_not_require_player_start_or_opening_text(self):
        self.module.opening_npc_locations = {str(self.wife.id): " Restroom "}
        self.module.opening_scene = ""
        await self.store.commit()
        for start in ("", "Park"):
            with self.subTest(start=start):
                session = await self.open(location=start)
                self.assertEqual(session.npc_places, {str(self.wife.id): "Restroom"})

    async def test_blank_explicit_location_falls_back_to_routine_even_with_legacy_selection(self):
        self.module.opening_npc_locations = {str(self.wife.id): "  "}
        await self.store.commit()
        session = await self.open()
        self.assertEqual(session.npc_places, {})
        self.assertEqual(npc_place(self.wife, session.slot, session.npc_places), "Kitchen")

    async def test_removing_custom_opening_only_changes_future_sessions(self):
        await routes.update_module(self.module.id, RpgModuleUpdate(
            opening_npc_ids=[], opening_npc_locations={str(self.wife.id): "Restroom"},
        ), self.user, self.store)
        first = await self.open()
        await routes.update_module(self.module.id, RpgModuleUpdate(
            opening_npc_locations={},
        ), self.user, self.store)
        second = await self.open()
        await self.store.refresh(first)
        self.assertEqual(first.npc_places, {str(self.wife.id): "Restroom"})
        self.assertEqual(second.npc_places, {})

    async def test_custom_start_and_blank_opening_still_initialize_positions(self):
        self.module.opening_scene = ""
        await self.store.commit()
        session = await self.open(location="Park")
        self.assertEqual(session.npc_places, {str(self.wife.id): "Park"})
        blank = await self.open(location="")
        self.assertEqual(blank.npc_places, {})

    async def test_foreign_deleted_and_protagonist_ids_cannot_join_opening(self):
        other = RpgModule(user_id=2, name="Other")
        self.store.add(other)
        await self.store.flush()
        stranger = RpgNpc(module_id=other.id, name="Stranger")
        player = RpgNpc(module_id=self.module.id, name="Player card", role="protagonist")
        self.store.add_all([stranger, player])
        await self.store.flush()
        self.module.opening_npc_ids = [self.wife.id, self.wife.id, stranger.id, player.id, 999999]
        self.module.opening_npc_locations = {
            str(stranger.id): "Restroom", str(player.id): "Restroom", "999999": "Restroom",
        }
        await self.store.commit()
        session = await self.open()
        self.assertEqual(session.npc_places, {str(self.wife.id): "Market"})

    async def test_manual_time_advance_keeps_opening_and_scheduled_present_characters(self):
        session = await self.open()
        result = await routes.advance_time(session.id, self.user, self.store)
        self.assertEqual(result.session.slot, "Evening")
        self.assertEqual(result.session.npc_places, {
            str(self.wife.id): "Market", str(self.vendor.id): "Market",
        })
        await routes.advance_time(session.id, self.user, self.store)
        self.assertEqual(session.day, 2)
        self.assertEqual(npc_place(self.wife, session.slot, session.npc_places), "Market")

    async def test_budget_advance_keeps_present_cast_and_departure_restores_routine(self):
        session = await self.open()
        cast = [self.wife, self.vendor]
        spend_slot_action(self.module, session, cast)
        self.assertEqual(npc_place(self.wife, session.slot, session.npc_places), "Market")
        session.location = "Park"
        advance_slot(self.module, session, cast)
        self.assertEqual(session.npc_places, {})
        self.assertEqual(npc_place(self.wife, session.slot, session.npc_places), "Kitchen")

    async def test_explicit_departure_takes_effect_before_the_next_slot(self):
        session = await self.open()
        apply_npc_place(session, self.wife.id, "Bedroom")
        self.assertNotIn(self.wife, here_npcs(
            [self.wife], session.location, session.slot, session.npc_places,
        ))
        advance_slot(self.module, session, [self.wife])
        self.assertEqual(npc_place(self.wife, session.slot, session.npc_places), "Bedroom")

    async def test_follower_stays_mobile_after_time_advance(self):
        session = await self.open()
        session.npc_followers = [self.wife.id]
        advance_slot(self.module, session, [self.wife])
        self.assertNotIn(str(self.wife.id), session.npc_places)
        session.location = "Park"
        self.assertEqual(npc_place(self.wife, session.slot, session.npc_places,
                                   session.npc_followers, session.location), "Park")

    async def test_migration_keeps_existing_home_and_start(self):
        async with self.engine.begin() as connection:
            await connection.execute(text("ALTER TABLE rpg_modules DROP COLUMN opening_npc_ids"))
        with patch.object(database, "engine", self.engine):
            await database._run_migrations()
            await database._run_migrations()
        await self.store.refresh(self.module)
        await self.store.refresh(self.wife)
        self.assertEqual(self.module.opening_npc_ids, [])
        self.assertEqual(self.module.default_location, "Market")
        self.assertEqual(self.wife.location, "Bedroom")

    async def test_restore_recovers_session_position_without_reapplying_module_opening(self):
        session = await self.open()
        saved = await routes._take_save(self.store, session, "manual", "Opening")
        await self.store.commit()
        apply_npc_place(session, self.wife.id, "Bedroom")
        self.module.opening_npc_ids = []
        self.module.opening_npc_locations = {str(self.wife.id): "Restroom"}
        await self.store.commit()
        await routes.restore_save(saved.id, self.user, self.store)
        await self.store.refresh(session)
        self.assertEqual(session.npc_places, {str(self.wife.id): "Market"})
        self.assertEqual(self.module.opening_npc_ids, [])
        self.assertEqual(self.module.opening_npc_locations, {str(self.wife.id): "Restroom"})

    async def test_location_migration_preserves_legacy_same_start_selection(self):
        async with self.engine.begin() as connection:
            await connection.execute(text("ALTER TABLE rpg_modules DROP COLUMN opening_npc_locations"))
        with patch.object(database, "engine", self.engine):
            await database._run_migrations()
            await database._run_migrations()
        await self.store.refresh(self.module)
        self.assertEqual(self.module.opening_npc_locations, {})
        self.assertEqual(self.module.opening_npc_ids, [self.wife.id])
        session = await self.open()
        self.assertEqual(session.npc_places, {str(self.wife.id): "Market"})
