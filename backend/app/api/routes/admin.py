from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.memory import Memory, Outline
from app.schemas.admin import MemoryOut, MemoryUpdate, OutlineOut, OutlineUpdate
from app.services import vector_store

router = APIRouter()


# ── Memory endpoints ──────────────────────────────────────────────────

@router.get("/novel/{novel_id}/memories", response_model=list[MemoryOut])
async def list_memories(novel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Memory)
        .where(Memory.novel_id == novel_id, Memory.memory_type != "state_snapshot")
        .order_by(Memory.chapter_number, Memory.id)
    )
    return result.scalars().all()


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def update_memory(memory_id: int, data: MemoryUpdate, db: AsyncSession = Depends(get_db)):
    memory = await db.get(Memory, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(memory, k, v)
    await db.commit()
    await db.refresh(memory)
    return memory


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int, db: AsyncSession = Depends(get_db)):
    memory = await db.get(Memory, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    # 清理 ChromaDB 中对应的向量
    if memory.memory_type == "chapter_summary" and memory.chapter_id:
        await vector_store.adelete_docs(
            memory.novel_id, [f"chapter_{memory.chapter_id}_summary"]
        )
    await db.delete(memory)
    await db.commit()
    return {"ok": True}


# ── Outline endpoints ─────────────────────────────────────────────────

@router.get("/novel/{novel_id}/outlines", response_model=list[OutlineOut])
async def list_outlines(novel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Outline)
        .where(Outline.novel_id == novel_id)
        .order_by(Outline.volume, Outline.chapter_number)
    )
    return result.scalars().all()


@router.patch("/outlines/{outline_id}", response_model=OutlineOut)
async def update_outline(outline_id: int, data: OutlineUpdate, db: AsyncSession = Depends(get_db)):
    outline = await db.get(Outline, outline_id)
    if not outline:
        raise HTTPException(status_code=404, detail="大纲条目不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(outline, k, v)
    await db.commit()
    await db.refresh(outline)
    return outline
