import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.chapter import Chapter
from app.models.memory import Memory, Outline
from app.models.novel import Novel
from app.schemas.admin import MemoryOut, MemoryUpdate, OutlineOut, OutlineUpdate
from app.services import summarizer, vector_store
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()

logger = logging.getLogger(__name__)


# ── Memory endpoints ──────────────────────────────────────────────────

@router.get("/novel/{novel_id}/memories", response_model=list[MemoryOut])
async def list_memories(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    result = await db.execute(
        select(Memory)
        .where(Memory.novel_id == novel_id, Memory.memory_type != "state_snapshot")
        .order_by(Memory.chapter_number, Memory.id)
    )
    return result.scalars().all()


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def update_memory(memory_id: int, data: MemoryUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    memory = await get_owned_child(db, Memory, memory_id, user, "记忆条目")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(memory, k, v)
    await db.commit()
    await db.refresh(memory)
    return memory


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    memory = await get_owned_child(db, Memory, memory_id, user, "记忆条目")
    # 清理 ChromaDB 中对应的向量
    if memory.memory_type == "chapter_summary" and memory.chapter_id:
        await vector_store.adelete_docs(
            memory.novel_id, [f"chapter_{memory.chapter_id}_summary"]
        )
    await db.delete(memory)
    await db.commit()
    return {"ok": True}


class BackfillMilestonesIn(BaseModel):
    start_chapter: int = Field(ge=1)
    end_chapter: int = Field(ge=1)


@router.post("/novel/{novel_id}/backfill-milestones")
async def backfill_milestones(
    novel_id: int,
    data: BackfillMilestonesIn,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """对存量章节按全文逐章抽取关系里程碑（手动触发，重跑幂等）。"""
    await get_owned_novel(db, novel_id, user)
    numbers = list((await db.execute(
        select(Chapter.number).where(
            Chapter.novel_id == novel_id,
            Chapter.number >= data.start_chapter,
            Chapter.number <= data.end_chapter,
        ).order_by(Chapter.number)
    )).scalars())

    processed = 0
    extracted = 0
    failed: list[int] = []
    for number in numbers:
        # 每章重新取对象：失败 rollback 会使会话内 ORM 对象过期，复用会触发懒加载报错
        try:
            novel = (await db.execute(
                select(Novel).where(Novel.id == novel_id)
            )).scalar_one()
            chapter = (await db.execute(
                select(Chapter).where(Chapter.novel_id == novel_id, Chapter.number == number)
            )).scalars().first()
            extracted += await summarizer.backfill_milestones_for_chapter(db, novel, chapter)
            await db.commit()
            processed += 1
        except Exception as e:  # 单章失败跳过，不中断整批
            await db.rollback()
            failed.append(number)
            logger.warning("章节 %s 回填关系里程碑失败: %s", number, e)
    return {"processed": processed, "extracted": extracted, "failed": failed}


# ── Outline endpoints ─────────────────────────────────────────────────

@router.get("/novel/{novel_id}/outlines", response_model=list[OutlineOut])
async def list_outlines(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    result = await db.execute(
        select(Outline)
        .where(Outline.novel_id == novel_id)
        .order_by(Outline.volume, Outline.chapter_number)
    )
    return result.scalars().all()


@router.patch("/outlines/{outline_id}", response_model=OutlineOut)
async def update_outline(outline_id: int, data: OutlineUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    outline = await get_owned_child(db, Outline, outline_id, user, "大纲条目")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(outline, k, v)
    await db.commit()
    await db.refresh(outline)
    return outline
