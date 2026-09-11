import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from jinja2 import TemplateError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import tavern_card_agent
from app.api.routes.tavern_prompts import PromptUpdate, list_prompts, reset_prompt, update_prompt
from app.models.user import User
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, prompt_rule, tavern as _tavern
from app.services import tavern_prompts
from app.services.auth import current_user_var


class TavernPromptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.owner = User(username="owner", password_hash="unused")
        self.other = User(username="other", password_hash="unused")
        self.db.add_all([self.owner, self.other])
        await self.db.commit()
        self.token = current_user_var.set(self.owner)

    async def asyncTearDown(self):
        current_user_var.reset(self.token)
        await self.db.close()
        await self.engine.dispose()

    async def test_defaults_validate_and_list(self):
        prompts = await list_prompts(self.owner)
        self.assertEqual(len(prompts), 5)
        for prompt in prompts:
            self.assertFalse(prompt.customized)
            self.assertEqual(prompt.content, prompt.default_content)
            tavern_prompts.validate(prompt.name, prompt.content)

    async def test_persistence_isolation_and_reset(self):
        name = "tavern_roleplay.jinja2"
        saved = await update_prompt(name, PromptUpdate(content="你好 {{ char_name }}"), self.owner, self.db)
        self.assertTrue(saved.customized)
        async with self.sessions() as fresh_db:
            fresh_owner = await fresh_db.get(User, self.owner.id)
            self.assertEqual(fresh_owner.tavern_prompts[name], "你好 {{ char_name }}")
        self.assertEqual(tavern_prompts.render(name, char_name="林越"), "你好 林越")
        current_user_var.set(self.other)
        self.assertNotIn(name, self.other.tavern_prompts)
        self.assertIn("怎么演", tavern_prompts.render(name, char_name="林越", persona="玩家"))
        self.assertTrue(all(not prompt.customized for prompt in await list_prompts(self.other)))
        current_user_var.set(self.owner)
        restored = await reset_prompt(name, self.owner, self.db)
        self.assertFalse(restored.customized)
        self.assertEqual(restored.content, restored.default_content)

    async def test_invalid_templates_do_not_persist(self):
        for content in (" ", "{% if %}", "{{ unknown }}", "{{ char_name.__class__.__mro__ }}", "{% include 'writer.jinja2' %}"):
            with self.subTest(content=content):
                with self.assertRaises(HTTPException) as raised:
                    await update_prompt("tavern_roleplay.jinja2", PromptUpdate(content=content), self.owner, self.db)
                self.assertEqual(raised.exception.status_code, 400)
                self.assertEqual(self.owner.tavern_prompts, {})

    async def test_unknown_names_rejected(self):
        for name in ("writer.jinja2", "../config.py"):
            with self.assertRaises(HTTPException) as raised:
                await update_prompt(name, PromptUpdate(content="test"), self.owner, self.db)
            self.assertEqual(raised.exception.status_code, 404)
            with self.assertRaises(HTTPException):
                await reset_prompt(name, self.owner, self.db)

    async def test_card_assistance_uses_saved_prompt(self):
        await update_prompt("tavern_card_note.jinja2", PromptUpdate(content="为 {{ char_name }} 写简介：{{ personality }}"), self.owner, self.db)
        with patch.object(tavern_card_agent.llm_client, "get_agent_client", return_value=("test", "openai")), patch.object(
            tavern_card_agent.llm_client, "dispatch_chat_complete", new_callable=AsyncMock, return_value="简介"
        ) as complete:
            result = await tavern_card_agent.assist_creator_note("林越", "温和", "详细设定", "test")
        self.assertEqual(result, "简介")
        self.assertEqual(complete.call_args.kwargs["messages"][0]["content"], "为 林越 写简介：温和")

    async def test_missing_runtime_variable_fails_explicitly(self):
        self.owner.tavern_prompts = {"tavern_roleplay.jinja2": "{{ persona }}"}
        with self.assertRaises(TemplateError):
            tavern_prompts.render("tavern_roleplay.jinja2", char_name="林越")
