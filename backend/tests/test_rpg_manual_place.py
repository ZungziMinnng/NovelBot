"""剧情里框选一个名字，补全成地点建进模组：名字必须真在那段剧情里、不能和已有地点重名，
依据从库里的原文取，结算也报过的同名待办一并划掉。"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import rpg as routes
from app.database import Base
from app.models import (  # noqa: F401
    novel, chapter, character, memory, model_library, writer_preset, prompt_rule,
    world_entity, location, api_provider, novel_note, faction, technique, volume,
    worldview_change, world_rule, story_thread, glossary_entry, user, tavern, rpg,
    llm_usage, sensitive_word, text_replace_backup,
)
from app.models.rpg import RpgLocation, RpgMessage, RpgModule, RpgSession
from app.schemas.rpg import RpgDiscoveryApplyIn, RpgManualPick

NARRATION = "你推开木门，眼前是一条潮湿的后巷，尽头堆着几只破酒桶，巷子另一头通向镇口。"


class ManualPlaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.store = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.user = SimpleNamespace(id=1)
        self.module = RpgModule(user_id=1, name="镇子", model_ref="10")
        self.store.add(self.module)
        await self.store.flush()
        self.store.add(RpgLocation(module_id=self.module.id, name="镇口", description="", connections=[]))
        self.session = RpgSession(
            module_id=self.module.id, char_name="你", location="镇口",
            discoveries=[
                {"id": "dup", "kind": "place", "name": "后巷", "hint": "", "message_id": 0},
                {"id": "other", "kind": "npc", "name": "老周", "hint": "", "message_id": 0},
            ],
        )
        self.store.add(self.session)
        await self.store.flush()
        self.message = RpgMessage(session_id=self.session.id, role="assistant", content=NARRATION)
        self.store.add(self.message)
        await self.store.commit()

    async def asyncTearDown(self):
        await self.store.close()
        await self.engine.dispose()

    async def _apply(self, name, message_id=None, drafted=None):
        flesh = AsyncMock(return_value=drafted or {
            "npcs": [], "items": [], "skills": [], "tasks": [], "dropped": [],
            "locations": [{"name": name, "description": "潮湿，堆着酒桶", "parent_name": "", "connections": ["镇口"]}],
        })
        with patch.object(routes.rpg_discover, "flesh_out", flesh):
            out = await routes.apply_discoveries(
                self.session.id,
                RpgDiscoveryApplyIn(ids=[], manual_place=RpgManualPick(name=name, message_id=message_id or self.message.id)),
                self.user, self.store,
            )
        return out, flesh

    async def test_builds_place_from_selected_name_with_context(self):
        out, flesh = await self._apply("后巷")
        picked, narration = flesh.call_args.args[1], flesh.call_args.args[2]
        self.assertEqual([(p["kind"], p["name"]) for p in picked], [("place", "后巷")])
        # 依据是那段原文里名字前后的字，不是前端传的
        self.assertIn("潮湿的后巷", picked[0]["hint"])
        self.assertEqual(narration, NARRATION)
        self.assertEqual([row.name for row in out.locations], ["后巷"])
        self.assertEqual(out.locations[0].connections, ["镇口"])
        # 结算也报过的同名地点待办划掉了，别的留着
        self.assertEqual([e["id"] for e in out.remaining], ["other"])

    async def test_rejects_name_not_in_message(self):
        with self.assertRaises(HTTPException) as raised:
            await self._apply("月球基地")
        self.assertEqual(raised.exception.status_code, 400)

    async def test_rejects_existing_place(self):
        with self.assertRaises(HTTPException) as raised:
            await self._apply("镇口")
        self.assertEqual(raised.exception.status_code, 400)
        rows = (await self.store.execute(select(RpgLocation))).scalars().all()
        self.assertEqual(len(rows), 1)

    async def test_rejects_message_from_other_session(self):
        other = RpgSession(module_id=self.module.id, char_name="你", location="镇口")
        self.store.add(other)
        await self.store.flush()
        foreign = RpgMessage(session_id=other.id, role="assistant", content=NARRATION)
        self.store.add(foreign)
        await self.store.commit()
        with self.assertRaises(HTTPException) as raised:
            await self._apply("后巷", message_id=foreign.id)
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
