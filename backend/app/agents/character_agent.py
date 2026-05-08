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
from app.services.summarizer import _build_analysis_messages
from app.prompts.loader import render

logger = logging.getLogger(__name__)

HISTORY_BATCH_SIZE = 20


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
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.7,
        max_tokens=800,
    )

    try:
        # 提取 JSON
        start = raw.find("{")
        end = raw.rfind("}") + 1
        sheet = json.loads(raw[start:end])
    except Exception:
        sheet = {"raw": raw}

    return sheet


def init_character_state(character: Character) -> dict:
    """初始化角色状态（故事开始前）"""
    return {
        "location": "故事起点",
        "current_goal": "",
        "known_secrets": [],
        "initial_relationships": {},
        "relationship_changes": {},
    }


async def discover_new_characters(
    novel: Novel,
    chapter_content: str,
    existing_names: list[str],
) -> list[dict]:
    """从章节内容中提取未录入的新角色，返回 [{name, role, description}]"""
    if not chapter_content.strip():
        return []

    names_str = "、".join(existing_names) if existing_names else "（暂无）"
    prompt = (
        f"已知角色：{names_str}\n\n"
        f"请从以下章节内容中，找出所有有名有姓的新角色（不在已知列表中的）。"
        f"只提取实际出现在章节中的角色，不要凭空捏造。\n\n"
        f"以 JSON 数组输出，格式：\n"
        f'[{{"name": "姓名", "role": "配角", "description": "一句话简介"}}]\n'
        f"role 只能是：主角、反派、配角、盟友 之一。\n"
        f"如果没有新角色，直接输出 []。只输出 JSON，不要任何说明。"
    )

    model, api_format = llm_client.get_agent_client("character", novel.fast_model)
    messages = _build_analysis_messages(
        prompt, chapter_content[:3000], "请输出 JSON 数组：", api_format,
    )
    try:
        raw = await llm_client.dispatch_chat_complete(
            messages=messages,
            model=model,
            api_format=api_format,
            temperature=0.3,
            max_tokens=600,
        )
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end <= 0:
            return []
        candidates = json.loads(raw[start:end])
        return [c for c in candidates if isinstance(c, dict) and "name" in c]
    except Exception:
        return []


async def refresh_appearance(novel: Novel, character: Character) -> str:
    """使用 LLM 根据角色卡和当前状态重新生成外貌描写"""
    sheet_str = json.dumps(character.full_sheet, ensure_ascii=False)[:1500]
    state_str = json.dumps(character.current_state, ensure_ascii=False)[:500]
    prompt = (
        f"角色名：{character.name}\n角色定位：{character.role}\n"
        f"角色卡片：{sheet_str}\n当前状态：{state_str}\n\n"
        f"请根据以上信息，生成一段简洁的角色外貌描写（100-200字），"
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


async def discover_new_locations(
    novel: Novel,
    chapter_content: str,
    existing_locations: list[dict],
) -> list[dict]:
    """从章节内容中提取未录入的新地点，返回 [{name, type, description, parent_name}]"""
    if not chapter_content.strip():
        return []

    loc_str = "、".join(f"{l['name']}({l['type']})" for l in existing_locations) if existing_locations else "（暂无）"
    prompt = (
        f"已知地点：{loc_str}\n\n"
        f"请从以下章节内容中，找出所有首次出现的、有明确名称的重要地点（不在已知列表中的）。\n"
        f"只提取章节中实际描述过的地点，不要凭空捏造。忽略模糊的无名地点。\n\n"
        f"以 JSON 数组输出，格式：\n"
        f'[{{"name": "地点名", "type": "类型", "description": "一句话简介", "parent_name": "所属上级地点名或空字符串"}}]\n'
        f'type 例如：城市、山脉、宗门、秘境、建筑 等。\n'
        f"如果没有新地点，直接输出 []。只输出 JSON，不要任何说明。"
    )

    model, api_format = llm_client.get_agent_client("character", novel.fast_model)
    messages = _build_analysis_messages(
        prompt, chapter_content[:3000], "请输出 JSON 数组：", api_format,
    )
    try:
        raw = await llm_client.dispatch_chat_complete(
            messages=messages,
            model=model,
            api_format=api_format,
            temperature=0.3,
            max_tokens=600,
        )
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end <= 0:
            return []
        candidates = json.loads(raw[start:end])
        return [
            {**c, "parent_name": c.get("parent_name", "")}
            for c in candidates
            if isinstance(c, dict) and "name" in c
        ]
    except Exception:
        return []


async def discover_new_techniques(
    novel: Novel,
    chapter_content: str,
    existing_names: list[str],
) -> list[dict]:
    """从章节内容中提取未录入的功法/武技，返回 [{name, type, description}]"""
    if not chapter_content.strip():
        return []

    names_str = "、".join(existing_names) if existing_names else "（暂无）"
    prompt = (
        f"已知功法/武技：{names_str}\n\n"
        f"请从以下章节内容中，找出所有首次出现的、有明确名称的功法或武技"
        f"（不在已知列表中的）。\n"
        f"功法：修炼心法、运气法门等\n"
        f"武技：招式、术法、技能等\n\n"
        f"只提取章节中实际描述过的，不要凭空捏造。忽略没有明确名称的普通攻击。\n\n"
        f"以 JSON 数组输出，格式：\n"
        f'[{{"name": "名称", "type": "功法或武技", "description": "一句话简介"}}]\n'
        f"如果没有新功法/武技，直接输出 []。只输出 JSON，不要任何说明。"
    )

    model, api_format = llm_client.get_agent_client("character", novel.fast_model)
    messages = _build_analysis_messages(
        prompt, chapter_content[:3000], "请输出 JSON 数组：", api_format,
    )
    try:
        raw = await llm_client.dispatch_chat_complete(
            messages=messages,
            model=model,
            api_format=api_format,
            temperature=0.3,
            max_tokens=600,
        )
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end <= 0:
            return []
        candidates = json.loads(raw[start:end])
        return [c for c in candidates if isinstance(c, dict) and "name" in c]
    except Exception:
        return []


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
        text_parts.append(f"[第{ch.number}章]\n{ch.content}")
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

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]

    try:
        entries = json.loads(raw)
        if not isinstance(entries, list):
            entries = []
        return [e for e in entries if isinstance(e, dict) and "chapter" in e and "content" in e], in_tok, out_tok
    except json.JSONDecodeError:
        logger.warning("角色经历 JSON 解析失败: %s", raw[:500])
        return [], in_tok, out_tok


async def discover_new_entities(
    novel: Novel,
    chapter_content: str,
    existing_names: list[str],
) -> list[dict]:
    """从章节内容中提取未录入的道具/系统，返回 [{name, type, description}]"""
    if not chapter_content.strip():
        return []

    names_str = "、".join(existing_names) if existing_names else "（暂无）"
    prompt = (
        f"已知道具/系统：{names_str}\n\n"
        f"请从以下章节内容中，找出所有首次出现的、有明确名称的重要道具或系统"
        f"（不在已知列表中的）。\n"
        f"道具(item)：武器、法宝、丹药、装备等有名称的具体物品\n"
        f"系统(system)：修炼体系、功法系统、游戏面板、等级系统等机制\n\n"
        f"只提取章节中实际描述过的，不要凭空捏造。忽略普通无名物品（如'一把剑'）。\n\n"
        f"以 JSON 数组输出，格式：\n"
        f'[{{"name": "名称", "type": "item", "description": "一句话简介"}}]\n'
        f'type 只能是 "item" 或 "system"。\n'
        f"如果没有新道具/系统，直接输出 []。只输出 JSON，不要任何说明。"
    )

    model, api_format = llm_client.get_agent_client("character", novel.fast_model)
    messages = _build_analysis_messages(
        prompt, chapter_content[:3000], "请输出 JSON 数组：", api_format,
    )
    try:
        raw = await llm_client.dispatch_chat_complete(
            messages=messages,
            model=model,
            api_format=api_format,
            temperature=0.3,
            max_tokens=600,
        )
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end <= 0:
            return []
        candidates = json.loads(raw[start:end])
        valid_types = {"item", "system"}
        return [
            {**c, "type": c.get("type", "item") if c.get("type") in valid_types else "item"}
            for c in candidates
            if isinstance(c, dict) and "name" in c
        ]
    except Exception:
        return []


