import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.memory import Outline
from app.models.novel import Novel
from app.models.volume import Volume
from app.schemas.outline import OutlineCreate, OutlineUpdate, OutlineOut
from app.services import llm_client, outline_health, outline_plan
from app.services.llm_json import repair_json
from app.prompts.loader import render
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()

# 体检时估算全书目标字数用的每章字数。没有"全书目标字数"这个字段，只有预估章数
WORDS_PER_CHAPTER = 3000


@router.get("/plan-options")
async def plan_options():
    """执行计划的候选值。前端下拉框读这个，避免和 outline_plan 里的清单各写一份。"""
    return {
        "chapter_roles": outline_plan.CHAPTER_ROLES,
        "emotion_tones": outline_plan.EMOTION_TONES,
        "hook_types": outline_plan.HOOK_TYPES,
    }


@router.get("/novel/{novel_id}", response_model=list[OutlineOut])
async def list_outlines(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    result = await db.execute(
        select(Outline)
        .where(Outline.novel_id == novel_id)
        .order_by(Outline.start_chapter, Outline.end_chapter)
    )
    return result.scalars().all()


@router.get("/novel/{novel_id}/health")
async def outline_health(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """大纲体检：章节配比、爽点密度、钩子重复、卷级库存。只报告，不阻断任何操作。

    路由声明必须在 /{outline_id} 之前，否则 "novel" 会被当成 outline_id。
    """
    novel = await get_owned_novel(db, novel_id, user)

    outlines = (await db.execute(
        select(Outline)
        .where(Outline.novel_id == novel_id, Outline.level == "chapter")
        .order_by(Outline.start_chapter)
    )).scalars().all()
    word_counts = dict((await db.execute(
        select(Chapter.number, Chapter.word_count).where(Chapter.novel_id == novel_id)
    )).all())
    volumes = (await db.execute(
        select(Volume).where(Volume.novel_id == novel_id).order_by(Volume.number)
    )).scalars().all()

    total_target = (novel.estimated_chapters or 0) * WORDS_PER_CHAPTER

    return {
        "chapter_count": len(outlines),
        "total_target_words": total_target,
        "chapters": outline_health.check_chapter_outlines([
            {
                "chapter_number": o.chapter_number,
                "content": o.content,
                "chapter_role": o.chapter_role,
                "emotion_tone": o.emotion_tone,
                "emotion_intensity": o.emotion_intensity,
                "hook_type": o.hook_type,
                "hook_strength": o.hook_strength,
                "word_count": word_counts.get(o.chapter_number, 0),
            }
            for o in outlines
        ]),
        "volumes": [
            {
                "number": v.number,
                "title": v.title,
                "findings": outline_health.check_volume_reserves(
                    {
                        "endgame_cards": v.endgame_cards,
                        "tier_count": v.tier_count,
                        "words_per_tier": v.words_per_tier,
                        "spent_payoffs": v.spent_payoffs,
                    },
                    total_target,
                ),
            }
            for v in volumes
        ],
    }


@router.post("/novel/{novel_id}/chapter/{chapter_number}/draft", response_model=OutlineOut)
async def draft_chapter_outline(
    novel_id: int,
    chapter_number: int,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """给单独一章补一份细纲。写正文前发现这章没纲时用。

    依据按优先级取：覆盖本章的范围大纲 > 全书概要 > 前几章摘要。
    已有细纲则原地重写，避免连点生成出两条。
    """
    novel = await get_owned_novel(db, novel_id, user)

    existing = (await db.execute(
        select(Outline).where(
            Outline.novel_id == novel_id,
            Outline.start_chapter == chapter_number,
            Outline.end_chapter == chapter_number,
        )
    )).scalar_one_or_none()

    range_outline = (await db.execute(
        select(Outline).where(
            Outline.novel_id == novel_id,
            Outline.start_chapter <= chapter_number,
            Outline.end_chapter >= chapter_number,
            Outline.start_chapter != Outline.end_chapter,
        ).order_by(Outline.start_chapter.desc())
    )).scalars().first()

    volume = range_outline.volume if range_outline else 0
    if not volume:
        prev_ch = (await db.execute(
            select(Chapter.volume).where(
                Chapter.novel_id == novel_id, Chapter.number < chapter_number
            ).order_by(Chapter.number.desc()).limit(1)
        )).scalar()
        volume = prev_ch or 1

    recent = (await db.execute(
        select(Chapter.number, Chapter.summary).where(
            Chapter.novel_id == novel_id,
            Chapter.number < chapter_number,
            Chapter.summary != "",
        ).order_by(Chapter.number.desc()).limit(3)
    )).all()
    recent_summaries = "\n".join(
        f"第{num}章：{summary}" for num, summary in reversed(recent)
    )

    prev_outline = (await db.execute(
        select(Outline.hook_type).where(
            Outline.novel_id == novel_id,
            Outline.start_chapter == chapter_number - 1,
            Outline.end_chapter == chapter_number - 1,
        )
    )).scalar()

    characters = (await db.execute(
        select(Character.name, Character.role).where(Character.novel_id == novel_id).limit(20)
    )).all()
    first_volume = (await db.execute(
        select(Volume).where(Volume.novel_id == novel_id, Volume.number == 1)
    )).scalar_one_or_none()

    prompt = render(
        "outline_single_chapter.jinja2",
        chapter_number=chapter_number,
        volume=volume,
        genre=novel.genre or "小说",
        core_setting=(novel.core_setting or "")[:800],
        ending=novel.ending or "",
        range_outline=range_outline.content if range_outline else "",
        range_start=range_outline.start_chapter if range_outline else 0,
        range_end=range_outline.end_chapter if range_outline else 0,
        book_summary=(novel.book_summary or "")[:800],
        recent_summaries=recent_summaries,
        characters_summary="、".join(f"{n}（{r}）" for n, r in characters),
        endgame_cards=(first_volume.endgame_cards if first_volume else "") or "",
        chapter_roles=" / ".join(outline_plan.CHAPTER_ROLES),
        emotion_tones=" / ".join(outline_plan.EMOTION_TONES),
        hook_types=" / ".join(outline_plan.HOOK_TYPES),
        avoid_hook=prev_outline or "",
    )

    model, api_format = llm_client.get_fast_client(novel.fast_model)
    raw = await llm_client.dispatch_chat_complete(
        [
            {"role": "system", "content": "你是专业小说策划师，只返回 JSON，不要其他文字。"},
            {"role": "user", "content": prompt},
        ],
        model, api_format, temperature=0.7, max_tokens=1500,
    )
    try:
        item = json.loads(repair_json(raw, expect="object"))
        if not isinstance(item, dict):
            raise json.JSONDecodeError("top-level is not object", raw, 0)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="LLM 返回格式异常，请重试")

    content = (item.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=502, detail="LLM 没返回细纲内容，请重试")
    title = (item.get("title") or f"第{chapter_number}章").strip()
    plan = outline_plan.clean_plan(item)

    if existing:
        existing.title = title
        existing.content = content
        for k, v in plan.items():
            setattr(existing, k, v)
        outline = existing
    else:
        outline = Outline(
            novel_id=novel_id,
            level="chapter",
            volume=volume,
            chapter_number=chapter_number,
            start_chapter=chapter_number,
            end_chapter=chapter_number,
            title=title,
            content=content,
            **plan,
        )
        db.add(outline)
    await db.commit()
    await db.refresh(outline)
    return outline


@router.post("/", response_model=OutlineOut)
async def create_outline(data: OutlineCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, data.novel_id, user)
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
        chapter_role=data.chapter_role,
        emotion_tone=data.emotion_tone,
        emotion_intensity=data.emotion_intensity,
        hook_type=data.hook_type,
        hook_strength=data.hook_strength,
    )
    db.add(outline)
    await db.commit()
    await db.refresh(outline)
    return outline


@router.patch("/{outline_id}", response_model=OutlineOut)
async def update_outline(outline_id: int, data: OutlineUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    outline = await get_owned_child(db, Outline, outline_id, user, "大纲")
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
async def delete_outline(outline_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    outline = await get_owned_child(db, Outline, outline_id, user, "大纲")
    await db.delete(outline)
    await db.commit()
    return {"ok": True}


@router.post("/{outline_id}/expand", response_model=list[OutlineOut])
async def expand_outline(outline_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    outline = await get_owned_child(db, Outline, outline_id, user, "大纲")
    if outline.start_chapter == outline.end_chapter:
        raise HTTPException(status_code=400, detail="单章大纲无需细化")

    novel = await db.get(Novel, outline.novel_id)

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
        f"3. 符合范围大纲的整体方向\n"
        f"4. 每章标出执行计划，取值只能从清单里选：\n"
        f"   chapter_role（本章定位）：{' / '.join(outline_plan.CHAPTER_ROLES)}\n"
        f"   emotion_tone（情绪基调）：{' / '.join(outline_plan.EMOTION_TONES)}\n"
        f"   hook_type（章尾钩子）：{' / '.join(outline_plan.HOOK_TYPES)}\n"
        f"   emotion_intensity、hook_strength 为 1-5 的整数\n"
        f"5. 高压章占 15%-20%，低压生活加信息整理合计不超过 15%，"
        f"同一种章尾钩子不要连用超过 2 章\n\n"
        f"请严格以 JSON 数组格式返回：\n"
        f'[{{"chapter": {outline.start_chapter}, "content": "...", "chapter_role": "推进", '
        f'"emotion_tone": "紧张", "emotion_intensity": 3, "hook_type": "突然揭示", '
        f'"hook_strength": 3}}, ...]'
    )

    messages = [
        {"role": "system", "content": "你是专业小说策划师，擅长拆解范围大纲为逐章细纲。只返回 JSON，不要其他文字。"},
        {"role": "user", "content": prompt},
    ]

    raw = await llm_client.dispatch_chat_complete(messages, model, api_format, temperature=0.7, max_tokens=4096)

    # Parse JSON from LLM response
    try:
        items = json.loads(repair_json(raw, expect="array"))
        if not isinstance(items, list):
            raise json.JSONDecodeError("top-level is not array", raw, 0)
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
            **outline_plan.clean_plan(item),
        )
        db.add(new_outline)
        created.append(new_outline)

    await db.commit()
    for o in created:
        await db.refresh(o)
    return created
