"""认证核心测试：scrypt 哈希、注册/登录、会话生命周期。"""
import asyncio
import unittest
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user  # noqa: F401
from app.models.user import User, UserSession
from app.services import auth as auth_service
from app.api.routes.auth import register, login, update_me, Credentials, MeUpdate


class PasswordHashTests(unittest.TestCase):
    def test_roundtrip(self):
        stored = auth_service.hash_password("correct horse battery")
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertTrue(auth_service.verify_password("correct horse battery", stored))

    def test_wrong_password(self):
        stored = auth_service.hash_password("correct horse battery")
        self.assertFalse(auth_service.verify_password("wrong password", stored))

    def test_malformed_stored_hash(self):
        self.assertFalse(auth_service.verify_password("x", "not-a-valid-hash"))
        self.assertFalse(auth_service.verify_password("x", ""))

    def test_unique_salt(self):
        self.assertNotEqual(
            auth_service.hash_password("same"),
            auth_service.hash_password("same"),
        )


class AuthFlowTests(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    async def _session(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return engine, async_sessionmaker(engine, expire_on_commit=False)()

    def test_register_then_login(self):
        async def scenario():
            engine, session = await self._session()
            try:
                out = await register(Credentials(username="张三", password="password1"), db=session)
                self.assertTrue(out.token)
                self.assertFalse(out.user.is_admin)

                out2 = await login(Credentials(username="张三", password="password1"), db=session)
                self.assertTrue(out2.token)
                self.assertNotEqual(out.token, out2.token)

                with self.assertRaises(HTTPException) as ctx:
                    await login(Credentials(username="张三", password="wrongpass1"), db=session)
                self.assertEqual(ctx.exception.status_code, 401)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)

    def test_register_validation(self):
        async def scenario():
            engine, session = await self._session()
            try:
                with self.assertRaises(HTTPException):  # 用户名太短
                    await register(Credentials(username="a", password="password1"), db=session)
                with self.assertRaises(HTTPException):  # 密码太短
                    await register(Credentials(username="user1", password="short"), db=session)
                await register(Credentials(username="user1", password="password1"), db=session)
                with self.assertRaises(HTTPException) as ctx:  # 重名（不区分大小写）
                    await register(Credentials(username="USER1", password="password1"), db=session)
                self.assertEqual(ctx.exception.status_code, 400)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)

    def test_session_resolve_revoke_expire(self):
        async def scenario():
            engine, session = await self._session()
            try:
                user = User(username="u1", password_hash="x")
                session.add(user)
                await session.commit()

                token = await auth_service.create_session(session, user.id)
                resolved = await auth_service.resolve_token(session, token)
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved.id, user.id)

                # 无效 token
                self.assertIsNone(await auth_service.resolve_token(session, "garbage"))

                # 登出吊销
                await auth_service.revoke_token(session, token)
                self.assertIsNone(await auth_service.resolve_token(session, token))

                # 过期会话：解析返回 None 且行被懒删除
                token2 = await auth_service.create_session(session, user.id)
                row = (await session.execute(select(UserSession))).scalar_one()
                row.expires_at = datetime.utcnow() - timedelta(seconds=1)
                await session.commit()
                self.assertIsNone(await auth_service.resolve_token(session, token2))
                self.assertEqual(len((await session.execute(select(UserSession))).scalars().all()), 0)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)

    def test_update_me_username(self):
        async def scenario():
            engine, session = await self._session()
            try:
                out = await register(Credentials(username="张三", password="password1"), db=session)
                await register(Credentials(username="李四", password="password1"), db=session)
                user = (await session.execute(
                    select(User).where(User.id == out.user.id)
                )).scalar_one()

                # 正常改名
                updated = await update_me(MeUpdate(username="张三丰"), user, db=session)
                self.assertEqual(updated.username, "张三丰")

                # 重名（不区分大小写）
                with self.assertRaises(HTTPException) as ctx:
                    await update_me(MeUpdate(username="李四"), user, db=session)
                self.assertEqual(ctx.exception.status_code, 400)

                # 非法格式
                with self.assertRaises(HTTPException):
                    await update_me(MeUpdate(username="a"), user, db=session)

                # 改成自己的名字（幂等，不触发重名校验）
                updated = await update_me(MeUpdate(username="张三丰"), user, db=session)
                self.assertEqual(updated.username, "张三丰")
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)

    def test_update_me_password_requires_old(self):
        async def scenario():
            engine, session = await self._session()
            try:
                out = await register(Credentials(username="张三", password="password1"), db=session)
                user = (await session.execute(
                    select(User).where(User.id == out.user.id)
                )).scalar_one()

                # 旧密码错误
                with self.assertRaises(HTTPException) as ctx:
                    await update_me(
                        MeUpdate(old_password="wrongpass1", new_password="password2"),
                        user, db=session,
                    )
                self.assertEqual(ctx.exception.status_code, 400)

                # 旧密码正确 → 新密码生效
                await update_me(
                    MeUpdate(old_password="password1", new_password="password2"),
                    user, db=session,
                )
                out2 = await login(Credentials(username="张三", password="password2"), db=session)
                self.assertTrue(out2.token)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)

    def test_token_stored_hashed(self):
        async def scenario():
            engine, session = await self._session()
            try:
                user = User(username="u1", password_hash="x")
                session.add(user)
                await session.commit()
                token = await auth_service.create_session(session, user.id)
                row = (await session.execute(select(UserSession))).scalar_one()
                self.assertNotEqual(row.token_hash, token)
                self.assertNotIn(token, row.token_hash)
            finally:
                await session.close()
                await engine.dispose()

        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
