"""每用户提示词覆盖的通用 CRUD。

RPG 和酒馆两侧的这套增删改查曾是逐行复制的两份，差别只有服务模块、User 上的
JSON 字段名和 404 文案。这里生成 router，两边各传自己的配置。

小说侧的 /api/prompts 不走这里：那边改磁盘上的共享模板文件、只给管理员、
没有 DELETE，语义完全不同。
"""
from types import ModuleType
from typing import Callable, NamedTuple

from fastapi import APIRouter, Depends, HTTPException
from jinja2 import TemplateError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.database import get_db
from app.models.user import User


class PromptUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


class PromptOut(BaseModel):
    name: str
    label: str
    description: str
    variables: dict[str, str]
    content: str
    default_content: str
    customized: bool


class UserPromptsRoutes(NamedTuple):
    """三个 handler 也一并返回：测试是直接 await handler(...) 做单测的，不走 HTTP。"""
    router: APIRouter
    list_prompts: Callable
    update_prompt: Callable
    reset_prompt: Callable


def create_user_prompts_router(
    service: ModuleType, field_name: str, unknown_message: str
) -> UserPromptsRoutes:
    """service 提供 PROMPTS / default_content / validate；field_name 是 User 上的 JSON 列名。"""
    router = APIRouter(prefix="/prompts")

    def _output(name: str, overrides: dict) -> PromptOut:
        if name not in service.PROMPTS:
            raise HTTPException(404, unknown_message)
        default = service.default_content(name)
        return PromptOut(
            name=name, **service.PROMPTS[name],
            content=overrides.get(name, default), default_content=default,
            customized=name in overrides,
        )

    @router.get("/", response_model=list[PromptOut])
    async def list_prompts(user: CurrentUser):
        return [_output(name, getattr(user, field_name) or {}) for name in service.PROMPTS]

    @router.put("/{name}", response_model=PromptOut)
    async def update_prompt(name: str, data: PromptUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
        if name not in service.PROMPTS:
            raise HTTPException(404, unknown_message)
        if not data.content.strip():
            raise HTTPException(400, "提示词不能为空，请使用恢复默认")
        try:
            service.validate(name, data.content)
        except (TemplateError, TypeError, ValueError, OverflowError) as exc:
            raise HTTPException(400, f"提示词模板错误：{exc}") from exc
        # 重新取一次当前 session 里的实例：CurrentUser 来自 contextvar，直接改它
        # 可能改在另一个 session 的对象上。整份赋值也是必须的——JSON 列不追踪
        # 原地改动，不整体赋新 dict 不会被标脏
        owner = await db.get(User, user.id)
        setattr(owner, field_name, {**(getattr(owner, field_name) or {}), name: data.content})
        await db.commit()
        return _output(name, getattr(owner, field_name))

    @router.delete("/{name}", response_model=PromptOut)
    async def reset_prompt(name: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
        if name not in service.PROMPTS:
            raise HTTPException(404, unknown_message)
        owner = await db.get(User, user.id)
        setattr(owner, field_name, {
            key: value for key, value in (getattr(owner, field_name) or {}).items() if key != name
        })
        await db.commit()
        return _output(name, getattr(owner, field_name))

    return UserPromptsRoutes(router, list_prompts, update_prompt, reset_prompt)
