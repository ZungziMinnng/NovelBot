from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.novel_note import NovelNote
from app.schemas.novel_note import NoteCreate, NoteUpdate, NoteOut
from app.services import vector_store

router = APIRouter()


def _vec_doc_id(note_id: int) -> str:
    return f"note_{note_id}"


@router.get("/novel/{novel_id}", response_model=list[NoteOut])
async def list_notes(novel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NovelNote).where(NovelNote.novel_id == novel_id).order_by(NovelNote.created_at)
    )
    return result.scalars().all()


@router.post("/", response_model=NoteOut)
async def create_note(data: NoteCreate, db: AsyncSession = Depends(get_db)):
    note = NovelNote(**data.model_dump())
    db.add(note)
    await db.commit()
    await db.refresh(note)
    if note.content.strip():
        await vector_store.astore_text(
            novel_id=note.novel_id,
            doc_id=_vec_doc_id(note.id),
            text=f"{note.title}\n{note.content}",
            metadata={"type": "novel_note"},
        )
    return note


@router.patch("/{note_id}", response_model=NoteOut)
async def update_note(note_id: int, data: NoteUpdate, db: AsyncSession = Depends(get_db)):
    note = await db.get(NovelNote, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(note, k, v)
    await db.commit()
    await db.refresh(note)
    if note.content.strip():
        await vector_store.astore_text(
            novel_id=note.novel_id,
            doc_id=_vec_doc_id(note.id),
            text=f"{note.title}\n{note.content}",
            metadata={"type": "novel_note"},
        )
    else:
        await vector_store.adelete_docs(note.novel_id, [_vec_doc_id(note.id)])
    return note


@router.delete("/{note_id}")
async def delete_note(note_id: int, db: AsyncSession = Depends(get_db)):
    note = await db.get(NovelNote, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    novel_id = note.novel_id
    await db.delete(note)
    await db.commit()
    await vector_store.adelete_docs(novel_id, [_vec_doc_id(note_id)])
    return {"ok": True}
