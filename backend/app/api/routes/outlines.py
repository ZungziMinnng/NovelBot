import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.memory import Outline
from app.models.novel import Novel
from app.schemas.outline import OutlineCreate, OutlineUpdate, OutlineOut
from app.services import llm_client

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[OutlineOut])
async def list_outlines(novel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Outline)
        .where(Outline.novel_id == novel_id)
        .order_by(Outline.start_chapter, Outline.end_chapter)
    )
    return result.scalars().all()


@router.post("/", response_model=OutlineOut)
async def create_outline(data: OutlineCreate, db: AsyncSession = Depends(get_db)):
    if data.end_chapter < data.start_chapter:
        raise HTTPException(status_code=400, detail="end_chapter 不能小于 start_chapter")
    outline = Outline(
        novel_id=data.novel_id,
        level="chapter",
        volume=data.volume,
        chapter_number=data.start_chapter,
        start_chapter=data.start_chapter,
        end_chapter=data.end_chapter,
        title=data.title,
        content=data.content,
    )
    db.add(outline)
    await db.commit()
    await db.refresh(outline)
    return outline


@router.patch("/{outline_id}", response_model=OutlineOut)
async def update_outline(outline_id: int, data: OutlineUpdate, db: AsyncSession = Depends(get_db)):
    outline = await db.get(Outline, outline_id)
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(outline, k, v)
    if data.start_chapter is not None:
        outline.chapter_number = data.start_chapter
    if data.end_chapter is not None and data.start_chapter is not None and data.end_chapter < data.start_chapter:
        raise HTTPException(status_code=400, detail="end_chapter 不能小于 start_chapter")
    await db.commit()
    await db.refresh(outline)
    return outline


@router.delete("/{outline_id}")
async def delete_outline(outline_id: int, db: AsyncSession = Depends(get_db)):
    outline = await db.get(Outline, outline_id)
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")
    await db.delete(outline)
    await db.commit()
    return {"ok": True}


@router.post("/{outline_id}/expand", response_model=list[OutlineOut])
async def expand_outline(outline_id: int, db: AsyncSession = Depends(get_db)):
    outline = await db.get(Outline, outline_id)
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")
    if outline.start_chapter == outline.end_chapter:
        raise HTTPException(status_code=400, detail="单章大纲无需细化")

    novel = await db.get(Novel, outline.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    model, api_format = llm_client.get_fast_client(novel.fast_model)

    prompt = (
        f"你是一位小说大纲策划师。以下是一部{novel.genre or '小说'}的范围大纲，"
        f"覆盖第{outline.start_chapter}章到第{outline.end_chapter}章。\n\n"
        f"小说类型：{novel.genre or '未知'}\n"
        f"核心设定：{(novel.core_setting or '')[:500]}\n\n"
        f"范围大纲内容：\n{outline.content}\n\n"
        f"请为第{outline.start_chapter}章到第{outline.end_chapter}章的每一章生成独立大纲。"
        f"要求：\n"
        f"1. 每章大纲 50-150 字，描述该章的核心事件和发展\n"
        f"2. 各章之间要有逻辑递进关系\n"
        f"3. 符合范围大纲的整体方向\n\n"
        f"请严格以 JSON 数组格式返回，每个元素包含 chapter（章节号）和 content（大纲内容）：\n"
        f'[{{"chapter": {outline.start_chapter}, "content": "..."}}, ...]'
    )

    messages = [
        {"role": "system", "content": "你是专业小说策划师，擅长拆解范围大纲为逐章细纲。只返回 JSON，不要其他文字。"},
        {"role": "user", "content": prompt},
    ]

    raw = await llm_client.dispatch_chat_complete(messages, model, api_format, temperature=0.7, max_tokens=4096)

    # Parse JSON from LLM response
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="LLM 返回格式异常，请重试")

    created = []
    for item in items:
        ch = item.get("chapter")
        content = item.get("content", "")
        if ch is None or not content:
            continue
        ch = int(ch)
        if ch < outline.start_chapter or ch > outline.end_chapter:
            continue
        # Skip if a per-chapter outline already exists
        existing = await db.execute(
            select(Outline).where(
                Outline.novel_id == outline.novel_id,
                Outline.volume == outline.volume,
                Outline.start_chapter == ch,
                Outline.end_chapter == ch,
            )
        )
        if existing.scalar_one_or_none():
            continue
        new_outline = Outline(
            novel_id=outline.novel_id,
            level="chapter",
            volume=outline.volume,
            chapter_number=ch,
            start_chapter=ch,
            end_chapter=ch,
            title=f"第{ch}章",
            content=content,
        )
        db.add(new_outline)
        created.append(new_outline)

    await db.commit()
    for o in created:
        await db.refresh(o)
    return created
