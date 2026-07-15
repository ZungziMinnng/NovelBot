"""Character Agent: 生成角色卡和初始状态"""
import asyncio
import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.character import Character
from app.services import llm_client
from app.services.llm_json import JsonCallError, call_json, repair_json
from app.services.summarizer import _build_analysis_messages, strip_plot_suggestions
from app.prompts.loader import render

logger = logging.getLogger(__name__)

HISTORY_BATCH_SIZE = 20


def _fallback_character_sheet(character: Character, warning: str = "") -> dict:
    description = (character.description or "").strip()
    sheet = {
        "personality": description or f"{character.name}的性格尚未细化，需在后续剧情中补充。",
        "skills": [],
        "appearance": description or f"{character.name}的外貌尚未细化，需在后续剧情中补充。",
        "speech_style": "说话风格尚未细化，保持与角色定位一致。",
    }
    if warning:
        sheet["_generation_warning"] = warning
    return sheet


def _normalize_character_sheet(sheet: dict, character: Character) -> dict:
    normalized = dict(sheet) if isinstance(sheet, dict) else {}
    fallback = _fallback_character_sheet(character)
    for key, value in fallback.items():
        if key.startswith("_"):
            continue
        current = normalized.get(key)
        if current is None or current == "" or current == []:
            normalized[key] = value
    return normalized


async def generate_character_sheet(
    novel: Novel,
    character: Character,
) -> dict:
    """使用 LLM 生成完整角色卡"""
    prompt = render(
        "character.jinja2",
        core_setting=novel.core_setting[:2000],
        name=character.name,
        role=character.role,
        age=character.age,
        description=character.description,
        premise=novel.premise,
        genre=novel.genre,
        writing_style=novel.writing_style,
    )

    model, api_format = llm_client.get_agent_client("character", novel.fast_model)
    raw = await llm_client.dispatch_chat_complete(
        messages=[
            {"role": "system", "content": "你是角色设定编辑，只输出可解析的 JSON 角色卡。"},
            {"role": "user", "content": prompt},
        ],
        model=model,
        api_format=api_format,
        temperature=0.7,
        max_tokens=800,
    )

    try:
        # 提取 JSON
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("LLM response does not contain a JSON object")
        sheet = json.loads(raw[start:end])
        if not isinstance(sheet, dict):
            raise ValueError("LLM response JSON is not an object")
    except Exception as exc:
        logger.warning("角色卡 JSON 解析失败: %s; raw=%s", exc, raw[:500])
        return _fallback_character_sheet(character, "角色卡 JSON 解析失败，已使用角色简介生成保底人设。")

    return _normalize_character_sheet(sheet, character)


def init_character_state(character: Character) -> dict:
    """初始化角色状态（故事开始前）"""
    return {
        "location": "故事起点",
        "current_goal": "",
        "known_secrets": [],
        "initial_relationships": {},
        "relationship_changes": {},
    }


async def refresh_appearance(
    novel: Novel,
    character: Character,
    appearance_context: str = "",
    context_source: str = "",
) -> str:
    """使用 LLM 根据角色卡和当前状态重新生成外貌描写"""
    sheet_str = json.dumps(character.full_sheet, ensure_ascii=False)[:1500]
    state_str = json.dumps(character.current_state, ensure_ascii=False)[:500]
    context_block = ""
    if appearance_context.strip():
        context_block = (
            f"\n正文检索来源：{context_source or 'unknown'}\n"
            f"正文中与该角色相关的描写片段：\n{appearance_context[:3000]}\n"
        )
    prompt = (
        f"角色名：{character.name}\n角色定位：{character.role}\n"
        f"角色卡片：{sheet_str}\n当前状态：{state_str}\n"
        f"{context_block}\n"
        f"请根据角色卡、当前状态以及正文检索到的描写片段，生成一段简洁的角色外貌描写（100-200字）。"
        f"如果正文片段中有明确外貌、服饰、气质描写，优先采用正文事实；不要编造与正文冲突的外貌。"
        f"包括体型、面容、发型、服饰等。只输出描写文本，不要任何格式标记。"
    )
    model, api_format = llm_client.get_agent_client("character", novel.fast_model)
    raw = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.7,
        max_tokens=400,
    )
    return raw.strip()


async def enhance_character(
    novel: Novel, character: Character, user_prompt: str, scope: list[str],
) -> dict:
    """根据用户指令增强角色卡的指定部分"""
    sheet = dict(character.full_sheet or {})
    scope_str = "、".join(scope) if scope else "所有方面"
    sheet_str = json.dumps(sheet, ensure_ascii=False)[:2000]

    prompt = (
        f"角色名：{character.name}（{character.role}）\n"
        f"当前角色卡：{sheet_str}\n\n"
        f"用户要求：{user_prompt}\n"
        f"需要完善的方面：{scope_str}\n\n"
        f"请在当前角色卡基础上，根据用户要求完善指定方面的内容。"
        f"输出完整的 JSON 角色卡（保留原有字段，更新/新增指定部分）。"
        f"只输出 JSON，不要任何说明。"
    )
    model, api_format = llm_client.get_agent_client("character", novel.fast_model)
    raw = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.7,
        max_tokens=1200,
    )
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        updated = json.loads(raw[start:end])
        return {**sheet, **updated}
    except Exception:
        return sheet


async def generate_character_history(
    session: AsyncSession,
    novel: Novel,
    character: Character,
) -> tuple[list[dict], int, int]:
    """扫描全文，分批提取角色在各章节中的关键经历。返回 (history[], in_tokens, out_tokens)"""
    result = await session.execute(
        select(Chapter)
        .where(Chapter.novel_id == novel.id, Chapter.content != "")
        .order_by(Chapter.number)
    )
    all_chapters = result.scalars().all()
    chapters = [ch for ch in all_chapters if character.name in (ch.content or "")]
    if not chapters:
        return [], 0, 0

    model, api_format = llm_client.get_agent_client("review")
    batches = [chapters[i:i + HISTORY_BATCH_SIZE] for i in range(0, len(chapters), HISTORY_BATCH_SIZE)]

    if len(batches) == 1:
        history, in_tok, out_tok = await _history_batch(character, batches[0], model, api_format)
        return history, in_tok, out_tok

    tasks = [_history_batch(character, batch, model, api_format) for batch in batches]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_history: list[dict] = []
    total_in = total_out = 0
    for r in results:
        if isinstance(r, Exception):
            logger.error("角色经历批次失败: %s", r)
            continue
        history, in_tok, out_tok = r
        all_history.extend(history)
        total_in += in_tok
        total_out += out_tok

    return all_history, total_in, total_out


async def _history_batch(
    character: Character,
    batch_chapters: list[Chapter],
    model: str,
    api_format: str,
) -> tuple[list[dict], int, int]:
    """处理单批章节，提取角色经历。"""
    text_parts = []
    for ch in batch_chapters:
        text_parts.append(f"[第{ch.number}章]\n{strip_plot_suggestions(ch.content or '')}")
    full_text = "\n\n".join(text_parts)

    system_prompt = (
        f"你是小说角色分析助手。以下每一章都包含角色「{character.name}」的相关内容。\n"
        "请为每一章概括该角色的关键经历。\n"
        "要求：\n"
        f"1. 只关注「{character.name}」的行为和遭遇，忽略其他角色的独立剧情\n"
        "2. 每章100字内概括\n"
        "3. 每一章都必须输出对应条目\n"
        "4. 严格以 JSON 数组返回，不要其他文字"
    )
    user_prompt = (
        f"目标角色：{character.name}（{character.role}）\n"
        f"角色简介：{(character.description or '')[:200]}\n\n"
        f"{full_text}\n\n"
        f"请概括「{character.name}」在以上每章中的经历，以 JSON 数组返回：\n"
        f'[{{"chapter": 章号, "content": "100字内概括"}}]\n'
        f"只输出 JSON。"
    )

    raw, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=model,
        api_format=api_format,
        temperature=0.3,
        max_tokens=4096,
    )

    try:
        entries = json.loads(repair_json(raw, expect="array"))
        if not isinstance(entries, list):
            entries = []
        return [e for e in entries if isinstance(e, dict) and "chapter" in e and "content" in e], in_tok, out_tok
    except json.JSONDecodeError:
        logger.warning("角色经历 JSON 解析失败: %s", raw[:500])
        return [], in_tok, out_tok


async def generate_image_prompt(novel: Novel, char: Character, style: str) -> str:
    """根据角色信息生成图像提示词：sd_tags (Illustrious 标签) 或 natural_zh (中文自然语言)"""
    model, api_format = llm_client.get_agent_client("character", novel.fast_model)
    sheet = char.full_sheet or {}
    appearance = sheet.get("appearance", "")
    body_traits = sheet.get("body_traits", "")
    personality = sheet.get("personality", "")

    char_info = (
        f"角色名：{char.name}\n"
        f"定位：{char.role}\n"
        f"年龄：{char.age}\n"
        f"描述：{char.description}\n"
        f"外貌：{appearance}\n"
        f"身体特质：{body_traits}\n"
        f"性格：{personality}\n"
        f"小说类型：{novel.genre}\n"
    )

    if style == "sd_tags":
        system = render("image_prompt_sd_tags.jinja2")
    else:
        system = render("image_prompt_natural_zh.jinja2")

    result = await llm_client.dispatch_chat_complete(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"请为以下角色生成图像提示词：\n\n{char_info}"},
        ],
        model=model,
        api_format=api_format,
        temperature=0.7,
        max_tokens=1024,
    )
    return result.strip()


async def discover_all_new(
    novel: Novel,
    chapter_content: str,
    existing_char_names: list[str],
    existing_entity_names: list[str],
    existing_locations: list[dict],
    existing_tech_names: list[str],
    existing_faction_names: list[str],
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """单次 LLM 调用完成五类新设定发现（角色/道具系统/地点/功法/势力）。

    返回 (characters, entities, locations, techniques, factions)。
    确定性后过滤剔除已知名称；同名候选只保留优先级最高的类别：
    角色 > 功法 > 势力 > 地点 > 道具。
    """
    empty: tuple[list[dict], list[dict], list[dict], list[dict], list[dict]] = ([], [], [], [], [])
    if not chapter_content.strip():
        return empty

    def _fmt(names: list[str]) -> str:
        return "、".join(names) if names else "（暂无）"

    loc_str = (
        "、".join(f"{l['name']}({l['type']})" for l in existing_locations)
        if existing_locations else "（暂无）"
    )
    prompt = (
        f"请从以下章节内容中，找出所有首次出现的新设定条目，按五个类别分类提取。\n\n"
        f"已知角色：{_fmt(existing_char_names)}\n"
        f"已知道具/系统：{_fmt(existing_entity_names)}\n"
        f"已知地点：{loc_str}\n"
        f"已知功法/武技：{_fmt(existing_tech_names)}\n"
        f"已知势力/组织：{_fmt(existing_faction_names)}\n\n"
        f"提取规则：\n"
        f"- 只提取章节正文中实际出现且有明确名称的条目，不要凭空捏造，不要根据常识或设定推测\n"
        f"- 已知列表中的名称一律不要输出；同一名称只能归入一个类别\n"
        f"- characters（角色）：有名有姓的人物。role 只能根据文中实际表现判断，"
        f"取 男主、女主、主角、配角、反派、朋友 之一；路人级角色（仅被提及、没台词、没行为）设为「配角」。"
        f"description 只写章节中实际出现的内容（做了什么、说了什么、与谁互动），"
        f"不要添加文中未明确的门派、身份、修为、人际关系，也不要根据姓名推测性别年龄\n"
        f'- entities（道具/系统）：type 只能是 "item"（武器、法宝、丹药、装备等有名称的具体物品）'
        f'或 "system"（修炼体系、游戏面板、等级系统等机制）。忽略普通无名物品（如\'一把剑\'）\n'
        f"- locations（地点）：type 例如 城市、山脉、秘境、建筑、区域 等；"
        f"parent_name 填所属上级地点名，没有则填空字符串。忽略模糊的无名地点\n"
        f"- techniques（功法/武技）：type 为「功法」（修炼心法、运气法门）或「武技」（招式、术法、技能）。"
        f"忽略没有明确名称的普通攻击\n"
        f"- factions（势力/组织）：宗门、门派、家族、帝国、王国、教派、商会、军队、联盟 等有组织的群体，"
        f"type 填组织类型\n"
        f"- 类别界定：宗门/门派/家族/帝国/商会等组织属于势力而非地点；"
        f"有形的武器、法宝、丹药属于道具而非功法；人物姓名、地点名、组织名不要归入道具或功法\n\n"
        f"以 JSON 对象输出，格式：\n"
        f"{{\n"
        f'  "characters": [{{"name": "姓名", "role": "配角", "description": "一句话简介"}}],\n'
        f'  "entities": [{{"name": "名称", "type": "item", "description": "一句话简介"}}],\n'
        f'  "locations": [{{"name": "地点名", "type": "类型", "description": "一句话简介", "parent_name": ""}}],\n'
        f'  "techniques": [{{"name": "名称", "type": "功法", "description": "一句话简介"}}],\n'
        f'  "factions": [{{"name": "名称", "type": "类型", "description": "一句话简介"}}]\n'
        f"}}\n"
        f"某个类别没有新条目就输出空数组。只输出 JSON，不要任何说明。"
    )

    model, api_format = llm_client.get_agent_client("character", novel.fast_model)
    messages = _build_analysis_messages(
        prompt, chapter_content[:12000], "请输出 JSON 对象：", api_format,
    )

    try:
        data, _, _ = await call_json(
            messages, model, api_format,
            temperatures=(0.3, 0.1), max_tokens=2000,
        )
    except JsonCallError as exc:
        logger.warning("统一素材发现解析失败: %s", exc)
        return empty

    return filter_discovered(
        data,
        existing_char_names, existing_entity_names, existing_locations,
        existing_tech_names, existing_faction_names,
    )


def filter_discovered(
    data: dict,
    existing_char_names: list[str],
    existing_entity_names: list[str],
    existing_locations: list[dict],
    existing_tech_names: list[str],
    existing_faction_names: list[str],
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """对 LLM 输出的五类发现候选做确定性后过滤：剔除已知名称、规整类型、
    同名候选只保留优先级最高的类别（角色 > 功法 > 势力 > 地点 > 道具）。

    返回 (characters, entities, locations, techniques, factions)。
    """
    known = {
        n.strip()
        for n in (
            existing_char_names + existing_entity_names
            + [l["name"] for l in existing_locations]
            + existing_tech_names + existing_faction_names
        )
    }

    def _clean(key: str) -> list[dict]:
        items = data.get(key)
        if not isinstance(items, list):
            return []
        return [
            c for c in items
            if isinstance(c, dict) and isinstance(c.get("name"), str)
            and c["name"].strip() and c["name"].strip() not in known
        ]

    characters = _clean("characters")
    techniques = _clean("techniques")
    factions = _clean("factions")
    locations = [{**c, "parent_name": c.get("parent_name") or ""} for c in _clean("locations")]
    valid_entity_types = {"item", "system"}
    entities = [
        {**c, "type": c.get("type") if c.get("type") in valid_entity_types else "item"}
        for c in _clean("entities")
    ]

    seen: set[str] = set()

    def _dedup(cands: list[dict]) -> list[dict]:
        out = []
        for c in cands:
            name = c["name"].strip()
            if name in seen:
                continue
            seen.add(name)
            out.append(c)
        return out

    characters = _dedup(characters)
    techniques = _dedup(techniques)
    factions = _dedup(factions)
    locations = _dedup(locations)
    entities = _dedup(entities)
    return characters, entities, locations, techniques, factions


