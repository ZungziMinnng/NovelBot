from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from openai import AuthenticationError as OpenAIAuthError
from app.database import get_db
from app.models.novel import Novel
from app.models.memory import Outline
from app.schemas.novel import NovelCreate, NovelUpdate, NovelOut, WizardStep2, WizardStep3, WizardStep4, WorldOptimizeRequest
from app.agents import world_agent, outline_agent, character_agent
from app.services import summarizer
from app.models.character import Character
from app.services import vector_store

router = APIRouter()


@router.get("/", response_model=list[NovelOut])
async def list_novels(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Novel).order_by(Novel.updated_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=NovelOut)
async def create_novel(data: NovelCreate, db: AsyncSession = Depends(get_db)):
    novel = Novel(**data.model_dump())
    db.add(novel)
    await db.commit()
    await db.refresh(novel)
    return novel


@router.get("/{novel_id}", response_model=NovelOut)
async def get_novel(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return novel


@router.patch("/{novel_id}", response_model=NovelOut)
async def update_novel(novel_id: int, data: NovelUpdate, db: AsyncSession = Depends(get_db)):
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(novel, k, v)
    await db.commit()
    await db.refresh(novel)
    return novel


@router.delete("/{novel_id}")
async def delete_novel(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    vector_store.delete_novel_collection(novel_id)
    await db.delete(novel)
    await db.commit()
    return {"ok": True}


# ── 向导接口 ──────────────────────────────────────────────────────────────

@router.post("/{novel_id}/optimize-world")
async def optimize_world_setting(novel_id: int, data: WorldOptimizeRequest, db: AsyncSession = Depends(get_db)):
    """使用 fast 模型优化世界观设定（使用前端传入的当前文本，而非 DB 中的旧值）"""
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    if not data.core_setting.strip():
        raise HTTPException(status_code=400, detail="当前世界观设定为空，无法优化")
    try:
        core_setting = await world_agent.optimize_world_setting(novel, data.core_setting)
    except OpenAIAuthError as e:
        raise HTTPException(
            status_code=400,
            detail=f"API Key 或模型名无效，请前往「设置」页面检查配置。原始错误：{e}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"调用 LLM 失败：{e}")
    novel.core_setting = core_setting
    await world_agent.embed_world_setting(novel.id, core_setting)
    await db.commit()
    return {"core_setting": core_setting}


@router.post("/{novel_id}/book-summary")
async def refresh_book_summary(novel_id: int, db: AsyncSession = Depends(get_db)):
    """从所有已确认章节的摘要重新生成全书概要，存入 novel.book_summary"""
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        book_summary = await summarizer.generate_book_summary(db, novel)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成全书概要失败：{e}")
    await db.commit()
    return {"book_summary": book_summary}


@router.post("/wizard/world")
async def wizard_expand_world(data: WizardStep2, db: AsyncSession = Depends(get_db)):
    """Step 2: 扩写世界观"""
    novel = await db.get(Novel, data.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        core_setting = await world_agent.expand_world_setting(
            novel, data.raw_world_setting, data.raw_world_rules
        )
    except OpenAIAuthError as e:
        raise HTTPException(
            status_code=400,
            detail=f"API Key 或模型名无效，请前往「设置」页面检查配置。原始错误：{e}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"调用 LLM 失败：{e}")
    novel.core_setting = core_setting
    await world_agent.embed_world_setting(novel.id, core_setting)
    await db.commit()
    return {"core_setting": core_setting}


@router.post("/wizard/characters")
async def wizard_generate_characters(data: WizardStep3, db: AsyncSession = Depends(get_db)):
    """Step 3: 批量创建并生成角色卡"""
    novel = await db.get(Novel, data.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    created = []
    for char_data in data.characters:
        char = Character(
            novel_id=novel.id,
            name=char_data.get("name", ""),
            role=char_data.get("role", "配角"),
            age=str(char_data.get("age", "")),
            description=char_data.get("description", ""),
        )
        db.add(char)
        await db.flush()
        try:
            sheet = await character_agent.generate_character_sheet(novel, char)
        except OpenAIAuthError as e:
            await db.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"API Key 或模型名无效，请前往「设置」页面检查配置。原始错误：{e}"
            )
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"调用 LLM 失败：{e}")
        char.full_sheet = sheet
        char.current_state = character_agent.init_character_state(char)
        await character_agent.embed_character(novel.id, char)
        created.append({"id": char.id, "name": char.name, "sheet": sheet})

    await db.commit()
    return {"characters": created}


@router.post("/wizard/outline")
async def wizard_generate_outline(data: WizardStep4, db: AsyncSession = Depends(get_db)):
    """Step 4: 生成章节大纲"""
    novel = await db.get(Novel, data.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 清除旧大纲
    result = await db.execute(select(Outline).where(Outline.novel_id == novel.id))
    for o in result.scalars().all():
        await db.delete(o)

    try:
        outlines = await outline_agent.generate_chapter_outlines(db, novel)
    except OpenAIAuthError as e:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"API Key 或模型名无效，请前往「设置」页面检查配置。原始错误：{e}"
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"调用 LLM 失败：{e}")

    await db.commit()

    return {
        "outlines": [
            {"chapter_number": o.chapter_number, "title": o.title, "content": o.content}
            for o in outlines
        ]
    }
