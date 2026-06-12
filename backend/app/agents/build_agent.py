"""Build Agent: 小说世界自动构建流水线（SSE 流式输出）"""
import asyncio
import json
import logging
import time
from typing import AsyncGenerator

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.location import Location
from app.models.faction import Faction
from app.models.technique import Technique
from app.models.memory import Outline
from app.models.volume import Volume
from app.agents import world_agent, outline_agent, character_agent
from app.services import llm_client, entity_embeddings, vector_store
from app.prompts.loader import render

log = logging.getLogger(__name__)

STEPS = [
    {"step": 1, "key": "config", "label": "分析配置参数"},
    {"step": 2, "key": "world", "label": "世界观·故事核心"},
    {"step": 3, "key": "outline", "label": "情节大纲"},
    {"step": 4, "key": "locations", "label": "构建地点"},
    {"step": 5, "key": "factions", "label": "势力阵营"},
    {"step": 6, "key": "characters", "label": "设计角色"},
    {"step": 7, "key": "techniques", "label": "力量/功法体系"},
]

TECHNIQUE_GENRES = {"玄幻", "仙侠", "武侠", "奇幻", "末世", "游戏", "科幻"}


def _sse(event: str, data) -> str:
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def _step_event(step: dict, status: str) -> str:
    return _sse("build_step", {**step, "status": status})


def _token(text: str) -> str:
    return _sse("build_token", text)


def _progress(percent: int, inp: int, out: int) -> str:
    return _sse("build_progress", {"percent": percent, "input_tokens": inp, "output_tokens": out})


def _format_tags(tags: dict) -> str:
    if not tags:
        return ""
    parts = []
    labels = {"tropes": "叙事套路", "situation": "角色处境", "theme": "题材方向",
              "pacing": "节奏风格", "cheat": "金手指"}
    for k, v in tags.items():
        if v:
            parts.append(f"{labels.get(k, k)}: {', '.join(v)}")
    return " | ".join(parts)


def _parse_json_array(raw: str) -> list[dict]:
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start < 0 or end <= start:
        return []
    try:
        return json.loads(raw[start:end])
    except json.JSONDecodeError:
        return []


def _clean_generated_title(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""

    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    for line in lines:
        line = line.lstrip("-*0123456789.、 \t")
        if "：" in line:
            prefix, rest = line.split("：", 1)
            if len(prefix) <= 8 and any(key in prefix for key in ("标题", "书名", "名字", "名称")):
                line = rest.strip()
        if ":" in line:
            prefix, rest = line.split(":", 1)
            if len(prefix) <= 16 and any(key in prefix for key in ("title", "name", "标题", "书名", "名字", "名称")):
                line = rest.strip()
        line = line.strip("《》\"'“”‘’「」[]【】 ")
        if 2 <= len(line) <= 12 and not any(bad in line for bad in ("以下", "几个", "风格", "小说名", "建议", "可以")):
            return line

    text = text.strip("《》\"'“”‘’「」[]【】 ")
    if 2 <= len(text) <= 12 and "\n" not in text:
        return text
    return ""


def _is_placeholder_title(title: str) -> bool:
    text = (title or "").strip()
    if not text:
        return True
    if text.startswith("《"):
        return True
    return any(
        bad in text
        for bad in ("为您提供", "以下几个", "不同风格", "小说名", "小说名字", "候选", "标题", "名称")
    )


async def _clear_build_outputs(db: AsyncSession, novel_id: int) -> dict[str, int]:
    """Replace-mode cleanup for artifacts managed by the automatic build flow."""
    outline_ids = (await db.execute(select(Outline.id).where(Outline.novel_id == novel_id))).scalars().all()
    chapter_volumes = set((await db.execute(select(Chapter.volume).where(Chapter.novel_id == novel_id))).scalars().all())
    volume_ids = (await db.execute(
        select(Volume.id).where(Volume.novel_id == novel_id, Volume.number.not_in(chapter_volumes or {-1}))
    )).scalars().all()
    loc_ids = (await db.execute(select(Location.id).where(Location.novel_id == novel_id))).scalars().all()
    fac_ids = (await db.execute(select(Faction.id).where(Faction.novel_id == novel_id))).scalars().all()
    tech_ids = (await db.execute(select(Technique.id).where(Technique.novel_id == novel_id))).scalars().all()

    doc_ids = [f"location_{i}" for i in loc_ids]
    doc_ids.extend(f"faction_{i}" for i in fac_ids)
    doc_ids.extend(f"technique_{i}" for i in tech_ids)
    await vector_store.adelete_docs(novel_id, doc_ids)

    await db.execute(delete(Outline).where(Outline.novel_id == novel_id))
    await db.execute(delete(Volume).where(Volume.id.in_(volume_ids)))
    await db.execute(delete(Location).where(Location.novel_id == novel_id))
    await db.execute(delete(Faction).where(Faction.novel_id == novel_id))
    await db.execute(delete(Technique).where(Technique.novel_id == novel_id))
    await db.commit()

    return {
        "outlines": len(outline_ids),
        "volumes": len(volume_ids),
        "locations": len(loc_ids),
        "factions": len(fac_ids),
        "techniques": len(tech_ids),
    }


async def run_novel_build(db: AsyncSession, novel_id: int, nsfw_mode: bool = False) -> AsyncGenerator[str, None]:
    t0 = time.time()
    total_in, total_out = 0, 0

    novel = await db.get(Novel, novel_id)
    if not novel:
        yield _sse("error", "小说不存在")
        return

    try:
        # ── Step 1: Config ──
        yield _step_event(STEPS[0], "running")
        config_lines = [
            f"类型: {novel.genre} | 长度: {novel.target_length} | 风格: {novel.writing_style}",
        ]
        if novel.premise:
            config_lines.append(f"创作方向: {novel.premise}")
        tags_str = _format_tags(novel.tags or {})
        if tags_str:
            config_lines.append(f"标签: {tags_str}")
        config_text = "\n".join(config_lines)
        yield _token(config_text)
        cleaned = await _clear_build_outputs(db, novel.id)
        if any(v > 0 for v in cleaned.values()):
            yield _token("\n已清理旧构建产物，开始重新生成。")
        yield _step_event(STEPS[0], "done")
        yield _progress(5, total_in, total_out)

        # ── Step 2: World ──
        yield _step_event(STEPS[1], "running")
        raw_setting_parts = [p for p in [novel.core_setting, novel.premise or novel.genre] if p]
        raw_setting = "\n\n".join(raw_setting_parts)
        if novel.tags:
            raw_setting += "\n" + _format_tags(novel.tags)
        core_setting = await world_agent.expand_world_setting(novel, raw_setting, "", nsfw_mode=nsfw_mode)
        novel.core_setting = core_setting

        is_placeholder = _is_placeholder_title(novel.title)
        if is_placeholder:
            title_prompt = (
                f"根据以下小说信息，取一个简洁有吸引力的小说名称。\n"
                f"要求：只输出一个中文标题，2-6个字，不要书名号，不要解释，不要列多个候选。\n"
                f"类型：{novel.genre}\n方向：{novel.premise or '无'}\n"
                f"世界观：{core_setting[:500]}"
            )
            title_model, title_fmt = llm_client.get_agent_client("world", novel.fast_model)
            generated_title = await llm_client.dispatch_chat_complete(
                messages=[
                    {"role": "system", "content": "你是小说标题编辑，只输出简洁、自然、具有吸引力的中文标题。"},
                    {"role": "user", "content": title_prompt},
                ],
                model=title_model, api_format=title_fmt, temperature=0.9, max_tokens=60)
            clean_title = _clean_generated_title(generated_title)
            if clean_title:
                novel.title = clean_title

        await db.commit()
        await world_agent.embed_world_setting(novel.id, core_setting)
        yield _token(core_setting)
        yield _step_event(STEPS[1], "done")
        yield _progress(20, total_in, total_out)

        # ── Step 3: Outline ──
        if novel.skip_outline:
            yield _step_event(STEPS[2], "skipped")
            outline_titles = ""
            yield _progress(40, total_in, total_out)
        else:
            yield _step_event(STEPS[2], "running")
            outlines = await outline_agent.generate_chapter_outlines(db, novel, nsfw_mode=nsfw_mode)
            outline_text = "\n\n".join(f"第{o.chapter_number}章：{o.title}\n{o.content}" for o in outlines)
            yield _token(outline_text)
            await db.commit()
            yield _step_event(STEPS[2], "done")
            yield _progress(40, total_in, total_out)
            outline_titles = "、".join(f"第{o.chapter_number}章:{o.title}" for o in outlines[:20])

        # ── Step 4: Locations ──
        yield _step_event(STEPS[3], "running")
        loc_prompt = render("build_locations.jinja2",
                            genre=novel.genre, premise=novel.premise or "",
                            core_setting=novel.core_setting[:1000],
                            outline_titles=outline_titles)
        model, api_format = llm_client.get_agent_client("world", novel.fast_model)
        loc_raw = await llm_client.dispatch_chat_complete(
            messages=[
                {"role": "system", "content": "你是世界观编辑，只输出结构化、克制、可解析的地点列表。"},
                {"role": "user", "content": loc_prompt},
            ],
            model=model, api_format=api_format, temperature=0.7, max_tokens=1200)
        loc_items = _parse_json_array(loc_raw)
        loc_lines = []
        for item in loc_items:
            name = item.get("name", "").strip()
            if not name:
                continue
            loc = Location(novel_id=novel.id, name=name,
                           type=item.get("type", "city"), description=item.get("description", ""))
            db.add(loc)
            loc_lines.append((loc, f"📍 {name}（{loc.type}）: {loc.description}"))
        await db.commit()
        for loc, _ in loc_lines:
            await entity_embeddings.embed_location(novel.id, loc)
        yield _token("\n".join(line for _, line in loc_lines) if loc_lines else "（无地点生成）")
        yield _step_event(STEPS[3], "done")
        yield _progress(55, total_in, total_out)

        # ── Step 5: Factions ──
        yield _step_event(STEPS[4], "running")
        fac_prompt = render("build_factions.jinja2",
                            genre=novel.genre, premise=novel.premise or "",
                            core_setting=novel.core_setting[:1000])
        fac_raw = await llm_client.dispatch_chat_complete(
            messages=[
                {"role": "system", "content": "你是世界观编辑，只输出结构化、克制、可解析的势力列表。"},
                {"role": "user", "content": fac_prompt},
            ],
            model=model, api_format=api_format, temperature=0.7, max_tokens=1000)
        fac_items = _parse_json_array(fac_raw)
        fac_lines = []
        for item in fac_items:
            name = item.get("name", "").strip()
            if not name:
                continue
            fac = Faction(novel_id=novel.id, name=name,
                          type=item.get("type", ""), description=item.get("description", ""),
                          goals=item.get("goals", ""))
            db.add(fac)
            fac_lines.append((fac, f"⚔ {name}（{fac.type}）: {fac.description}"))
        await db.commit()
        for fac, _ in fac_lines:
            await entity_embeddings.embed_faction(novel.id, fac)
        yield _token("\n".join(line for _, line in fac_lines) if fac_lines else "（无势力生成）")
        yield _step_event(STEPS[4], "done")
        yield _progress(70, total_in, total_out)

        # ── Step 6: Characters ──
        yield _step_event(STEPS[5], "running")
        existing_chars = (await db.execute(
            select(Character).where(Character.novel_id == novel.id)
        )).scalars().all()
        existing_characters = "\n".join(
            f"- {c.name}（{c.role}）：{c.description}" for c in existing_chars
        )
        char_prompt = render("build_characters.jinja2",
                             genre=novel.genre, premise=novel.premise or "",
                             core_setting=novel.core_setting[:1000],
                             outline_titles=outline_titles,
                             existing_characters=existing_characters)
        char_raw = await llm_client.dispatch_chat_complete(
            messages=[
                {"role": "system", "content": "你是角色策划编辑，只输出结构化角色列表。"},
                {"role": "user", "content": char_prompt},
            ],
            model=model, api_format=api_format, temperature=0.7, max_tokens=1000)
        char_items = _parse_json_array(char_raw)
        existing_names = {c.name for c in existing_chars}
        chars_created = []
        char_lines = []
        for char in existing_chars:
            role_label = f"({char.role})" if char.role else ""
            char_lines.append(f"👤 {char.name}{role_label}: {char.description}")
        for item in char_items:
            name = item.get("name", "").strip()
            if not name or name in existing_names:
                continue
            char = Character(novel_id=novel.id, name=name,
                             role=item.get("role", "配角"), age=item.get("age", ""),
                             description=item.get("description", ""))
            db.add(char)
            chars_created.append(char)
            role_label = f"({char.role})" if char.role else ""
            char_lines.append(f"👤 {name}{role_label}: {char.description}")
        await db.commit()
        all_chars = [*existing_chars, *chars_created]
        sheet_failures = []
        sheet_warnings = []
        chars_to_embed = list(chars_created)

        def _needs_sheet(c: Character) -> bool:
            sheet = c.full_sheet or {}
            if not isinstance(sheet, dict):
                return True
            display_keys = ("appearance", "personality", "speech_style", "skills")
            return not any(sheet.get(key) for key in display_keys)

        async def _gen_sheet(c: Character) -> None:
            changed = False
            try:
                if _needs_sheet(c):
                    c.full_sheet = await character_agent.generate_character_sheet(novel, c, nsfw_mode=nsfw_mode)
                    changed = True
                    warning = (c.full_sheet or {}).get("_generation_warning")
                    if warning:
                        sheet_warnings.append(f"{c.name}: {warning}")
            except Exception as exc:
                log.warning("角色卡生成失败: %s", c.name, exc_info=True)
                c.full_sheet = {
                    "personality": c.description or f"{c.name}的性格尚未细化，需在后续剧情中补充。",
                    "skills": [],
                    "appearance": c.description or f"{c.name}的外貌尚未细化，需在后续剧情中补充。",
                    "speech_style": "说话风格尚未细化，保持与角色定位一致。",
                    "_generation_warning": f"角色卡生成失败，已使用保底人设：{exc}",
                }
                changed = True
                sheet_failures.append(f"{c.name}: {exc}")
            if not c.current_state:
                c.current_state = character_agent.init_character_state(c)
                changed = True
            if changed and c not in chars_to_embed:
                chars_to_embed.append(c)

        await asyncio.gather(*[_gen_sheet(c) for c in all_chars])
        await db.commit()
        if chars_to_embed:
            await asyncio.gather(*[entity_embeddings.embed_character(novel.id, c) for c in chars_to_embed])
        output = "\n".join(char_lines) if char_lines else "（无角色生成）"
        if sheet_warnings:
            output += "\n\n⚠ 角色卡已使用保底人设：\n" + "\n".join(f"- {w}" for w in sheet_warnings)
        if sheet_failures:
            output += "\n\n⚠ 角色卡生成失败：\n" + "\n".join(f"- {f}" for f in sheet_failures)
        yield _token(output)
        yield _step_event(STEPS[5], "done")
        yield _progress(90, total_in, total_out)

        # ── Step 7: Techniques ──
        should_gen_tech = any(g in novel.genre for g in TECHNIQUE_GENRES)
        if should_gen_tech:
            yield _step_event(STEPS[6], "running")
            tech_prompt = render("build_techniques.jinja2",
                                 genre=novel.genre,
                                 core_setting=novel.core_setting[:1000],
                                 tags=_format_tags(novel.tags or {}))
            tech_raw = await llm_client.dispatch_chat_complete(
                messages=[
                    {"role": "system", "content": "你是力量体系编辑，只输出结构化、克制、可解析的功法列表。"},
                    {"role": "user", "content": tech_prompt},
                ],
                model=model, api_format=api_format, temperature=0.7, max_tokens=1000)
            tech_items = _parse_json_array(tech_raw)
            tech_lines = []
            techs_created = []
            for item in tech_items:
                name = item.get("name", "").strip()
                if not name:
                    continue
                tech = Technique(novel_id=novel.id, name=name,
                                 type=item.get("type", "功法"), description=item.get("description", ""))
                db.add(tech)
                techs_created.append(tech)
                tech_lines.append(f"🔮 {name}（{tech.type}）: {tech.description}")
            await db.commit()
            for tech in techs_created:
                await entity_embeddings.embed_technique(novel.id, tech)
            yield _token("\n".join(tech_lines) if tech_lines else "（无功法生成）")
            yield _step_event(STEPS[6], "done")
        else:
            yield _step_event(STEPS[6], "skipped")

        yield _progress(100, total_in, total_out)

        await db.commit()
        yield _sse("build_done", {"novel_id": novel.id})

    except Exception as exc:
        log.exception("构建流水线异常: novel_id=%s", novel_id)
        await db.rollback()
        try:
            await _clear_build_outputs(db, novel_id)
        except Exception:
            log.exception("构建失败后的产物清理也失败: novel_id=%s", novel_id)
        yield _sse("error", str(exc))
