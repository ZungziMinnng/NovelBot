"""模组各栏的 AI 生成 / 优化。对应酒馆的 tavern_card_agent。

只服务编辑器，不进游玩链路：输入是前端表单里的文本，输出是一段字给作者过目，
作者点「用这个」才写回表单，端点本身不落任何库。

安全底线同酒馆：creator_note 是「AI 看不到的介绍」，它既不作为输入进 prompt，
也不给生成入口——那一栏本来就是写给人看的。
"""
from app.services import llm_client
from app.services.rpg_prompts import render

# 单条参考的长度上限。放到 5000 是为了让写了几千字的世界观能整段进去——
# 只截前 600 字会让生成的内容和后半段设定对不上
CONTEXT_CHARS = 5000

# 可辅助的栏位 → (界面上的名字, 这一栏该写什么, 字数上限)。
# **这是唯一的栏位注册点**：路由拿它当白名单，前端的联合类型照着它写
FIELD_SPECS: dict[str, tuple[str, str, int]] = {
    "worldview": (
        "世界观",
        "这个世界是什么样的：时代、地方、有什么规矩、正在发生什么麻烦。"
        "写玩家一进来就该知道的那些事，不写只有作者知道的秘密",
        1800,
    ),
    "opening_scene": (
        "开场",
        "玩家睁开眼看到的第一幕：他在哪、周围有什么、此刻发生了什么事。"
        "这段会作为第一条旁白发给玩家，所以要给出一个可以立刻动手的处境",
        1200,
    ),
    "system_instruction": (
        "GM 风格",
        "对主持人的额外要求：叙事的腔调、节奏、尺度、哪些东西必须写、"
        "哪些绝对不能出现。写成一条条祈使句，不要写世界设定",
        1200,
    ),
    "narration_sample": (
        "叙事样例",
        "一段示范性的旁白，用来定腔调。只写 GM 那一侧，不要写玩家说了什么、做了什么",
        900,
    ),
    "npc_persona": (
        "角色性格",
        "这个人是什么脾气、在意什么、怕什么、说话什么调子、对玩家是什么态度。"
        "有矛盾的人比完美的人耐看",
        1200,
    ),
    "npc_appearance": (
        "角色外貌",
        "第一次见到他时看得见的东西：长相、身形、穿着、随身带着什么、"
        "有什么一眼能记住的特征",
        900,
    ),
    "npc_description": (
        "角色详细设定",
        "身份、来历、重要经历、会什么、和别人是什么关系。这些是事实，不是性格",
        1500,
    ),
    "location_description": (
        "地点描述",
        "走进来看到什么、闻到什么、听到什么、有什么不对劲。写感官，不写地图方位",
        900,
    ),
    "item_description": (
        "道具描述",
        "这东西是什么、什么手感、从哪来的、有什么用或者有什么古怪",
        600,
    ),
    "skill_description": (
        "技能描述",
        "这一招怎么施展、使出来是什么样子、管什么用、有什么代价",
        600,
    ),
    "task_description": (
        "任务描述",
        "这桩事的来龙去脉：谁托付的、为什么要办、办不成会怎样",
        600,
    ),
}


async def assist_field(
    field: str, content: str, context: dict[str, str], model_ref: str
) -> str:
    """生成（content 为空）或优化（content 非空）单栏内容，只返回该栏正文。

    context 是 {展示名: 文本}，由前端按当前表单拼；这里只负责截断和清洗，
    不去反查库——作者刚敲进去还没保存的内容，库里查不到。
    """
    label, guidance, max_chars = FIELD_SPECS[field]
    context_blocks = [
        {"label": str(key), "content": str(value).strip()[:CONTEXT_CHARS]}
        for key, value in (context or {}).items()
        if str(value or "").strip()
    ]
    prompt = render(
        "rpg_assist.jinja2",
        field_label=label,
        field_guidance=guidance,
        max_chars=max_chars,
        content=content,
        context_blocks=context_blocks,
        is_generate=not content.strip(),
    )
    # 用叙事模型而不是那个便宜的 fast_model_ref：这是写世界观和人设的创作活，
    # 便宜模型写出来的东西作者要整段重写，省下的那点钱买不到任何东西
    model, api_format = llm_client.get_agent_client("writer", model_ref)
    result = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.85,
        # 跟着 FIELD_SPECS 的字数上限一起放大：1800 字的世界观按中文算就要 2500+ token，
        # 留在 1500 会被硬切在句子中间
        max_tokens=4500,
    )
    return (result or "").strip()
