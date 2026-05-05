"""Character Agent: 生成角色卡和初始状态"""
import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.novel import Novel
from app.models.character import Character
from app.services import llm_client
from app.services.summarizer import _build_analysis_messages
from app.prompts.loader import render


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


