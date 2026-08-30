"""认证服务：scrypt 密码哈希 + 不透明 token 会话（stdlib，无新依赖）。"""
import hashlib
import hmac
import secrets
from contextvars import ContextVar
from datetime import datetime, timedelta

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserSession

# 请求级当前用户，由 AuthMiddleware 写入；deps 与 llm_client 共同读取
current_user_var: ContextVar[User | None] = ContextVar("current_user", default=None)

SESSION_TTL_DAYS = 30

_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 64


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(hash_hex)),
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_session(db: AsyncSession, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(UserSession(
        token_hash=_token_hash(token),
        user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS),
    ))
    await db.commit()
    return token


async def resolve_token(db: AsyncSession, token: str) -> User | None:
    result = await db.execute(
        select(UserSession).where(UserSession.token_hash == _token_hash(token))
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None
    if session.expires_at < datetime.utcnow():
        await db.delete(session)
        await db.commit()
        return None
    return await db.get(User, session.user_id)


async def revoke_token(db: AsyncSession, token: str) -> None:
    await db.execute(
        delete(UserSession).where(UserSession.token_hash == _token_hash(token))
    )
    await db.commit()
