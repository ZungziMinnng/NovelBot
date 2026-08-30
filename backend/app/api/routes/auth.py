import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db, seed_builtin_rules
from app.models.user import User
from app.models.model_library import ModelEntry
from app.api.deps import CurrentUser
from app.services import auth as auth_service

router = APIRouter()

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_一-鿿]{2,32}$")


class Credentials(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool
    default_writer_model: str
    default_fast_model: str
    hidden_novel_ids: list[int]
    hidden_preset_ids: list[int]


class AuthOut(BaseModel):
    token: str
    user: UserOut


class MeUpdate(BaseModel):
    username: str | None = None
    default_writer_model: str | None = None
    default_fast_model: str | None = None
    hidden_novel_ids: list[int] | None = None
    hidden_preset_ids: list[int] | None = None
    old_password: str = ""
    new_password: str = ""


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        default_writer_model=user.default_writer_model or "",
        default_fast_model=user.default_fast_model or "",
        hidden_novel_ids=user.hidden_novel_ids or [],
        hidden_preset_ids=user.hidden_preset_ids or [],
    )


async def _username_taken(db: AsyncSession, username: str, exclude_id: int | None = None) -> bool:
    stmt = select(func.count(User.id)).where(func.lower(User.username) == username.lower())
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    result = await db.execute(stmt)
    return (result.scalar() or 0) > 0


@router.post("/register", response_model=AuthOut)
async def register(data: Credentials, db: AsyncSession = Depends(get_db)):
    username = data.username.strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(400, "用户名需为 2-32 位字母、数字、下划线或中文")
    if len(data.password) < 8:
        raise HTTPException(400, "密码至少 8 位")
    if await _username_taken(db, username):
        raise HTTPException(400, "用户名已被使用")
    user = User(username=username, password_hash=auth_service.hash_password(data.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    # 新账号立刻拿到内置规则，不用等下次重启补种
    await seed_builtin_rules([user.id])
    token = await auth_service.create_session(db, user.id)
    return AuthOut(token=token, user=_user_out(user))


@router.post("/login", response_model=AuthOut)
async def login(data: Credentials, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(func.lower(User.username) == data.username.strip().lower())
    )
    user = result.scalar_one_or_none()
    if user is None or not auth_service.verify_password(data.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    token = await auth_service.create_session(db, user.id)
    return AuthOut(token=token, user=_user_out(user))


@router.post("/logout")
async def logout(request: Request, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        await auth_service.revoke_token(db, auth_header[7:].strip())
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return _user_out(user)


async def _validate_model_ref(db: AsyncSession, ref: str, user: User) -> None:
    """默认模型只能指向自己的 ModelEntry（数字 id）。"""
    if not ref.isdigit():
        raise HTTPException(400, "模型引用无效，请从模型库中选择")
    entry = await db.get(ModelEntry, int(ref))
    if entry is None or (entry.user_id != user.id and not user.is_admin):
        raise HTTPException(400, "模型不存在或不属于当前用户")


@router.patch("/me", response_model=UserOut)
async def update_me(data: MeUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    db_user = await db.get(User, user.id)
    if data.username is not None:
        username = data.username.strip()
        if username != db_user.username:
            if not _USERNAME_RE.match(username):
                raise HTTPException(400, "用户名需为 2-32 位字母、数字、下划线或中文")
            if await _username_taken(db, username, exclude_id=db_user.id):
                raise HTTPException(400, "用户名已被使用")
            db_user.username = username
    if data.default_writer_model is not None:
        if data.default_writer_model:
            await _validate_model_ref(db, data.default_writer_model, user)
        db_user.default_writer_model = data.default_writer_model
    if data.default_fast_model is not None:
        if data.default_fast_model:
            await _validate_model_ref(db, data.default_fast_model, user)
        db_user.default_fast_model = data.default_fast_model
    if data.hidden_novel_ids is not None:
        db_user.hidden_novel_ids = sorted(set(data.hidden_novel_ids))
    if data.hidden_preset_ids is not None:
        db_user.hidden_preset_ids = sorted(set(data.hidden_preset_ids))
    if data.new_password:
        if not auth_service.verify_password(data.old_password, db_user.password_hash):
            raise HTTPException(400, "旧密码错误")
        if len(data.new_password) < 8:
            raise HTTPException(400, "新密码至少 8 位")
        db_user.password_hash = auth_service.hash_password(data.new_password)
    await db.commit()
    await db.refresh(db_user)
    return _user_out(db_user)
