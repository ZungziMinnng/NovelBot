from fastapi import APIRouter, Depends, HTTPException
from jinja2 import TemplateError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.database import get_db
from app.models.user import User
from app.services import tavern_prompts


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
    if name not in tavern_prompts.PROMPTS:
        raise HTTPException(404, "未知的酒馆提示词")
    default = tavern_prompts.default_content(name)
    return PromptOut(
        name=name, **tavern_prompts.PROMPTS[name],
        content=overrides.get(name, default), default_content=default,
        customized=name in overrides,
    )


@router.get("/", response_model=list[PromptOut])
async def list_prompts(user: CurrentUser):
    return [_output(name, user.tavern_prompts or {}) for name in tavern_prompts.PROMPTS]


@router.put("/{name}", response_model=PromptOut)
async def update_prompt(name: str, data: PromptUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if name not in tavern_prompts.PROMPTS:
        raise HTTPException(404, "未知的酒馆提示词")
    if not data.content.strip():
        raise HTTPException(400, "提示词不能为空，请使用恢复默认")
    try:
        tavern_prompts.validate(name, data.content)
    except (TemplateError, TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(400, f"提示词模板错误：{exc}") from exc
    owner = await db.get(User, user.id)
    owner.tavern_prompts = {**(owner.tavern_prompts or {}), name: data.content}
    await db.commit()
    return _output(name, owner.tavern_prompts)


@router.delete("/{name}", response_model=PromptOut)
async def reset_prompt(name: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if name not in tavern_prompts.PROMPTS:
        raise HTTPException(404, "未知的酒馆提示词")
    owner = await db.get(User, user.id)
    owner.tavern_prompts = {key: value for key, value in (owner.tavern_prompts or {}).items() if key != name}
    await db.commit()
    return _output(name, owner.tavern_prompts)
