"""Character Agent: 生成角色卡和初始状态"""
import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.novel import Novel
from app.models.character import Character
from app.services import llm_client, vector_store
from app.prompts.loader import render


async def generate_character_sheet(
    novel: Novel,
    character: Character,
) -> dict:
    """使用 LLM 生成完整角色卡"""
    prompt = render(
        "character.jinja2",
        core_setting=novel.core_setting[:500],
        name=character.name,
        role=character.role,
        age=character.age,
        description=character.description,
        premise=novel.premise,
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
        "current_goal": character.full_sheet.get("motivation", ""),
        "known_secrets": [],
        "relationship_changes": {},
    }


async def embed_character(novel_id: int, character: Character) -> None:
    """将角色信息写入向量库"""
    text = (
        f"角色：{character.name}（{character.role}）\n"
        f"描述：{character.description}\n"
        f"性格：{character.full_sheet.get('personality', '')}\n"
        f"动机：{character.full_sheet.get('motivation', '')}"
    )
    vector_store.store_text(
        novel_id=novel_id,
        doc_id=f"character_{character.id}",
        text=text,
        metadata={"type": "character", "character_id": character.id, "name": character.name},
    )
