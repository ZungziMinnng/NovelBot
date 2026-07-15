from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.novel import Novel
from app.models.world_rule import WorldRule
from app.schemas.world_rule import WorldRuleCreate, WorldRuleUpdate, WorldRuleOut
from app.services.world_rules_sync import sync_core_setting
from app.services.entity_embeddings import embed_world_element, remove_entity_embedding

router = APIRouter()


async def _sync_novel(db: AsyncSession, novel_id: int) -> None:
    novel = await db.get(Novel, novel_id)
    if novel:
        await sync_core_setting(db, novel)


@router.get("/novel/{novel_id}", response_model=list[WorldRuleOut])
async def list_rules(novel_id: int, kind: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    stmt = select(WorldRule).where(WorldRule.novel_id == novel_id)
    if kind:
        stmt = stmt.where(WorldRule.kind == kind)
    stmt = stmt.order_by(WorldRule.importance.desc(), WorldRule.created_at)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=WorldRuleOut)
async def create_rule(data: WorldRuleCreate, db: AsyncSession = Depends(get_db)):
    rule = WorldRule(**data.model_dump())
    db.add(rule)
    await db.flush()
    await _sync_novel(db, rule.novel_id)
    await db.commit()
    await db.refresh(rule)
    if rule.kind == "element":
        await embed_world_element(rule.novel_id, rule)
    return rule


@router.patch("/{rule_id}", response_model=WorldRuleOut)
async def update_rule(rule_id: int, data: WorldRuleUpdate, db: AsyncSession = Depends(get_db)):
    rule = await db.get(WorldRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="条目不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(rule, k, v)
    await db.flush()
    await _sync_novel(db, rule.novel_id)
    await db.commit()
    await db.refresh(rule)
    if rule.kind == "element":
        await embed_world_element(rule.novel_id, rule)
    else:
        await remove_entity_embedding(rule.novel_id, "world_element", rule.id)
    return rule


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    rule = await db.get(WorldRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="条目不存在")
    novel_id = rule.novel_id
    was_element = rule.kind == "element"
    rule_id_val = rule.id
    await db.delete(rule)
    await db.flush()
    await _sync_novel(db, novel_id)
    await db.commit()
    if was_element:
        await remove_entity_embedding(novel_id, "world_element", rule_id_val)
    return {"ok": True}
