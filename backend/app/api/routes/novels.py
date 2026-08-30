from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, delete as sql_delete, update as sql_update
from openai import AuthenticationError as OpenAIAuthError
from app.database import get_db, AsyncSessionLocal
from app.models.novel import Novel
from app.models.memory import Outline, Memory
from app.models.chapter import Chapter
from app.schemas.novel import NovelCreate, NovelUpdate, NovelOut, WizardStep2, WizardStep3, WizardStep4, WorldOptimizeRequest
from app.agents import world_agent, outline_agent, character_agent, build_agent
from app.agents.writer import _compose_system_prompt
from app.prompts.loader import render
from app.prompts import genre_cards
from app.services import summarizer, context_builder, llm_client, entity_embeddings
from app.services.llm_json import repair_json
from app.services.world_rules_sync import seed_or_sync
from app.models.character import Character
from app.models.world_entity import WorldEntity
from app.models.location import Location
from app.models.faction import Faction
from app.models.technique import Technique
from app.models.novel_note import NovelNote
from app.models.volume import Volume
from app.models.worldview_change import WorldviewChange
from app.models.story_thread import StoryThread
from app.models.llm_usage import LlmUsage
from app.models.model_library import ModelEntry
from app.services import vector_store
from app.models.memory import Memory
from app.api.deps import CurrentUser, get_owned_novel

router = APIRouter()


async def _reindex_after_embedding_change(db, novel):
    """嵌入模型变更后：删除旧向量集合，配置新嵌入函数，重建全部向量。"""
    import logging
    log = logging.getLogger(__name__)
    log.info("embedding_model changed for novel %d, rebuilding vector store", novel.id)

    vector_store.delete_novel_collection(novel.id)
    await vector_store.ensure_embedding_configured(novel.id, db)

    await entity_embeddings.reindex_all_entities(db, novel.id)

    if novel.core_setting:
        await world_agent.embed_world_setting(novel.id, novel.core_setting)

    result = await db.execute(
        select(Memory).where(
            Memory.novel_id == novel.id,
            Memory.memory_type == "chapter_summary",
            Memory.content != "",
        )
    )
    summaries = result.scalars().all()
    if summaries:
        batch = []
        for m in summaries:
            doc_id = m.embedding_id or f"summary_v{m.volume}_ch{m.chapter_number}"
            batch.append((doc_id, m.content, {
                "type": "chapter_summary",
                "volume": m.volume,
                "chapter_number": m.chapter_number,
                "importance": m.importance,
            }))
        await vector_store.astore_texts_batch(novel.id, batch)

    log.info("vector store rebuilt for novel %d: %d summaries re-embedded", novel.id, len(summaries))


@router.get("/dashboard")
async def dashboard(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    novels = (await db.execute(select(Novel).where(Novel.user_id == user.id))).scalars().all()
    total_novels = len(novels)
    novel_ids = [n.id for n in novels]

    word_rows = (await db.execute(
        select(Chapter.novel_id, func.coalesce(func.sum(Chapter.word_count), 0))
        .where(Chapter.novel_id.in_(novel_ids))
        .group_by(Chapter.novel_id)
    )).all() if novel_ids else []
    novel_words = {row[0]: row[1] for row in word_rows}
    total_words = sum(novel_words.values())

    if novel_ids:
        entity_count = (await db.execute(
            select(func.count(WorldEntity.id)).where(WorldEntity.novel_id.in_(novel_ids))
        )).scalar() or 0
        technique_count = (await db.execute(
            select(func.count(Technique.id)).where(Technique.novel_id.in_(novel_ids))
        )).scalar() or 0
    else:
        entity_count = technique_count = 0
    total_entities = entity_count + technique_count

    return {
        "total_novels": total_novels,
        "total_words": total_words,
        "total_entities": total_entities,
        "novel_words": novel_words,
    }


@router.get("/genre-cards")
async def list_genre_cards(user: CurrentUser):
    """可选的题材腔调卡（卡名 + 正文），供设置页选择与预览。

    路由声明必须在 /{novel_id} 之前，否则 "genre-cards" 会被当成 novel_id。
    """
    return {"off_value": genre_cards.OFF, "cards": genre_cards.list_cards()}


@router.get("/", response_model=list[NovelOut])
async def list_novels(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Novel).where(Novel.user_id == user.id).order_by(Novel.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=NovelOut)
async def create_novel(data: NovelCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    novel = Novel(**data.model_dump(), user_id=user.id)
    db.add(novel)
    await db.commit()
    await db.refresh(novel)
    return novel


@router.get("/{novel_id}", response_model=NovelOut)
async def get_novel(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await get_owned_novel(db, novel_id, user)


@router.get("/{novel_id}/overview")
async def novel_overview(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """预览用轻量聚合：卷数/章节数/总字数/角色名单，不带章节正文。"""
    novel = await get_owned_novel(db, novel_id, user)

    volume_count = (await db.execute(
        select(func.count(Volume.id)).where(Volume.novel_id == novel_id)
    )).scalar() or 0
    if volume_count == 0:
        # 未建卷数据的老书：按章节表里出现过的卷号计数
        volume_count = (await db.execute(
            select(func.count(func.distinct(Chapter.volume)))
            .where(Chapter.novel_id == novel_id)
        )).scalar() or 0

    chapter_count = (await db.execute(
        select(func.count(Chapter.id)).where(Chapter.novel_id == novel_id)
    )).scalar() or 0
    total_words = (await db.execute(
        select(func.coalesce(func.sum(Chapter.word_count), 0))
        .where(Chapter.novel_id == novel_id)
    )).scalar() or 0

    char_rows = (await db.execute(
        select(Character.name, Character.role)
        .where(Character.novel_id == novel_id)
        .order_by(Character.id)
    )).all()
    role_order = {"主角": 0, "反派": 1, "配角": 2}
    characters = sorted(
        ({"name": name, "role": role} for name, role in char_rows),
        key=lambda c: role_order.get(c["role"], 3),
    )

    return {
        "volume_count": volume_count,
        "chapter_count": chapter_count,
        "total_words": total_words,
        "characters": characters,
    }


@router.patch("/{novel_id}", response_model=NovelOut)
async def update_novel(novel_id: int, data: NovelUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    novel = await get_owned_novel(db, novel_id, user)
    updates = data.model_dump(exclude_none=True)
    core_setting_changed = "core_setting" in updates and updates["core_setting"] != novel.core_setting
    embedding_changed = "embedding_model" in updates and updates["embedding_model"] != novel.embedding_model
    for k, v in updates.items():
        setattr(novel, k, v)
    try:
        await db.commit()
        await db.refresh(novel)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("update_novel commit failed")
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")
    if core_setting_changed:
        await world_agent.embed_world_setting(novel.id, novel.core_setting)
    if embedding_changed:
        await _reindex_after_embedding_change(db, novel)
    return novel


@router.delete("/{novel_id}")
async def delete_novel(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    novel = await get_owned_novel(db, novel_id, user)
    # llm_usage 无外键无 relationship，级联删不到，手动清理
    await db.execute(sql_delete(LlmUsage).where(LlmUsage.novel_id == novel_id))
    # locations.parent_id 自引用，ORM 级联删除顺序不保证父先子后，先置空避免外键违规
    await db.execute(
        sql_update(Location).where(Location.novel_id == novel_id).values(parent_id=None)
    )
    # memories.chapter_id 指向 chapters，但 Memory 与 Chapter 之间没有 relationship，
    # ORM 看不出两个集合的先后依赖，会先删 chapters 撞上外键。同样先置空
    await db.execute(
        sql_update(Memory).where(Memory.novel_id == novel_id).values(chapter_id=None)
    )
    await db.delete(novel)
    await db.commit()
    # SQL 提交成功后再删向量，避免 SQL 失败时向量已丢
    vector_store.delete_novel_collection(novel_id)
    return {"ok": True}


# ── 复制整本小说 ────────────────────────────────────────────────────────────

class _DuplicateBody(BaseModel):
    mode: str = "full"  # full=全部（含章节/记忆） / settings=仅设定
    title: str | None = None


def _clone_cols(obj, exclude: set[str], **overrides) -> dict:
    """复制 ORM 行的标量列值（排除主键/外键/时间戳等），叠加 overrides。"""
    data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in exclude}
    data.update(overrides)
    return data


@router.post("/{novel_id}/duplicate", response_model=NovelOut)
async def duplicate_novel(novel_id: int, body: _DuplicateBody, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """深拷贝整本小说：SQL 行重映射 id + 直接复制向量（不重嵌入）。
    mode=full 含章节与对应记忆；mode=settings 仅复制设定并重置写作进度。"""
    import re, logging
    log = logging.getLogger(__name__)

    src = await get_owned_novel(db, novel_id, user)

    full = body.mode != "settings"
    CHILD_EXCLUDE = {"id", "novel_id", "created_at", "updated_at"}

    # 1. Novel 本体
    novel_overrides: dict = {"title": (body.title or f"{src.title} - 副本")}
    if not full:
        novel_overrides.update(current_volume=1, current_chapter=0, book_summary="")
    new_novel = Novel(**_clone_cols(src, {"id", "created_at", "updated_at"}, **novel_overrides))
    db.add(new_novel)
    await db.flush()
    new_id = new_novel.id

    async def _load(model):
        return (await db.execute(select(model).where(model.novel_id == novel_id))).scalars().all()

    # 2. 角色
    char_pairs = [(c.id, Character(**_clone_cols(c, CHILD_EXCLUDE, novel_id=new_id))) for c in await _load(Character)]
    for _, nc in char_pairs:
        db.add(nc)

    # 3. 道具/系统
    entity_pairs = [(e.id, WorldEntity(**_clone_cols(e, CHILD_EXCLUDE, novel_id=new_id))) for e in await _load(WorldEntity)]
    for _, ne in entity_pairs:
        db.add(ne)

    # 4. 地点（parent_id 自引用，先建后补）
    loc_pairs = []
    for l in await _load(Location):
        nl = Location(**_clone_cols(l, CHILD_EXCLUDE | {"parent_id"}, novel_id=new_id))
        db.add(nl)
        loc_pairs.append((l, nl))

    # 5. 势力（location_id 指向地点）
    fac_src = await _load(Faction)

    # 6. 功法 / 7. 笔记 / 8. 分卷 / 9. 世界观变更 / 10. 大纲
    tech_pairs = [(t.id, Technique(**_clone_cols(t, CHILD_EXCLUDE, novel_id=new_id))) for t in await _load(Technique)]
    for _, nt in tech_pairs:
        db.add(nt)
    note_pairs = [(n.id, NovelNote(**_clone_cols(n, CHILD_EXCLUDE, novel_id=new_id))) for n in await _load(NovelNote)]
    for _, nn in note_pairs:
        db.add(nn)
    for v in await _load(Volume):
        db.add(Volume(**_clone_cols(v, CHILD_EXCLUDE, novel_id=new_id)))
    for w in await _load(WorldviewChange):
        db.add(WorldviewChange(**_clone_cols(w, CHILD_EXCLUDE, novel_id=new_id)))
    for thread in await _load(StoryThread):
        db.add(StoryThread(**_clone_cols(thread, CHILD_EXCLUDE, novel_id=new_id)))
    for o in await _load(Outline):
        db.add(Outline(**_clone_cols(o, CHILD_EXCLUDE, novel_id=new_id)))

    await db.flush()
    char_map = {old: nc.id for old, nc in char_pairs}
    entity_map = {old: ne.id for old, ne in entity_pairs}
    loc_map = {l.id: nl.id for l, nl in loc_pairs}
    tech_map = {old: nt.id for old, nt in tech_pairs}
    note_map = {old: nn.id for old, nn in note_pairs}

    # 补地点 parent_id
    for l, nl in loc_pairs:
        if l.parent_id and l.parent_id in loc_map:
            nl.parent_id = loc_map[l.parent_id]

    # 势力重映射 location_id
    fac_pairs = []
    for f in fac_src:
        nf = Faction(**_clone_cols(
            f, CHILD_EXCLUDE | {"location_id"}, novel_id=new_id,
            location_id=loc_map.get(f.location_id) if f.location_id else None,
        ))
        db.add(nf)
        fac_pairs.append((f.id, nf))

    # 11+12. 章节 + 记忆（仅 full）
    chapter_map: dict[int, int] = {}
    if full:
        chap_pairs = [(ch.id, Chapter(**_clone_cols(ch, CHILD_EXCLUDE, novel_id=new_id))) for ch in await _load(Chapter)]
        for _, nch in chap_pairs:
            db.add(nch)
        await db.flush()
        chapter_map = {old: nch.id for old, nch in chap_pairs}

        for m in await _load(Memory):
            new_chapter_id = chapter_map.get(m.chapter_id) if m.chapter_id else None
            new_emb = m.embedding_id
            if m.embedding_id and m.chapter_id and m.chapter_id in chapter_map:
                new_emb = m.embedding_id.replace(
                    f"chapter_{m.chapter_id}_", f"chapter_{chapter_map[m.chapter_id]}_", 1
                )
            db.add(Memory(**_clone_cols(
                m, {"id", "created_at", "novel_id", "chapter_id", "embedding_id"},
                novel_id=new_id, chapter_id=new_chapter_id, embedding_id=new_emb,
            )))

    await db.commit()
    await db.refresh(new_novel)

    # 13. 向量复制（直接搬运 embedding，不重新嵌入）
    fac_map = {old: nf.id for old, nf in fac_pairs}
    simple_specs = [
        ("character_", char_map, "entity_id"),
        ("entity_item_", entity_map, "entity_id"),
        ("entity_system_", entity_map, "entity_id"),
        ("location_", loc_map, "entity_id"),
        ("faction_", fac_map, "entity_id"),
        ("technique_", tech_map, "entity_id"),
        ("note_", note_map, "note_id"),
    ]

    def _remap_doc(doc_id: str, meta: dict):
        meta = dict(meta or {})
        m = re.match(r"^world_setting_(\d+)_chunk_(\d+)$", doc_id)
        if m:
            return f"world_setting_{new_id}_chunk_{m.group(2)}", meta
        m = re.match(r"^chapter_(\d+)_summary(.*)$", doc_id)
        if m:
            if not full:
                return None
            new_ch = chapter_map.get(int(m.group(1)))
            if new_ch is None:
                return None
            return f"chapter_{new_ch}_summary{m.group(2)}", meta
        for prefix, id_map, meta_key in simple_specs:
            if doc_id.startswith(prefix):
                rest = doc_id[len(prefix):]
                if not rest.isdigit():
                    return None
                new = id_map.get(int(rest))
                if new is None:
                    return None
                if meta_key in meta:
                    meta[meta_key] = new
                return f"{prefix}{new}", meta
        return None

    try:
        # 先按新小说的 embedding_model 配置嵌入函数，确保新集合以正确维度创建
        await vector_store.ensure_embedding_configured(new_id, db)
        data = await vector_store.aget_all_docs(novel_id)
        old_ids = data["ids"]
        embs, docs, metas = data["embeddings"], data["documents"], data["metadatas"]
        new_ids, new_embs, new_docs, new_metas = [], [], [], []
        for i, did in enumerate(old_ids):
            remapped = _remap_doc(did, metas[i] if i < len(metas) else {})
            if remapped is None:
                continue
            ndid, nmeta = remapped
            new_ids.append(ndid)
            new_embs.append(embs[i])
            new_docs.append(docs[i] if i < len(docs) else "")
            new_metas.append(nmeta)
        if new_ids:
            await vector_store.aadd_with_embeddings(new_id, new_ids, new_embs, new_docs, new_metas)
        log.info("duplicate novel %d → %d: copied %d/%d vectors", novel_id, new_id, len(new_ids), len(old_ids))
    except Exception:
        log.warning("复制向量失败（SQL 已提交，可后续 reindex 重建）: novel %d → %d", novel_id, new_id, exc_info=True)

    return new_novel


# ── 搜索 ─────────────────────────────────────────────────────────────────

@router.get("/{novel_id}/search")
async def search_novel(
    novel_id: int,
    user: CurrentUser,
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """全文搜索：向量语义检索 + SQL 模糊匹配"""
    await get_owned_novel(db, novel_id, user)

    import asyncio
    pattern = f"%{q}%"

    async def _vector_search():
        return await vector_store.asearch_similar_with_meta(novel_id, q, top_k=10)

    async def _sql_characters():
        r = await db.execute(
            select(Character).where(
                Character.novel_id == novel_id,
                or_(Character.name.ilike(pattern), Character.description.ilike(pattern)),
            )
        )
        return [{"id": c.id, "name": c.name, "role": c.role, "description": c.description} for c in r.scalars()]

    async def _sql_entities(entity_type: str):
        r = await db.execute(
            select(WorldEntity).where(
                WorldEntity.novel_id == novel_id,
                WorldEntity.type == entity_type,
                or_(WorldEntity.name.ilike(pattern), WorldEntity.description.ilike(pattern)),
            )
        )
        return [{"id": e.id, "name": e.name, "type": e.type, "description": e.description} for e in r.scalars()]

    async def _sql_locations():
        r = await db.execute(
            select(Location).where(
                Location.novel_id == novel_id,
                or_(Location.name.ilike(pattern), Location.description.ilike(pattern)),
            )
        )
        return [{"id": l.id, "name": l.name, "type": l.type, "description": l.description} for l in r.scalars()]

    async def _sql_factions():
        r = await db.execute(
            select(Faction).where(
                Faction.novel_id == novel_id,
                or_(Faction.name.ilike(pattern), Faction.description.ilike(pattern)),
            )
        )
        return [{"id": f.id, "name": f.name, "type": f.type, "description": f.description} for f in r.scalars()]

    async def _sql_techniques():
        r = await db.execute(
            select(Technique).where(
                Technique.novel_id == novel_id,
                or_(Technique.name.ilike(pattern), Technique.description.ilike(pattern)),
            )
        )
        return [{"id": t.id, "name": t.name, "type": t.type, "description": t.description} for t in r.scalars()]

    async def _sql_notes():
        r = await db.execute(
            select(NovelNote).where(
                NovelNote.novel_id == novel_id,
                or_(NovelNote.title.ilike(pattern), NovelNote.content.ilike(pattern)),
            )
        )
        return [{"id": n.id, "title": n.title, "content": n.content} for n in r.scalars()]

    vec_results, characters, items, systems, locations, factions, techniques, notes = await asyncio.gather(
        _vector_search(),
        _sql_characters(),
        _sql_entities("item"),
        _sql_entities("system"),
        _sql_locations(),
        _sql_factions(),
        _sql_techniques(),
        _sql_notes(),
    )

    chapters = []
    note_hits = []
    for hit in vec_results:
        meta = hit.get("metadata") or {}
        doc_type = meta.get("type", "")
        score = round(1 - hit.get("distance", 1), 3)
        if doc_type == "chapter_summary":
            chapters.append({
                "chapter_number": meta.get("chapter_number"),
                "summary": hit["text"],
                "score": score,
            })
        elif doc_type in ("novel_note", "note"):
            note_hits.append({
                "title": meta.get("title", ""),
                "content": hit["text"],
                "score": score,
            })
    chapters.sort(key=lambda c: c.get("chapter_number") or 0)

    return {
        "chapters": chapters,
        "characters": characters,
        "items": items,
        "systems": systems,
        "locations": locations,
        "factions": factions,
        "techniques": techniques,
        "notes": notes + note_hits,
    }


# ── 向导接口 ──────────────────────────────────────────────────────────────

@router.post("/{novel_id}/optimize-world")
async def optimize_world_setting(novel_id: int, data: WorldOptimizeRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """使用 fast 模型优化世界观设定（使用前端传入的当前文本，而非 DB 中的旧值）"""
    novel = await get_owned_novel(db, novel_id, user)

    # 分区块模式：针对单个区块生成（空内容）或优化（有内容），只返回文本、不入库、不重建向量。
    # 由前端「保存世界观」统一合并落库。
    if data.section:
        try:
            text = await world_agent.optimize_world_section(novel, data.section, data.core_setting)
        except OpenAIAuthError as e:
            raise HTTPException(
                status_code=400,
                detail=f"API Key 或模型名无效，请前往「设置」页面检查配置。原始错误：{e}"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"调用 LLM 失败：{e}")
        return {"core_setting": text}

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
    await seed_or_sync(db, novel)
    await world_agent.embed_world_setting(novel.id, novel.core_setting)
    await db.commit()
    return {"core_setting": novel.core_setting}


@router.post("/{novel_id}/book-summary")
async def refresh_book_summary(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """从所有已确认章节的摘要重新生成全书概要，存入 novel.book_summary"""
    novel = await get_owned_novel(db, novel_id, user)
    try:
        book_summary = await summarizer.generate_book_summary(db, novel)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成全书概要失败：{e}")
    await db.commit()
    return {"book_summary": book_summary}


@router.post("/wizard/world")
async def wizard_expand_world(data: WizardStep2, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Step 2: 扩写世界观"""
    novel = await get_owned_novel(db, data.novel_id, user)
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
    await seed_or_sync(db, novel)
    await world_agent.embed_world_setting(novel.id, novel.core_setting)
    await db.commit()
    return {"core_setting": novel.core_setting}


@router.post("/wizard/characters")
async def wizard_generate_characters(data: WizardStep3, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Step 3: 批量创建并生成角色卡"""
    novel = await get_owned_novel(db, data.novel_id, user)

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
        # 作者在向导里填了的栏位当硬要求传下去，AI 据此扩写而不是另起一套
        given = {
            k: str(char_data.get(k, "")).strip()
            for k in ("personality", "appearance", "speech_style")
            if str(char_data.get(k, "")).strip()
        }
        try:
            sheet = await character_agent.generate_character_sheet(novel, char, given=given)
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
        created.append({"id": char.id, "name": char.name, "sheet": sheet})

    await db.commit()
    return {"characters": created}


@router.post("/wizard/outline")
async def wizard_generate_outline(data: WizardStep4, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Step 4: 生成章节大纲"""
    novel = await get_owned_novel(db, data.novel_id, user)

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
    except RuntimeError as e:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"大纲生成失败：{e}")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"调用 LLM 失败：{e}")

    if not outlines:
        await db.rollback()
        raise HTTPException(status_code=502, detail="大纲生成失败：模型没有返回任何大纲内容")

    await db.commit()

    return {
        "outlines": [
            {
                "chapter_number": o.chapter_number,
                "start_chapter": o.start_chapter,
                "end_chapter": o.end_chapter,
                "title": o.title,
                "content": o.content,
            }
            for o in outlines
        ]
    }


@router.get("/{novel_id}/context-preview")
async def get_context_preview(
    novel_id: int,
    user: CurrentUser,
    chapter_number: int | None = None,
    instruction: str = "",
    target_words: int = 2500,
    db: AsyncSession = Depends(get_db),
):
    """预览 Writer 在生成指定章节时收到的完整上下文（JSON 结构化）。"""
    novel = await get_owned_novel(db, novel_id, user)

    if chapter_number is None:
        chapter_number = (novel.current_chapter or 0) + 1
    if chapter_number < 1:
        chapter_number = 1

    ctx = await context_builder.build_generation_context(
        session=db,
        novel=novel,
        chapter_number=chapter_number,
        volume=novel.current_volume or 1,
        scene_hint=instruction,
        target_words=target_words,
    )
    context_meta = ctx.get("_meta", [])
    context_block, chars_block, task_instruction = context_builder.format_context_for_writer(
        ctx, instruction=instruction, target_words=target_words,
    )

    def _est_tokens(text: str) -> int:
        """粗估中文 token 数（中文约 1.5 token/字，英文约 1 token/4字符）"""
        if not text:
            return 0
        cn_chars = sum(1 for c in text if '一' <= c <= '鿿')
        other_chars = len(text) - cn_chars
        return int(cn_chars * 1.5 + other_chars * 0.25)

    sections = {
        "core_setting": ctx.get("core_setting", ""),
        "book_summary": ctx.get("book_summary", ""),
        "arc_summary": ctx.get("arc_summary", ""),
        "chapter_outline": ctx.get("chapter_outline", ""),
        "rolling_summary": ctx.get("rolling_summary", ""),
        "rag_context": ctx.get("rag_context", ""),
        "notes_context": "\n".join(f"【{n['title']}】{n['content']}" for n in ctx.get("notes", [])),
        "recent_text": ctx.get("recent_text", ""),
    }
    section_tokens = {k: _est_tokens(v) for k, v in sections.items()}

    import json as _json

    def _chars_text(characters: list) -> str:
        return "".join(
            f"【{c['name']}·{c['role']}】{c['description']}\n"
            + "".join(f"  {k}：{v}\n" for k, v in (c.get("full_sheet") or {}).items() if v)
            + (f"  状态：{_json.dumps(c.get('state') or {}, ensure_ascii=False)}\n" if c.get("state") else "")
            for c in characters
        )

    def _entities_text(entities: list) -> str:
        return "".join(
            f"【{e['name']}·{e['type']}】{e['description']}\n"
            + (f"  状态：{_json.dumps(e.get('state') or {}, ensure_ascii=False)}\n" if e.get("state") else "")
            for e in entities
        )

    def _locations_text(locations: list) -> str:
        return "".join(
            f"【{loc['name']}·{loc['type']}】{loc['description']}\n"
            + (f"  状态：{_json.dumps(loc.get('state') or {}, ensure_ascii=False)}\n" if loc.get("state") else "")
            for loc in locations
        )

    def _factions_text(factions: list) -> str:
        return "".join(
            f"【{f['name']}·{f.get('alignment', '')}】{f.get('type', '')} {f.get('description', '')}\n"
            for f in factions
        )

    def _techniques_text(techniques: list) -> str:
        return "".join(
            f"【{t['name']}·{t.get('type', '')}】{t.get('description', '')}\n"
            for t in techniques
        )

    all_entities = ctx.get("world_entities", [])
    items_list = [e for e in all_entities if e.get("type") == "item"]
    systems_list = [e for e in all_entities if e.get("type") == "system"]

    chars_tokens = _est_tokens(_chars_text(ctx.get("characters", [])))
    items_tokens = _est_tokens(_entities_text(items_list))
    systems_tokens = _est_tokens(_entities_text(systems_list))
    locations_tokens = _est_tokens(_locations_text(ctx.get("locations", [])))
    factions_tokens = _est_tokens(_factions_text(ctx.get("factions", [])))
    techniques_tokens = _est_tokens(_techniques_text(ctx.get("techniques", [])))
    task_tokens = _est_tokens(task_instruction)
    # 与 writer.stream_chapter 同一套组装逻辑，预览才能当规则是否注入的验证面
    system_content, system_source = _compose_system_prompt(
        (novel.writer_system_prompt or "").strip(),
        render(
            "writer.jinja2",
            genre=ctx.get("genre", ""),
            writing_style=ctx.get("writing_style", ""),
            target_words=target_words,
            chapter_number=ctx.get("chapter_number"),
        ),
        ctx,
    )
    system_tokens = _est_tokens(system_content)
    total_est_tokens = (
        sum(section_tokens.values())
        + chars_tokens + items_tokens + systems_tokens + locations_tokens + factions_tokens + techniques_tokens
        + task_tokens + system_tokens
    )
    dynamic_budget = ctx.get("_budget", {})
    expected_output_tokens = int(dynamic_budget.get("output_reserve") or 0)
    pricing = ctx.get("_pricing", {})
    input_price_cny = float(pricing.get("input_price_cny_per_million") or 0)
    output_price_cny = float(pricing.get("output_price_cny_per_million") or 0)
    input_cost_cny = total_est_tokens * input_price_cny / 1_000_000
    output_cost_cny = expected_output_tokens * output_price_cny / 1_000_000
    budget_input_tokens = int(dynamic_budget.get("input_budget") or 0)

    cfg = novel.context_config or {}
    context_config_keys = [
        "core_setting", "book_summary", "arc_summary", "chapter_outline",
        "rolling_summary", "rag_context", "notes_context", "recent_text",
        "characters", "items", "systems", "locations", "factions", "techniques",
    ]
    context_top_k_defaults = {
        "characters_top_k": 8,
        "items_top_k": 5,
        "systems_top_k": 3,
        "locations_top_k": 5,
        "factions_top_k": 4,
        "techniques_top_k": 4,
        "notes_top_k": 5,
    }

    return {
        "chapter_number": chapter_number,
        "meta": context_meta,
        "context": {
            **sections,
            "characters_count": len(ctx.get("characters", [])),
            "items_count": len(items_list),
            "systems_count": len(systems_list),
            "locations_count": len(ctx.get("locations", [])),
            "factions_count": len(ctx.get("factions", [])),
            "techniques_count": len(ctx.get("techniques", [])),
        },
        "context_config": {
            **{k: cfg.get(k, True) for k in context_config_keys},
            **{k: cfg.get(k, default) for k, default in context_top_k_defaults.items()},
        },
        "token_estimate": {
            **section_tokens,
            "characters": chars_tokens,
            "items": items_tokens,
            "systems": systems_tokens,
            "locations": locations_tokens,
            "factions": factions_tokens,
            "techniques": techniques_tokens,
            "task_instruction": task_tokens,
            "system_prompt": system_tokens,
            "total": total_est_tokens,
        },
        "dynamic_budget": dynamic_budget,
        "pricing": {
            **pricing,
            "input_tokens": total_est_tokens,
            "expected_output_tokens": expected_output_tokens,
            "input_cost_cny": input_cost_cny,
            "output_cost_cny": output_cost_cny,
            "total_cost_cny": input_cost_cny + output_cost_cny,
            "budget_input_cost_cny": budget_input_tokens * input_price_cny / 1_000_000,
        },
        "writer_messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": context_block or "（无上下文区块）"},
            {"role": "assistant", "content": chars_block or "（无角色/实体数据）"},
            {"role": "user", "content": task_instruction},
        ],
        "writer_model": novel.writer_model or "（使用全局默认 Writer 模型）",
        "system_source": system_source,
    }


class _BuildBody(BaseModel):
    nsfw_mode: bool = False


@router.post("/{novel_id}/build")
async def build_novel(novel_id: int, body: _BuildBody, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    # 所有权校验用请求级 db；SSE 流内另开独立会话，避免长流式期间连接悬空。
    await get_owned_novel(db, novel_id, user)

    async def event_stream():
        async with AsyncSessionLocal() as gen_db:
            async for chunk in build_agent.run_novel_build(gen_db, novel_id, nsfw_mode=body.nsfw_mode):
                yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )


@router.post("/{novel_id}/reindex-entities")
async def reindex_entities(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await get_owned_novel(db, novel_id, user)
    counts = await entity_embeddings.reindex_all_entities(db, novel_id)
    return counts


@router.post("/{novel_id}/rebuild-vectors")
async def rebuild_vectors(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """删除并按当前嵌入模型重建整本书的向量集合。
    用于修复历史集合维度与当前模型不一致（如 384 vs 1536）导致的写入失败。"""
    novel = await get_owned_novel(db, novel_id, user)
    await _reindex_after_embedding_change(db, novel)
    await db.commit()
    return {"ok": True}


@router.post("/{novel_id}/reindex-timeline")
async def reindex_timeline(novel_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """批量重标注所有章节摘要的时间标记为绝对日期计数格式。"""
    import re, json as _json, logging, traceback
    log = logging.getLogger(__name__)

    try:
        novel = await get_owned_novel(db, novel_id, user)

        result = await db.execute(
            select(Chapter)
            .where(Chapter.novel_id == novel.id, Chapter.summary.is_not(None), Chapter.summary != "")
            .order_by(Chapter.number)
        )
        chapters = result.scalars().all()
        if not chapters:
            return {"updated": 0, "results": []}

        model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
        log.warning("reindex-timeline: model=%s, api_format=%s, chapters=%d", model, api_format, len(chapters))

        BATCH_SIZE = 15
        OVERLAP = 3

        output_spec = (
            '请输出 JSON 数组，每项格式为 {"chapter": 章节号, "time": "新时间标记"}。\n'
            "只输出 JSON 数组，不要其他文字。"
        )

        def _parse_raw(raw_text: str) -> list:
            raw_text = raw_text.strip()
            if not raw_text:
                return []
            return _json.loads(repair_json(raw_text, expect="array"))

        time_map: dict[int, str] = {}
        resolved_tail: list[tuple[int, str]] = []  # (chapter_number, time) of last few resolved

        for i in range(0, len(chapters), BATCH_SIZE):
            batch = chapters[i:i + BATCH_SIZE]

            # 构建指令
            instruction = (
                "你是一位时间线编辑。下面是一部小说各章节的剧情梗概。\n"
                "请为每一章确定一个绝对日期计数格式的时间标记。\n\n"
                "规则：\n"
                "- 格式为：第X日 或 第X日·时段（清晨/上午/白天/午后/傍晚/晚上/深夜）\n"
                "- 如果一章跨越多天：第X日·时段→第Y日·时段\n"
                "- 禁止使用当天、当日、次日、翌日、第二天、三日后等相对时间词\n"
                "- 日数必须单调递增，不能回退或重置\n"
                "- 即使某章缺少时间标记，也必须根据上下文推算\n"
            )

            if resolved_tail:
                instruction += "\n已确定的前几章时间（作为参照，不要输出这些章）：\n"
                for ch_num, ch_time in resolved_tail:
                    instruction += f"  第{ch_num}章 → 【{ch_time}】\n"
                last_time = resolved_tail[-1][1]
                instruction += f"\n⚠ 本批第一章（第{batch[0].number}章）的日数必须 ≥ {last_time}，严禁回退到第1日。\n"
            else:
                instruction += "- 第一章发生的故事为第1日\n"

            summaries_text = "\n".join(f"第{c.number}章：{c.summary}" for c in batch)
            instruction += f"\n需要标注的章节：\n{summaries_text}"

            if api_format == "gemini":
                messages = [
                    {"role": "user", "content": instruction},
                    {"role": "assistant", "content": "好的，我来为这些章节标注绝对日期。"},
                    {"role": "user", "content": output_spec},
                ]
            else:
                messages = [{"role": "user", "content": f"{instruction}\n\n{output_spec}"}]

            raw, _, _ = await llm_client.dispatch_chat_complete_with_usage(
                messages=messages, model=model, api_format=api_format,
                temperature=0.1, max_tokens=2000,
            )

            batch_results = _parse_raw(raw)
            if not batch_results and i == 0:
                raise HTTPException(status_code=500, detail="LLM 返回空内容，可能被安全过滤器拦截，请尝试更换 fast 模型")

            previous_time = resolved_tail[-1][1] if resolved_tail else ""
            normalized_results = []
            for item in sorted(batch_results, key=lambda x: x.get("chapter", 0)):
                ch_num = item.get("chapter")
                ch_time = item.get("time")
                if ch_num is not None and ch_time:
                    ch_time = summarizer.normalize_timeline_tag(ch_time, previous_time)
                    time_map[ch_num] = ch_time
                    previous_time = ch_time
                    normalized_results.append({"chapter": ch_num, "time": ch_time})

            # 保留本批最后 OVERLAP 条结果作为下一批的参照
            valid_results = [(item["chapter"], item["time"]) for item in normalized_results if "chapter" in item and "time" in item]
            resolved_tail = valid_results[-OVERLAP:] if valid_results else resolved_tail

        updated = 0
        results = []
        for c in chapters:
            new_time = time_map.get(c.number)
            if not new_time:
                continue
            new_tag = f"【{new_time}】"
            old_match = re.match(r'【(.+?)】', c.summary)
            if old_match:
                old_tag = old_match.group(0)
                c.summary = c.summary.replace(old_tag, new_tag, 1)
            else:
                c.summary = new_tag + c.summary

            mem_result = await db.execute(
                select(Memory).where(
                    Memory.novel_id == novel.id,
                    Memory.memory_type == "chapter_summary",
                    Memory.chapter_number == c.number,
                )
            )
            for mem in mem_result.scalars().all():
                if old_match and old_match.group(0) in mem.content:
                    mem.content = mem.content.replace(old_match.group(0), new_tag, 1)
                elif not re.match(r'【(.+?)】', mem.content):
                    mem.content = new_tag + mem.content

            updated += 1
            results.append({"chapter": c.number, "old": old_match.group(1) if old_match else "(无)", "new": new_time})

        await db.commit()
        return {"updated": updated, "results": results}

    except HTTPException:
        raise
    except Exception as e:
        log.error("reindex-timeline failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


def aggregate_usage(rows: list[tuple], price_map: dict, group_by: str) -> dict:
    """把 (key, model, calls, in_tok, out_tok, dur_ms) 聚合行按 key 归并，
    并按 price_map（model → (输入单价, 输出单价)，单位 元/百万token）折算成本。"""
    groups: dict = {}
    for key, model, calls, in_tok, out_tok, dur_ms in rows:
        g = groups.setdefault(key, {
            "key": key, "calls": 0, "input_tokens": 0, "output_tokens": 0,
            "duration_ms": 0, "cost_cny": 0.0,
        })
        in_tok = in_tok or 0
        out_tok = out_tok or 0
        g["calls"] += calls or 0
        g["input_tokens"] += in_tok
        g["output_tokens"] += out_tok
        g["duration_ms"] += dur_ms or 0
        in_price, out_price = price_map.get(model, (0.0, 0.0))
        g["cost_cny"] += in_tok * in_price / 1_000_000 + out_tok * out_price / 1_000_000
    result_rows = sorted(groups.values(), key=lambda g: (-g["cost_cny"], -g["input_tokens"]))
    total = {
        "calls": sum(g["calls"] for g in result_rows),
        "input_tokens": sum(g["input_tokens"] for g in result_rows),
        "output_tokens": sum(g["output_tokens"] for g in result_rows),
        "duration_ms": sum(g["duration_ms"] for g in result_rows),
        "cost_cny": sum(g["cost_cny"] for g in result_rows),
    }
    return {"group_by": group_by, "rows": result_rows, "total": total}


@router.get("/{novel_id}/usage")
async def get_llm_usage(
    novel_id: int,
    user: CurrentUser,
    group_by: str = Query("agent"),
    db: AsyncSession = Depends(get_db),
):
    """LLM 用量账本汇总：按环节/模型/章节分组，折算成人民币成本（未配置单价的模型计 0）。"""
    await get_owned_novel(db, novel_id, user)
    if group_by not in ("agent", "model", "chapter"):
        raise HTTPException(status_code=400, detail="group_by 只支持 agent / model / chapter")
    key_col = {
        "agent": LlmUsage.agent,
        "model": LlmUsage.model,
        "chapter": LlmUsage.chapter_number,
    }[group_by]
    result = await db.execute(
        select(
            key_col, LlmUsage.model,
            func.count(LlmUsage.id),
            func.sum(LlmUsage.input_tokens),
            func.sum(LlmUsage.output_tokens),
            func.sum(LlmUsage.duration_ms),
        )
        .where(LlmUsage.novel_id == novel_id)
        .group_by(key_col, LlmUsage.model)
    )
    rows = result.all()

    entries = (await db.execute(
        select(ModelEntry).where(ModelEntry.user_id == user.id)
    )).scalars().all()
    price_map = {
        e.model_id: (
            float(e.input_price or 0) * float(e.currency_to_cny_rate or 1),
            float(e.output_price or 0) * float(e.currency_to_cny_rate or 1),
        )
        for e in entries
    }
    return aggregate_usage([tuple(r) for r in rows], price_map, group_by)
