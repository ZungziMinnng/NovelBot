import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.character import Character
from app.models.novel import Novel
from app.schemas.character import CharacterCreate, CharacterUpdate, CharacterOut, EnhanceRequest, ImagePromptRequest
from app.agents import character_agent
from app.services.entity_embeddings import embed_character, remove_entity_embedding
from app.services import state_snapshot
from app.services.relevance_selector import select_character_appearance_context
from app.api.deps import CurrentUser, get_owned_novel, get_owned_child

router = APIRouter()

AVATARS_DIR = Path("data/avatars")


@router.get("/novel/{novel_id}", response_model=list[CharacterOut])
async def list_characters(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    result = await db.execute(
        select(Character).where(Character.novel_id == novel_id)
    )
    return result.scalars().all()


@router.get("/novel/{novel_id}/relationship-graph")
async def relationship_graph(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    result = await db.execute(
        select(Character).where(Character.novel_id == novel_id)
    )
    characters = result.scalars().all()

    nodes = [{"id": c.id, "name": c.name, "role": c.role} for c in characters]

    name_to_id = {c.name: c.id for c in characters}
    edge_map: dict[tuple[int, int], list[dict]] = {}

    for char in characters:
        state = char.current_state or {}
        for rel_type, rel_key in [("base", "base_relationships"), ("initial", "initial_relationships"), ("current", "relationship_changes")]:
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
async def get_character(character_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await get_owned_child(db, Character, character_id, user, "角色")


@router.post("/", response_model=CharacterOut)
async def create_character(data: CharacterCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, data.novel_id, user)
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
    character_id: int, data: CharacterUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    char = await get_owned_child(db, Character, character_id, user, "角色")
    fields = data.model_dump(exclude_none=True)
    for k, v in fields.items():
        setattr(char, k, v)
    # 手改的状态同步进最新快照，否则重新确认时的回滚会把它一起冲掉
    if "current_state" in fields:
        await state_snapshot.patch_latest(
            db, char.novel_id, "characters", char.id, char.current_state,
        )
    await db.commit()
    await db.refresh(char)
    await embed_character(char.novel_id, char)
    return char


@router.delete("/{character_id}")
async def delete_character(character_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    char = await get_owned_child(db, Character, character_id, user, "角色")
    novel_id = char.novel_id
    char_id = char.id
    if char.avatar_url:
        old_path = AVATARS_DIR / Path(char.avatar_url).name
        old_path.unlink(missing_ok=True)
    await db.delete(char)
    await db.commit()
    await remove_entity_embedding(novel_id, "character", char_id)
    return {"ok": True}


@router.post("/{character_id}/avatar", response_model=CharacterOut)
async def upload_avatar(
    character_id: int,
    user: CurrentUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    char = await get_owned_child(db, Character, character_id, user, "角色")

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
async def delete_avatar(character_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    char = await get_owned_child(db, Character, character_id, user, "角色")

    if char.avatar_url:
        old_path = AVATARS_DIR / Path(char.avatar_url).name
        if old_path.exists():
            old_path.unlink()
    char.avatar_url = ""
    await db.commit()
    await db.refresh(char)
    return char


@router.post("/{character_id}/refresh-appearance", response_model=CharacterOut)
async def refresh_appearance(character_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    char = await get_owned_child(db, Character, character_id, user, "角色")
    novel = await db.get(Novel, char.novel_id)

    appearance_selection = await select_character_appearance_context(
        db,
        novel.id,
        char.name,
        query=f"{char.name} {char.role or ''} 外貌 容貌 衣着 身形 气质",
        top_k=8,
    )
    appearance_context = "\n\n".join(appearance_selection.items)
    appearance = await character_agent.refresh_appearance(
        novel,
        char,
        appearance_context=appearance_context,
        context_source=appearance_selection.source,
    )
    sheet = dict(char.full_sheet or {})
    sheet["appearance"] = appearance
    char.full_sheet = sheet
    await db.commit()
    await db.refresh(char)
    await embed_character(char.novel_id, char)
    return char


@router.post("/{character_id}/enhance", response_model=CharacterOut)
async def enhance_character_endpoint(
    character_id: int,
    body: EnhanceRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    char = await get_owned_child(db, Character, character_id, user, "角色")
    novel = await db.get(Novel, char.novel_id)

    updated_sheet = await character_agent.enhance_character(novel, char, body.prompt, body.scope)
    char.full_sheet = updated_sheet
    await db.commit()
    await db.refresh(char)
    await embed_character(char.novel_id, char)
    return char


@router.post("/{character_id}/generate-sheet", response_model=CharacterOut)
async def generate_sheet(character_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    char = await get_owned_child(db, Character, character_id, user, "角色")
    novel = await db.get(Novel, char.novel_id)

    sheet = await character_agent.generate_character_sheet(novel, char)
    char.full_sheet = sheet
    await db.commit()
    await db.refresh(char)
    await embed_character(char.novel_id, char)
    return char


@router.post("/{character_id}/generate-image-prompt")
async def generate_image_prompt(
    character_id: int,
    body: ImagePromptRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    char = await get_owned_child(db, Character, character_id, user, "角色")
    novel = await db.get(Novel, char.novel_id)

    prompt = await character_agent.generate_image_prompt(novel, char, body.style)
    return {"prompt": prompt}


@router.post("/{character_id}/generate-history", response_model=CharacterOut)
async def generate_history(character_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    char = await get_owned_child(db, Character, character_id, user, "角色")
    novel = await db.get(Novel, char.novel_id)

    history, _in_tok, _out_tok = await character_agent.generate_character_history(db, novel, char)
    sheet = dict(char.full_sheet or {})
    sheet["character_history"] = history
    char.full_sheet = sheet
    await db.commit()
    await db.refresh(char)
    return char
