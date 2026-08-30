from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.prompt_rule import PromptRule
from app.schemas.prompt_rule import PromptRuleCreate, PromptRuleUpdate, PromptRuleOut
from app.api.deps import CurrentUser

router = APIRouter()


async def _get_owned_rule(db: AsyncSession, rule_id: int, user) -> PromptRule:
    rule = await db.get(PromptRule, rule_id)
    if not rule or rule.user_id != user.id:
        raise HTTPException(status_code=404, detail="规则不存在")
    return rule


@router.get("/", response_model=list[PromptRuleOut])
async def list_rules(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    # 按 sort_order 排：这个顺序决定规则拼进 prompt 的先后，有语义
    result = await db.execute(
        select(PromptRule)
        .where(PromptRule.user_id == user.id)
        .order_by(PromptRule.sort_order, PromptRule.id)
    )
    return result.scalars().all()


@router.post("/", response_model=PromptRuleOut)
async def create_rule(data: PromptRuleCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    # is_builtin / builtin_key 不接受客户端赋值，只有种子函数能造内置规则
    rule = PromptRule(
        name=data.name,
        content=data.content,
        category=data.category,
        enabled=data.enabled,
        sort_order=data.sort_order,
        is_builtin=False,
        builtin_key="",
        user_id=user.id,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.get("/{rule_id}", response_model=PromptRuleOut)
async def get_rule(rule_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await _get_owned_rule(db, rule_id, user)


@router.patch("/{rule_id}", response_model=PromptRuleOut)
async def update_rule(
    rule_id: int, data: PromptRuleUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    rule = await _get_owned_rule(db, rule_id, user)
    for field in ("name", "content", "category", "enabled", "sort_order"):
        value = getattr(data, field)
        if value is not None:
            setattr(rule, field, value)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rule = await _get_owned_rule(db, rule_id, user)
    if rule.is_builtin:
        raise HTTPException(status_code=409, detail="内置规则不可删除，可停用")
    await db.delete(rule)
    await db.commit()
    return {"ok": True}
