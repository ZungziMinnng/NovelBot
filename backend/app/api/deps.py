"""认证与归属校验依赖。"""
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.novel import Novel
from app.models.user import User
from app.services.auth import current_user_var


async def get_current_user() -> User:
    user = current_user_var.get()
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def get_owned_novel(db: AsyncSession, novel_id: int, user: User) -> Novel:
    """载入小说并校验归属；不存在或非本人一律 404（防 id 枚举）。"""
    novel = await db.get(Novel, novel_id)
    if novel is None or novel.user_id != user.id:
        raise HTTPException(status_code=404, detail="小说不存在")
    return novel


async def get_owned_child(db: AsyncSession, model, obj_id: int, user: User, label: str = "资源"):
    """载入子资源（章节/角色/地点等，须有 novel_id 字段）并校验其小说归属。"""
    obj = await db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    await get_owned_novel(db, obj.novel_id, user)
    return obj
