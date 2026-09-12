"""RPG 提示词的每用户覆盖。结构与 tavern_prompts 一致，读写 User.rpg_prompts。

不加 require_admin：小说侧那个 /api/prompts 改的是磁盘上的共享模板文件，
所以只给管理员；这里是每用户各存一份 JSON，互不影响，谁都能改自己的。
"""
from fastapi import APIRouter, Depends, HTTPException
from jinja2 import TemplateError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.database import get_db
from app.models.user import User
from app.services import rpg_prompts


router = APIRouter(prefix="/prompts")


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


def _output(name: str, overrides: dict) -> PromptOut:
    if name not in rpg_prompts.PROMPTS:
        raise HTTPException(404, "未知的 RPG 提示词")
    default = rpg_prompts.default_content(name)
    return PromptOut(
        name=name, **rpg_prompts.PROMPTS[name],
        content=overrides.get(name, default), default_content=default,
        customized=name in overrides,
    )


@router.get("/", response_model=list[PromptOut])
async def list_prompts(user: CurrentUser):
    return [_output(name, user.rpg_prompts or {}) for name in rpg_prompts.PROMPTS]


@router.put("/{name}", response_model=PromptOut)
async def update_prompt(name: str, data: PromptUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if name not in rpg_prompts.PROMPTS:
        raise HTTPException(404, "未知的 RPG 提示词")
    if not data.content.strip():
        raise HTTPException(400, "提示词不能为空，请使用恢复默认")
    try:
        rpg_prompts.validate(name, data.content)
    except (TemplateError, TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(400, f"提示词模板错误：{exc}") from exc
    # 重新取一次当前 session 里的实例：CurrentUser 来自 contextvar，直接改它
    # 可能改在另一个 session 的对象上。整份赋值也是必须的——JSON 列不追踪
    # 原地改动，不整体赋新 dict 不会被标脏
    owner = await db.get(User, user.id)
    owner.rpg_prompts = {**(owner.rpg_prompts or {}), name: data.content}
    await db.commit()
    return _output(name, owner.rpg_prompts)


@router.delete("/{name}", response_model=PromptOut)
async def reset_prompt(name: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if name not in rpg_prompts.PROMPTS:
        raise HTTPException(404, "未知的 RPG 提示词")
    owner = await db.get(User, user.id)
    owner.rpg_prompts = {key: value for key, value in (owner.rpg_prompts or {}).items() if key != name}
    await db.commit()
    return _output(name, owner.rpg_prompts)
