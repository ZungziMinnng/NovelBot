"""角色卡各栏的 AI 生成/优化。

安全底线与 tavern_context 一致：creator_note 是"AI 不会看到的介绍"，
它只能作为本模块的**产出**，绝不能作为输入进任何 prompt。
"""
from app.prompts.loader import render
from app.services import llm_client

# 可辅助的栏位 → (界面上的名字, 这一栏该写什么, 字数上限)
FIELD_SPECS: dict[str, tuple[str, str, int]] = {
    "personality": (
        "角色性格",
        "基本特质、情感表现、人际关系、价值观、行为模式、优点和缺点。"
        "复杂而有矛盾的性格比完美无缺的更有深度",
        400,
    ),
    "description": (
        "详细描述",
        "外貌形象、背景故事、重要经历、能力特长、关系网络等事实性设定",
        500,
    ),
    "opening_scene": (
        "开场环境",
        "物理环境、氛围、时间、在场的其他人、角色所处位置、与玩家的情感联系。"
        "这段会作为角色的第一句话发给玩家",
        300,
    ),
}

# 给某一栏做辅助时，把哪些别的栏当参考喂进去
_CONTEXT_FIELDS: dict[str, list[str]] = {
    "personality": ["description"],
    "description": ["personality"],
    "opening_scene": ["personality", "description"],
}


async def assist_field(
    field: str,
    content: str,
    name: str,
    personality: str,
    description: str,
    model_ref: str,
) -> str:
    """生成（content 为空）或优化（content 非空）单栏内容，只返回该栏正文。"""
    label, guidance, max_chars = FIELD_SPECS[field]
    available = {"personality": personality, "description": description}
    context_blocks = [
        {"label": FIELD_SPECS[key][0], "content": available[key].strip()}
        for key in _CONTEXT_FIELDS[field]
        if key != field and available.get(key, "").strip()
    ]
    prompt = render(
        "tavern_card_field.jinja2",
        field_label=label,
        field_guidance=guidance,
        max_chars=max_chars,
        char_name=name.strip(),
        content=content,
        context_blocks=context_blocks,
        is_generate=not content.strip(),
    )
    model, api_format = llm_client.get_agent_client("memory", model_ref)
    result = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.85,
        max_tokens=1200,
    )
    return (result or "").strip()


async def assist_creator_note(
    name: str, personality: str, description: str, model_ref: str
) -> str:
    """根据性格与详细描述写卡介绍。只生成，不做优化——这栏本来就是给人认卡的。"""
    prompt = render(
        "tavern_card_note.jinja2",
        char_name=name.strip(),
        personality=personality.strip(),
        description=description.strip(),
    )
    model, api_format = llm_client.get_agent_client("memory", model_ref)
    result = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.8,
        max_tokens=400,
    )
    return (result or "").strip()
