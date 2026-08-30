"""数据隔离测试：跨用户访问一律 404、列表过滤、API Key 永不明文外泄。"""
import asyncio
import unittest

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user  # noqa: F401
from app.models.api_provider import ApiProvider
from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.user import User
from app.api.deps import get_owned_novel, get_owned_child
from app.api.routes.api_providers import list_providers


class OwnershipTests(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    async def _two_users(self, session):
        alice = User(username="alice", password_hash="x")
        bob = User(username="bob", password_hash="x")
        session.add_all([alice, bob])
        await session.flush()
        novel_a = Novel(title="A的书", user_id=alice.id)
        novel_b = Novel(title="B的书", user_id=bob.id)
        session.add_all([novel_a, novel_b])
        await session.flush()
        return alice, bob, novel_a, novel_b

    def test_cross_user_novel_404(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                alice, bob, novel_a, novel_b = await self._two_users(session)

                # 本人可访问
                got = await get_owned_novel(session, novel_a.id, alice)
                self.assertEqual(got.id, novel_a.id)

                # 跨用户 → 404（与"不存在"不可区分，防 id 枚举）
                with self.assertRaises(HTTPException) as ctx:
                    await get_owned_novel(session, novel_b.id, alice)
                self.assertEqual(ctx.exception.status_code, 404)
                with self.assertRaises(HTTPException) as ctx2:
                    await get_owned_novel(session, 9999, alice)
                self.assertEqual(ctx2.exception.status_code, 404)
                self.assertEqual(ctx.exception.detail, ctx2.exception.detail)

                # admin 也无特权：严格隔离
                admin = User(username="admin2", password_hash="x", is_admin=True)
                session.add(admin)
                await session.flush()
                with self.assertRaises(HTTPException):
                    await get_owned_novel(session, novel_a.id, admin)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)

    def test_child_resource_via_novel(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                alice, bob, novel_a, novel_b = await self._two_users(session)
                ch = Chapter(novel_id=novel_b.id, number=1, volume=1, content="秘密内容", word_count=4)
                session.add(ch)
                await session.flush()

                got = await get_owned_child(session, Chapter, ch.id, bob, "章节")
                self.assertEqual(got.id, ch.id)

                with self.assertRaises(HTTPException) as ctx:
                    await get_owned_child(session, Chapter, ch.id, alice, "章节")
                self.assertEqual(ctx.exception.status_code, 404)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)

    def test_provider_list_filtered_and_key_masked(self):
        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session = async_sessionmaker(engine, expire_on_commit=False)()
            try:
                alice, bob, _, _ = await self._two_users(session)
                secret = "sk-verysecretkey1234567890"
                session.add_all([
                    ApiProvider(name="A的供应商", base_url="https://a.example", api_key=secret,
                                api_format="openai", user_id=alice.id),
                    ApiProvider(name="B的供应商", base_url="https://b.example", api_key="sk-bob-key-000",
                                api_format="openai", user_id=bob.id),
                ])
                await session.commit()

                items = await list_providers(alice, db=session)
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0].name, "A的供应商")

                # key 只以掩码形式出现，schema 中没有明文字段
                dumped = items[0].model_dump()
                self.assertNotIn("api_key", dumped)
                self.assertNotEqual(dumped["api_key_masked"], secret)
                self.assertNotIn(secret[5:-4], dumped["api_key_masked"])
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
