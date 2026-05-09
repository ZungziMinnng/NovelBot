import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.character import Character
from app.models.novel import Novel
from app.schemas.character import CharacterCreate, CharacterUpdate, CharacterOut, EnhanceRequest, ImagePromptRequest
from app.agents import character_agent
from app.services.entity_embeddings import embed_character, remove_entity_embedding

router = APIRouter()

AVATARS_DIR = Path("data/avatars")


@router.get("/novel/{novel_id}", response_model=list[CharacterOut])
async def list_characters(novel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Character).where(Character.novel_id == novel_id)
    )
    return result.scalars().all()


@router.get("/novel/{novel_id}/relationship-graph")
async def relationship_graph(novel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Character).where(Character.novel_id == novel_id)
    )
    characters = result.scalars().all()

    nodes = [{"id": c.id, "name": c.name, "role": c.role} for c in characters]

    name_to_id = {c.name: c.id for c in characters}
    edge_map: dict[tuple[int, int], list[dict]] = {}

    for char in characters:
        state = char.current_state or {}
        for rel_type, rel_key in [("initial", "initial_relationships"), ("current", "relationship_changes")]:
            rels = state.get(rel_key, {})
            if not isinstance(rels, dict):
                continue
            for target_name, desc in rels.items():
                target_id = name_to_id.get(target_name)
                if target_id is None or target_id == char.id:
                    continue
                pair = (min(char.id, target_id), max(char.id, target_id))
                if pair not in edge_map:
                    edge_map[pair] = []
                edge_map[pair].append({"from": char.name, "desc": str(desc), "type": rel_type})

    edges = [
        {"source": pair[0], "target": pair[1], "labels": labels}
        for pair, labels in edge_map.items()
    ]

    return {"nodes": nodes, "edges": edges}


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

    await db.commit()
    await db.refresh(char)
    await embed_character(char.novel_id, char)
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
    await db.commit()
    await db.refresh(char)
    await embed_character(char.novel_id, char)
    return char


@router.delete("/{character_id}")
async def delete_character(character_id: int, db: AsyncSession = Depends(get_db)):
    char = await db.get(Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")
    novel_id = char.novel_id
    char_id = char.id
    await db.delete(char)
    await db.commit()
    await remove_entity_embedding(novel_id, "character", char_id)
    return {"ok": True}


@router.post("/{character_id}/avatar", response_model=CharacterOut)
async def upload_avatar(
    character_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    char = await db.get(Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")

    if char.avatar_url:
        old_path = AVATARS_DIR / Path(char.avatar_url).name
        if old_path.exists():
            old_path.unlink()

    ext = Path(file.filename or "img").suffix or ".png"
    filename = f"{character_id}_{uuid.uuid4().hex[:8]}{ext}"
    dest = AVATARS_DIR / filename
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(await file.read())

    char.avatar_url = f"/api/avatars/{filename}"
    await db.commit()
    await db.refresh(char)
    return char


@router.delete("/{character_id}/avatar", response_model=CharacterOut)
async def delete_avatar(character_id: int, db: AsyncSession = Depends(get_db)):
    char = await db.get(Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")

    if char.avatar_url:
        old_path = AVATARS_DIR / Path(char.avatar_url).name
        if old_path.exists():
            old_path.unlink()
    char.avatar_url = ""
    await db.commit()
    await db.refresh(char)
    return char


@router.post("/{character_id}/refresh-appearance", response_model=CharacterOut)
async def refresh_appearance(character_id: int, db: AsyncSession = Depends(get_db)):
    char = await db.get(Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")
    novel = await db.get(Novel, char.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    appearance = await character_agent.refresh_appearance(novel, char)
    sheet = dict(char.full_sheet or {})
    sheet["appearance"] = appearance
    char.full_sheet = sheet
    await db.commit()
    await db.refresh(char)
    return char


@router.post("/{character_id}/enhance", response_model=CharacterOut)
async def enhance_character_endpoint(
    character_id: int,
    body: EnhanceRequest,
    db: AsyncSession = Depends(get_db),
):
    char = await db.get(Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")
    novel = await db.get(Novel, char.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    updated_sheet = await character_agent.enhance_character(novel, char, body.prompt, body.scope)
    char.full_sheet = updated_sheet
    await db.commit()
    await db.refresh(char)
    await embed_character(char.novel_id, char)
    return char


@router.post("/{character_id}/generate-image-prompt")
async def generate_image_prompt(
    character_id: int,
    body: ImagePromptRequest,
    db: AsyncSession = Depends(get_db),
):
    char = await db.get(Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")
    novel = await db.get(Novel, char.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    prompt = await character_agent.generate_image_prompt(novel, char, body.style)
    return {"prompt": prompt}


@router.post("/{character_id}/generate-history", response_model=CharacterOut)
async def generate_history(character_id: int, db: AsyncSession = Depends(get_db)):
    char = await db.get(Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")
    novel = await db.get(Novel, char.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    history, _in_tok, _out_tok = await character_agent.generate_character_history(db, novel, char)
    sheet = dict(char.full_sheet or {})
    sheet["character_history"] = history
    char.full_sheet = sheet
    await db.commit()
    await db.refresh(char)
    return char
