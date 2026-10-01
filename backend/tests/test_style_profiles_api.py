"""文风库路由：导入只出预览不入库、按用户隔离、删库不影响已取用处（取用本来就是拷贝）。

直接调路由函数，不起 HTTP。模型调用全 patch 掉，文本全是构造的。
"""
import io
import types
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 路由链路会拉进 Novel，单独跑这个文件时它的关系目标还没注册，先全量导入
from app.models import novel, chapter, character, memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, user  # noqa: F401
from app.api.routes import style_profiles as routes
from app.models.style_profile import StyleProfile
from app.schemas.style_profile import StyleAdaptIn, StyleProfileCreate, StyleProfileUpdate


def _upload(text: str, name: str = "测试书.txt", encoding: str = "gbk") -> UploadFile:
    return UploadFile(file=io.BytesIO(text.encode(encoding)), filename=name)


def _book() -> str:
    body = "\n".join("他走过长街，风从巷口灌进来。“你来了。”她说。" * 3 for _ in range(10))
    return "\n".join(f"第{i}章 标题\n{body}" for i in range(1, 6))


class StyleProfileRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(StyleProfile.__table__.create)
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.alice = types.SimpleNamespace(id=1)
        self.bob = types.SimpleNamespace(id=2)

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _create(self, user, name="甲"):
        data = StyleProfileCreate(
            name=name, style_desc="短句",
            scenes=[{"scene_type": "对话", "text": "段落。", "speakers": ["林轩"]}],
            characters=[{"name": "林轩", "role": "主角"}],
        )
        return await routes.create_profile(data, user, self.db)

    async def test_import_returns_preview_without_saving(self):
        fake = AsyncMock(return_value={"style_desc": "说明", "characters": [], "scenes": []})
        with patch("app.agents.style_agent.analyze", new=fake):
            preview = await routes.import_profile(
                self.alice, _upload(_book()), categories=["对话"], model="7"
            )
        self.assertEqual(preview.name, "测试书")
        self.assertEqual(preview.style_desc, "说明")
        self.assertIn("dialogue_ratio", preview.stats)
        # GBK 解码成功才会有段落喂给模型
        self.assertTrue(fake.await_args.args[0])
        self.assertTrue(fake.await_args.args[1])  # 全书的块，粗筛用
        self.assertEqual(fake.await_args.args[2], ["对话"])
        self.assertEqual(fake.await_args.args[4], "7")  # 用户选的模型透传下去
        rows = (await self.db.execute(select(StyleProfile))).scalars().all()
        self.assertEqual(rows, [])

    async def test_import_cleans_categories(self):
        fake = AsyncMock(return_value={"style_desc": "", "characters": [], "scenes": []})
        with patch("app.agents.style_agent.analyze", new=fake):
            await routes.import_profile(
                self.alice, _upload(_book()), categories=["  对话 ", "对话", "", "吃饭"], model=""
            )
        self.assertEqual(fake.await_args.args[2], ["对话", "吃饭"])

    async def test_import_without_category_400(self):
        fake = AsyncMock()
        with patch("app.agents.style_agent.analyze", new=fake):
            with self.assertRaises(HTTPException) as ctx:
                await routes.import_profile(self.alice, _upload(_book()), categories=[" "])
        self.assertEqual(ctx.exception.status_code, 400)
        fake.assert_not_called()

    async def test_import_bad_model_400(self):
        # 模型不属于当前用户时 resolve_model_ref 抛 ValueError，不能漏成 500
        fake = AsyncMock(side_effect=ValueError("模型引用无效或不属于当前用户"))
        with patch("app.agents.style_agent.analyze", new=fake):
            with self.assertRaises(HTTPException) as ctx:
                await routes.import_profile(
                    self.alice, _upload(_book()), categories=["对话"], model="999"
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_import_empty_file_400(self):
        with self.assertRaises(HTTPException) as ctx:
            await routes.import_profile(self.alice, _upload("太短"), categories=["对话"])
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_ownership_and_crud(self):
        mine = await self._create(self.alice)
        await self._create(self.bob, "乙")

        listed = await routes.list_profiles(self.alice, self.db)
        self.assertEqual([p.name for p in listed], ["甲"])

        with self.assertRaises(HTTPException) as ctx:
            await routes.get_profile(mine.id, self.bob, self.db)
        self.assertEqual(ctx.exception.status_code, 404)

        updated = await routes.update_profile(
            mine.id, StyleProfileUpdate(name="丙"), self.alice, self.db
        )
        self.assertEqual(updated.name, "丙")
        self.assertEqual(updated.scenes[0]["speakers"], ["林轩"])  # 没传的字段不动

        await routes.delete_profile(mine.id, self.alice, self.db)
        with self.assertRaises(HTTPException):
            await routes.get_profile(mine.id, self.alice, self.db)

    async def test_adapt_value_error_becomes_400(self):
        mine = await self._create(self.alice)
        with self.assertRaises(HTTPException) as ctx:
            await routes.adapt_profile(
                mine.id, StyleAdaptIn(mode="tavern", scene_indexes=[0]), self.alice, self.db
            )
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
