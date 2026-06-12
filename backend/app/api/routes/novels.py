from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from openai import AuthenticationError as OpenAIAuthError
from app.database import get_db
from app.models.novel import Novel
from app.models.memory import Outline, Memory
from app.models.chapter import Chapter
from app.schemas.novel import NovelCreate, NovelUpdate, NovelOut, WizardStep2, WizardStep3, WizardStep4, WorldOptimizeRequest
from app.agents import world_agent, outline_agent, character_agent, build_agent
from app.services import summarizer, context_builder, llm_client, entity_embeddings
from app.models.character import Character
from app.models.world_entity import WorldEntity
from app.models.location import Location
from app.models.faction import Faction
from app.models.technique import Technique
from app.models.novel_note import NovelNote
from app.services import vector_store
from app.models.memory import Memory

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
            }))
        await vector_store.astore_texts_batch(novel.id, batch)

    log.info("vector store rebuilt for novel %d: %d summaries re-embedded", novel.id, len(summaries))


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db)):
    novels = (await db.execute(select(Novel))).scalars().all()
    total_novels = len(novels)

    word_rows = (await db.execute(
        select(Chapter.novel_id, func.coalesce(func.sum(Chapter.word_count), 0))
        .group_by(Chapter.novel_id)
    )).all()
    novel_words = {row[0]: row[1] for row in word_rows}
    total_words = sum(novel_words.values())

    entity_count = (await db.execute(select(func.count(WorldEntity.id)))).scalar() or 0
    technique_count = (await db.execute(select(func.count(Technique.id)))).scalar() or 0
    total_entities = entity_count + technique_count

    return {
        "total_novels": total_novels,
        "total_words": total_words,
        "total_entities": total_entities,
        "novel_words": novel_words,
    }


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
async def delete_novel(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    vector_store.delete_novel_collection(novel_id)
    await db.delete(novel)
    await db.commit()
    return {"ok": True}


# ── 搜索 ─────────────────────────────────────────────────────────────────

@router.get("/{novel_id}/search")
async def search_novel(
    novel_id: int,
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """全文搜索：向量语义检索 + SQL 模糊匹配"""
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

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
    chapter_number: int | None = None,
    instruction: str = "",
    target_words: int = 800,
    db: AsyncSession = Depends(get_db),
):
    """预览 Writer 在生成指定章节时收到的完整上下文（JSON 结构化）。"""
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

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
    system_tokens = 150
    total_est_tokens = (
        sum(section_tokens.values())
        + chars_tokens + items_tokens + systems_tokens + locations_tokens + factions_tokens + techniques_tokens
        + task_tokens + system_tokens
    )

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
        "writer_messages": [
            {"role": "system", "content": f"（系统提示由 writer.jinja2 渲染，genre={ctx.get('genre')}, writing_style={ctx.get('writing_style')}）"},
            {"role": "user", "content": context_block or "（无上下文区块）"},
            {"role": "assistant", "content": chars_block or "（无角色/实体数据）"},
            {"role": "user", "content": task_instruction},
        ],
        "writer_model": novel.writer_model or "（使用全局默认 Writer 模型）",
    }


class _BuildBody(BaseModel):
    nsfw_mode: bool = False


@router.post("/{novel_id}/build")
async def build_novel(novel_id: int, body: _BuildBody, db: AsyncSession = Depends(get_db)):
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return StreamingResponse(
        build_agent.run_novel_build(db, novel_id, nsfw_mode=body.nsfw_mode),
        media_type="text/event-stream",
    )


@router.post("/{novel_id}/reindex-entities")
async def reindex_entities(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    counts = await entity_embeddings.reindex_all_entities(db, novel_id)
    return counts


@router.post("/{novel_id}/reindex-timeline")
async def reindex_timeline(novel_id: int, db: AsyncSession = Depends(get_db)):
    """批量重标注所有章节摘要的时间标记为绝对日期计数格式。"""
    import re, json as _json, logging, traceback
    log = logging.getLogger(__name__)

    try:
        novel = await db.get(Novel, novel_id)
        if not novel:
            raise HTTPException(status_code=404, detail="小说不存在")

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
            if raw_text.startswith("```"):
                raw_text = re.sub(r'^```\w*\n?', '', raw_text)
                raw_text = re.sub(r'\n?```$', '', raw_text)
            raw_text = raw_text.strip()
            raw_text = re.sub(r',\s*]', ']', raw_text)
            return _json.loads(raw_text)

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
        tb = traceback.format_exc()
        log.error("reindex-timeline failed:\n%s", tb)
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}\n{tb[-500:]}")
