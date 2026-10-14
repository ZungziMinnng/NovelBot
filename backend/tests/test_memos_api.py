"""主页备忘录：小说侧和游戏侧分开、按用户隔离、空内容不收。直接调路由函数，不起 HTTP。"""
import types
import unittest

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 路由链路会拉进 Novel，单独跑这个文件时它的关系目标还没注册，先全量导入
from app.models import novel, chapter, character, memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, user  # noqa: F401
from app.api.routes import memos as routes
from app.models.memo import Memo


class MemoRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Memo.__table__.create)
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.alice = types.SimpleNamespace(id=1)
        self.bob = types.SimpleNamespace(id=2)

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _create(self, user, scope="novel", content="点子"):
        return await routes.create_memo(routes.MemoCreate(scope=scope, content=content), user, self.db)

    async def test_scopes_and_users_are_separate(self):
        await self._create(self.alice, "novel", "  主角其实是反派  ")
        await self._create(self.alice, "game", "做个赛马模组")
        await self._create(self.bob, "novel", "别人的")
        novel = await routes.list_memos("novel", self.alice, self.db)
        game = await routes.list_memos("game", self.alice, self.db)
        self.assertEqual([m["content"] for m in novel], ["主角其实是反派"])
        self.assertEqual([m["content"] for m in game], ["做个赛马模组"])

    async def test_rejects_blank(self):
        with self.assertRaises(HTTPException) as raised:
            await self._create(self.alice, content="   ")
        self.assertEqual(raised.exception.status_code, 400)

    async def test_cannot_touch_other_users_memo(self):
        memo = await self._create(self.alice)
        with self.assertRaises(HTTPException) as raised:
            await routes.update_memo(memo["id"], routes.MemoUpdate(content="改"), self.bob, self.db)
        self.assertEqual(raised.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            await routes.delete_memo(memo["id"], self.bob, self.db)
        await routes.update_memo(memo["id"], routes.MemoUpdate(content="改好了"), self.alice, self.db)
        await routes.delete_memo(memo["id"], self.alice, self.db)
        self.assertEqual(await routes.list_memos("novel", self.alice, self.db), [])


if __name__ == "__main__":
    unittest.main()
