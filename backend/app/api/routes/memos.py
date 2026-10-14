"""主页备忘录：小说侧 / 游戏侧各一块，按用户隔离，不进任何提示词。"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.memo import Memo
from app.api.deps import CurrentUser

router = APIRouter()

Scope = Literal["novel", "game"]


class MemoCreate(BaseModel):
    scope: Scope
    content: str = Field(max_length=5000)


class MemoUpdate(BaseModel):
    content: str = Field(max_length=5000)


def _out(m: Memo) -> dict:
    return {
        "id": m.id, "scope": m.scope, "content": m.content,
        "created_at": m.created_at, "updated_at": m.updated_at,
    }


def _clean(content: str) -> str:
    text = content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="备忘内容不能为空")
    return text


async def _owned(db: AsyncSession, memo_id: int, user) -> Memo:
    memo = await db.get(Memo, memo_id)
    if memo is None or memo.user_id != user.id:
        raise HTTPException(status_code=404, detail="备忘不存在")
    return memo


@router.get("/")
async def list_memos(scope: Scope, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Memo)
        .where(Memo.user_id == user.id, Memo.scope == scope)
        .order_by(Memo.updated_at.desc(), Memo.id.desc())
    )).scalars().all()
    return [_out(m) for m in rows]


@router.post("/")
async def create_memo(body: MemoCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    memo = Memo(user_id=user.id, scope=body.scope, content=_clean(body.content))
    db.add(memo)
    await db.commit()
    await db.refresh(memo)
    return _out(memo)


@router.patch("/{memo_id}")
async def update_memo(memo_id: int, body: MemoUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    memo = await _owned(db, memo_id, user)
    memo.content = _clean(body.content)
    await db.commit()
    await db.refresh(memo)
    return _out(memo)


@router.delete("/{memo_id}")
async def delete_memo(memo_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    memo = await _owned(db, memo_id, user)
    await db.delete(memo)
    await db.commit()
    return {"ok": True}
