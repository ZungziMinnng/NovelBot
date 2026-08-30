import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.novel_note import NovelNote
from app.schemas.novel_note import NoteCreate, NoteUpdate, NoteOut
from app.services import vector_store
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()

logger = logging.getLogger(__name__)


def _vec_doc_id(note_id: int) -> str:
    return f"note_{note_id}"


async def _embed_note(note: NovelNote, db: AsyncSession) -> None:
    """写入笔记向量。先按小说配置装载嵌入模型（避免冷缓存回退到默认维度导致维度不匹配）；
    向量写入失败不应让笔记保存失败（与摘要/实体同步策略一致，可重建向量库修复）。"""
    try:
        await vector_store.ensure_embedding_configured(note.novel_id, db)
        await vector_store.astore_text(
            novel_id=note.novel_id,
            doc_id=_vec_doc_id(note.id),
            text=f"{note.title}\n{note.content}",
            metadata={"type": "novel_note", "note_id": note.id, "importance": note.importance},
        )
    except Exception:
        logger.warning(
            "笔记向量同步失败（文本已保存，可重建向量库修复）: novel=%s note=%s",
            note.novel_id, note.id, exc_info=True,
        )


@router.get("/novel/{novel_id}", response_model=list[NoteOut])
async def list_notes(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    result = await db.execute(
        select(NovelNote).where(NovelNote.novel_id == novel_id).order_by(NovelNote.created_at)
    )
    return result.scalars().all()


@router.post("/", response_model=NoteOut)
async def create_note(data: NoteCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, data.novel_id, user)
    note = NovelNote(**data.model_dump())
    db.add(note)
    await db.commit()
    await db.refresh(note)
    if note.content.strip():
        await _embed_note(note, db)
    return note


@router.patch("/{note_id}", response_model=NoteOut)
async def update_note(note_id: int, data: NoteUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    note = await get_owned_child(db, NovelNote, note_id, user, "笔记")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(note, k, v)
    await db.commit()
    await db.refresh(note)
    if note.content.strip():
        await _embed_note(note, db)
    else:
        await vector_store.adelete_docs(note.novel_id, [_vec_doc_id(note.id)])
    return note


@router.delete("/{note_id}")
async def delete_note(note_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    note = await get_owned_child(db, NovelNote, note_id, user, "笔记")
    novel_id = note.novel_id
    await db.delete(note)
    await db.commit()
    await vector_store.adelete_docs(novel_id, [_vec_doc_id(note_id)])
    return {"ok": True}
