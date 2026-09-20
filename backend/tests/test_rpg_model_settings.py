import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.agents import rpg_turn
from app.api.routes import rpg as routes
from app.database import Base
from app.models import llm_usage, sensitive_word, text_replace_backup
from app.models import (
    novel, chapter, character, memory, model_library, writer_preset, prompt_rule,
    world_entity, location, api_provider, novel_note, faction, technique, volume,
    worldview_change, world_rule, story_thread, glossary_entry, user, tavern, rpg,
)
from app.models.rpg import RpgMessage, RpgModule, RpgNpc, RpgSession
from app.schemas.rpg import RpgDiscoveryApplyIn, RpgModuleCreate, RpgModuleUpdate
from app.services.rpg_suggestions import SuggestSources


NEW_FIELDS = (
    "settlement_model_ref", "adjudication_model_ref", "suggestion_model_ref",
    "activity_model_ref", "offscreen_model_ref", "discovery_model_ref",
)


class ModelSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.store = self.sessions()
        self.user = SimpleNamespace(id=1)
        self.module = RpgModule(
            user_id=1, name="Model settings", model_ref="10", fast_model_ref="20",
            summary_model_ref="30", context_turns=1, offscreen_brief=True,
            **{field: str(index + 40) for index, field in enumerate(NEW_FIELDS)},
        )
        self.store.add(self.module)
        await self.store.flush()
        self.npc = RpgNpc(module_id=self.module.id, name="Guard", location="Tower", ai_scheduled=True)
        self.store.add(self.npc)
        await self.store.flush()
        self.session = RpgSession(
            module_id=self.module.id, char_name="Player", location="Garden",
            npc_states={str(self.npc.id): {"met": True}},
            discoveries=[{"id": "found", "kind": "place", "name": "Cave"}],
        )
        self.store.add(self.session)
        await self.store.flush()
        self.history = [
            RpgMessage(session_id=self.session.id, role="user", content=f"Explore {index}")
            for index in range(6)
        ]
        self.store.add_all(self.history)
        await self.store.commit()
        self.session_patch = patch.object(rpg_turn, "AsyncSessionLocal", self.sessions)
        self.session_patch.start()

    async def asyncTearDown(self):
        self.session_patch.stop()
        await self.store.close()
        await self.engine.dispose()

    async def test_model_choices_survive_create_update_read_and_clear(self):
        values = {field: str(index + 100) for index, field in enumerate(NEW_FIELDS)}
        created = await routes.create_module(RpgModuleCreate(name="New", **values), self.user, self.store)
        for field, value in values.items():
            self.assertEqual(getattr(created, field), value)
        updated = {field: str(index + 200) for index, field in enumerate(NEW_FIELDS)}
        await routes.update_module(created.id, RpgModuleUpdate(**updated), self.user, self.store)
        result = await routes.get_module(created.id, self.user, self.store)
        for field, value in updated.items():
            self.assertEqual(getattr(result, field), value)
        await routes.update_module(created.id, RpgModuleUpdate(**dict.fromkeys(NEW_FIELDS, "")), self.user, self.store)
        result = await routes.get_module(created.id, self.user, self.store)
        for field in NEW_FIELDS:
            self.assertEqual(getattr(result, field), "")

    async def test_calls_use_independent_models_and_legacy_fallbacks(self):
        async def adjudicate():
            await rpg_turn.adjudicate(self.module, self.session, "Explore", "")

        async def suggest():
            await rpg_turn.suggest_actions(self.module, self.session, self.history, None, SuggestSources())

        async def activity():
            await rpg_turn.idle_npc_activities(self.session.id, set())

        async def offscreen():
            await rpg_turn.offscreen_brief(self.session.id)

        for field, invoke in (
            ("adjudication_model_ref", adjudicate), ("suggestion_model_ref", suggest),
            ("activity_model_ref", activity), ("offscreen_model_ref", offscreen),
        ):
            for chosen in (getattr(self.module, field), ""):
                with self.subTest(field=field, chosen=chosen):
                    setattr(self.module, field, chosen)
                    await self.store.commit()
                    with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("chosen", "openai")) as resolve, \
                         patch.object(rpg_turn.llm_client, "dispatch_chat_complete", AsyncMock(return_value="")), \
                         patch.object(rpg_turn, "call_json", AsyncMock(return_value=({}, 1, 1))):
                        await invoke()
                    resolve.assert_called_once_with("memory", chosen or "20")

    async def test_discovery_request_override_then_dedicated_then_narration_then_default(self):
        for request, dedicated, narrator, expected in (
            ("99", "45", "10", "99"), ("", "45", "10", "45"),
            ("", "", "10", "10"), ("", "", "", ""),
        ):
            with self.subTest(expected=expected):
                await self.store.refresh(self.session)
                self.module.discovery_model_ref = dedicated
                self.module.model_ref = narrator
                await self.store.commit()
                with patch.object(routes.rpg_discover, "flesh_out", AsyncMock(side_effect=ValueError("stop"))) as flesh:
                    with self.assertRaises(HTTPException) as raised:
                        await routes.apply_discoveries(
                            self.session.id, RpgDiscoveryApplyIn(ids=["found"], model=request), self.user, self.store,
                        )
                self.assertEqual(raised.exception.status_code, 400)
                self.assertEqual(flesh.call_args.args[4], expected)

    async def test_migration_keeps_old_choices_and_defaults_new_fields_to_empty(self):
        async with self.engine.begin() as connection:
            for field in NEW_FIELDS:
                await connection.execute(text(f"ALTER TABLE rpg_modules DROP COLUMN {field}"))
        with patch.object(database, "engine", self.engine):
            await database._run_migrations()
            await database._run_migrations()
        await self.store.refresh(self.module)
        self.assertEqual(self.module.model_ref, "10")
        self.assertEqual(self.module.fast_model_ref, "20")
        for field in NEW_FIELDS:
            self.assertEqual(getattr(self.module, field), "")
