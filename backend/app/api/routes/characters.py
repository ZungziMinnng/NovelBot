from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.character import Character
from app.models.novel import Novel
from app.schemas.character import CharacterCreate, CharacterUpdate, CharacterOut
from app.agents import character_agent

router = APIRouter()


@router.get("/novel/{novel_id}", response_model=list[CharacterOut])
async def list_characters(novel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Character).where(Character.novel_id == novel_id)
    )
    return result.scalars().all()


@router.get("/{character_id}", response_model=CharacterOut)
async def get_character(character_id: int, db: AsyncSession = Depends(get_db)):
    char = await db.get(Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")
    return char


@router.post("/", response_model=CharacterOut)
async def create_character(data: CharacterCreate, db: AsyncSession = Depends(get_db)):
    char = Character(**data.model_dump())
    db.add(char)
    await db.flush()

    if not char.full_sheet:
        novel = await db.get(Novel, char.novel_id)
        if novel:
            sheet = await character_agent.generate_character_sheet(novel, char)
            char.full_sheet = sheet

    if not char.current_state:
        char.current_state = character_agent.init_character_state(char)

    await character_agent.embed_character(char.novel_id, char)
    await db.commit()
    await db.refresh(char)
    return char


@router.patch("/{character_id}", response_model=CharacterOut)
async def update_character(
    character_id: int, data: CharacterUpdate, db: AsyncSession = Depends(get_db)
):
    char = await db.get(Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(char, k, v)
    await character_agent.embed_character(char.novel_id, char)
    await db.commit()
    await db.refresh(char)
    return char


@router.delete("/{character_id}")
async def delete_character(character_id: int, db: AsyncSession = Depends(get_db)):
    char = await db.get(Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")
    await db.delete(char)
    await db.commit()
    return {"ok": True}
