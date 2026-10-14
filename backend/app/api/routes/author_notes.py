"""作者便签 / 章节备注：只给作者自己看，不进向量库、不进任何提示词。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.author_note import AuthorNote
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()


class AuthorNoteCreate(BaseModel):
    novel_id: int
    content: str
    chapter_number: Optional[int] = Field(default=None, ge=1)


class AuthorNoteUpdate(BaseModel):
    content: Optional[str] = None
    done: Optional[bool] = None
    # 显式传 null = 取消挂章；不传 = 不动（靠 model_fields_set 区分）
    chapter_number: Optional[int] = Field(default=None, ge=1)


def _out(n: AuthorNote) -> dict:
    return {
        "id": n.id, "novel_id": n.novel_id, "chapter_number": n.chapter_number,
        "content": n.content, "done": n.done,
        "created_at": n.created_at, "updated_at": n.updated_at,
    }


@router.get("/novel/{novel_id}")
async def list_notes(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    rows = (await db.execute(
        select(AuthorNote)
        .where(AuthorNote.novel_id == novel_id)
        .order_by(AuthorNote.done, AuthorNote.created_at.desc())
    )).scalars().all()
    return [_out(n) for n in rows]


@router.post("/")
async def create_note(body: AuthorNoteCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, body.novel_id, user)
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="便签内容不能为空")
    note = AuthorNote(novel_id=body.novel_id, content=body.content.strip(), chapter_number=body.chapter_number)
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return _out(note)


@router.patch("/{note_id}")
async def update_note(note_id: int, body: AuthorNoteUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    note = await get_owned_child(db, AuthorNote, note_id, user, "便签")
    if body.content is not None:
        if not body.content.strip():
            raise HTTPException(status_code=400, detail="便签内容不能为空")
        note.content = body.content.strip()
    if body.done is not None:
        note.done = body.done
    if "chapter_number" in body.model_fields_set:
        note.chapter_number = body.chapter_number
    await db.commit()
    await db.refresh(note)
    return _out(note)


@router.delete("/{note_id}")
async def delete_note(note_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    note = await get_owned_child(db, AuthorNote, note_id, user, "便签")
    await db.delete(note)
    await db.commit()
    return {"ok": True}
