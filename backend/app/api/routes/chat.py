from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.prompts.loader import render
from app.schemas.chat import (
    BrainstormExtractRequest,
    BrainstormExtractResponse,
    BrainstormRequest,
    ChatMessage,
    ChatRequest,
)
from app.services import context_builder, llm_client, llm_json, web_search
from app.services.sse import sse_event as _sse
from app.api.deps import CurrentUser, get_owned_novel

router = APIRouter()

_ROLE_PROMPT = (
    "你是《{title}》{genre_hint}的创作助手，服务对象是这部小说的作者本人。\n"
    "你掌握下面这份完整创作资料：世界观与核心规则、角色卡与当前状态、伏笔与秘密、"
    "各级摘要、当前章节大纲、以及与作者提问相关的历史章节原文片段。\n"
    "回答时请遵守：\n"
    "- 以资料为准。资料里有的，直接引用具体内容，不要含糊其辞；资料里没有的，明说「设定里还没定」，"
    "再给建议，不要编造成既定事实。\n"
    "- 区分「已经写了的」和「大纲里计划的」，不要把计划当成已发生的情节。\n"
    "- 你面对的是作者，所有秘密、伏笔、上帝视角真相都可以坦率讨论，不需要替角色保密。\n"
    "- 建议要落到具体的人、事、章节上，避免泛泛而谈的写作教条。\n"
    "- 除非作者明确要求你写正文或改写段落，否则以讨论和建议为主，不要擅自输出成段小说正文。\n"
    "- 直接写文字，不要用 markdown 语法（星号加粗、井号标题、反引号这些）。要分点就用「1. 2. 3.」。"
)


async def _maybe_search(
    db: AsyncSession,
    messages: list[ChatMessage],
) -> tuple[str, str]:
    """按最后一条用户消息搜一次。返回 (资料块, 警告)，两者都可能为空。"""
    query = next((m.content for m in reversed(messages) if m.role == "user"), "")
    outcome = await web_search.search(db, query)
    if outcome.error:
        return "", f"联网搜索没用上：{outcome.error}"
    return web_search.format_block(query.strip(), outcome.items), ""


def _build_chat_system_prompt(
    ctx: dict,
    progress_block: str,
    context_block: str,
    chars_block: str,
) -> str:
    genre = ctx.get("genre", "")
    parts = [
        _ROLE_PROMPT.format(
            title=ctx.get("novel_title", ""),
            genre_hint=f"（{genre}类型）" if genre else "",
        ),
        progress_block,
    ]
    if context_block:
        parts.append(context_block)
    if chars_block:
        parts.append(chars_block)
    if ctx.get("recent_text"):
        parts.append(f"=== 上一章原文 ===\n{ctx['recent_text']}")
    return "\n\n".join(p for p in parts if p)


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    SSE 流式接口：编辑器对话模式。

    事件类型：
      token  → 逐 token 输出
      done   → 完成，data 为 {input_tokens, output_tokens}
      error  → 错误信息
    """
    novel = await get_owned_novel(db, req.novel_id, user)
    await db.refresh(novel)

    focus_chapter = req.chapter_number or novel.current_chapter or 1
    if focus_chapter < 1:
        focus_chapter = 1

    # 最近两轮用户提问当检索查询词：让 RAG、实体名匹配、回忆取证围绕作者真正在问的东西，
    # 而不是退化成"第X章"这种字面量。
    user_msgs = [m.content for m in req.messages if m.role == "user"]
    scene_hint = "\n".join(user_msgs[-2:])

    ctx = await context_builder.build_generation_context(
        session=db,
        novel=novel,
        chapter_number=focus_chapter,
        volume=novel.current_volume or 1,
        scene_hint=scene_hint,
    )
    progress_block = await context_builder.build_progress_block(db, novel, focus_chapter)
    context_block, chars_block, _ = context_builder.format_context_for_writer(
        ctx, for_chat=True,
    )
    system_prompt = _build_chat_system_prompt(ctx, progress_block, context_block, chars_block)

    search_warning = ""
    if req.web_search:
        search_block, search_warning = await _maybe_search(db, req.messages)
        if search_block:
            system_prompt += f"\n\n{search_block}"

    if req.system_prompt.strip():
        system_prompt += f"\n\n=== 作者自定义指令（优先遵守）===\n{req.system_prompt}"

    # 应用消息轮次限制（1轮 = user+assistant 各1条 = 2条消息）
    chat_rounds = req.context_rounds if req.context_rounds > 0 else (novel.chat_context_rounds or 0)
    if chat_rounds and chat_rounds > 0:
        max_messages = chat_rounds * 2
        trimmed = req.messages[-max_messages:]
    else:
        trimmed = req.messages

    # 组装 messages（prepend system message）
    messages = [{"role": "system", "content": system_prompt}]
    for m in trimmed:
        messages.append({"role": m.role, "content": m.content})

    # 解析模型
    model, api_format = llm_client.get_agent_client("writer", req.model)

    return _stream_response(
        messages, model, api_format, req.temperature, req.max_tokens,
        pre_warning=search_warning,
    )


def _stream_response(
    messages: list[dict],
    model: str,
    api_format: str,
    temperature: float,
    max_tokens: int,
    pre_warning: str = "",
) -> StreamingResponse:
    async def event_stream():
        if pre_warning:
            yield _sse("warning", pre_warning)
        try:
            in_tok = 0
            out_tok = 0
            async for chunk in llm_client.dispatch_chat_stream_with_usage(
                messages=messages,
                model=model,
                api_format=api_format,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if isinstance(chunk, tuple):
                    _, in_tok, out_tok = chunk
                elif isinstance(chunk, dict):
                    if "warning" in chunk:
                        yield _sse("warning", chunk["warning"])
                else:
                    yield _sse("token", chunk)
            yield _sse("done", {"input_tokens": in_tok, "output_tokens": out_tok})
        except Exception as e:
            yield _sse("error", str(e))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# 向导阶段 id，须与前端 wizardStages.ts 和 brainstorm.jinja2 的分支保持一致
_WIZARD_STAGES = ["warmup", "idea", "characters", "opening", "plot", "world", "wrapup"]


@router.post("/brainstorm")
async def brainstorm_stream(
    req: BrainstormRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    SSE 流式接口：新建小说页的构思对话。

    和 /stream 的区别是这里还没有 novel，也不读表单草稿，不做 RAG。
    stage 为空走自由聊天，给了合法阶段 id 则按向导那一步的指令提问。
    事件类型同 /stream。
    """
    stage = req.stage if req.stage in _WIZARD_STAGES else ""
    system_prompt = render(
        "brainstorm.jinja2",
        nsfw=req.nsfw,
        stage=stage,
        confirmed=req.confirmed if stage else "",
    )

    search_warning = ""
    if req.web_search:
        search_block, search_warning = await _maybe_search(db, req.messages)
        if search_block:
            system_prompt += f"\n\n{search_block}"

    rounds = req.context_rounds
    trimmed = req.messages[-rounds * 2:] if rounds > 0 else req.messages
    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in trimmed]

    model, api_format = llm_client.get_agent_client("writer", req.model)
    return _stream_response(
        messages, model, api_format, req.temperature, req.max_tokens,
        pre_warning=search_warning,
    )


# 抽取只能选表单里已有的选项，模型自由发挥的值前端会当没聊到丢掉
_GENRES = [
    "玄幻", "仙侠", "都市", "科幻", "历史", "言情", "悬疑",
    "武侠", "奇幻", "末世", "游戏", "军事", "古代权谋",
]
# 与前端 NovelWizard.tsx 的 STYLES 保持一致
_STYLES = [
    "严肃厚重", "热血激昂", "爽文直给", "悬念紧张",
    "轻快幽默", "诙谐吐槽", "荒诞黑色幽默", "冷峻克制",
    "细腻文艺", "唯美绮丽", "古典雅致", "平实白描",
    "口语化直白", "硬核写实", "温暖治愈", "阴郁压抑",
]
_ROLES = ["主角", "男主", "女主", "配角", "盟友", "朋友", "反派"]


@router.post("/brainstorm/extract", response_model=BrainstormExtractResponse)
async def brainstorm_extract(
    req: BrainstormExtractRequest,
    user: CurrentUser,
) -> BrainstormExtractResponse:
    """把构思对话里聊定的结论抽成新建小说表单的字段。

    只读对话、不落库：抽出来的值回前端给作者过一遍，他确认了才写进表单。
    """
    if not req.messages:
        return BrainstormExtractResponse()

    transcript = "\n\n".join(
        f"{'作者' if m.role == 'user' else '编辑'}：{m.content}" for m in req.messages
    )
    system_prompt = render(
        "brainstorm_extract.jinja2",
        genres="、".join(_GENRES),
        styles="、".join(_STYLES),
        roles="、".join(_ROLES),
    )
    model, api_format = llm_client.get_fast_client(req.model)
    try:
        parsed, _, _ = await llm_json.call_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"=== 对话记录 ===\n{transcript}"},
            ],
            model,
            api_format,
            max_tokens=3000,
        )
    except llm_json.JsonCallError as e:
        raise HTTPException(status_code=502, detail=f"抽取失败：{e}") from e

    def text(key: str) -> str:
        value = parsed.get(key)
        return value.strip() if isinstance(value, str) else ""

    def one_of(key: str, allowed: list[str]) -> str:
        value = text(key)
        return value if value in allowed else ""

    cards = [
        {"volume": int(c.get("volume") or 3), "text": str(c.get("text", "")).strip()}
        for c in (parsed.get("endgame_cards") or [])
        if isinstance(c, dict) and str(c.get("text", "")).strip()
    ]
    characters = [
        {
            "name": str(c.get("name", "")).strip(),
            "role": str(c.get("role", "")).strip() if str(c.get("role", "")).strip() in _ROLES else "配角",
            "age": str(c.get("age", "")).strip(),
            "description": str(c.get("description", "")).strip(),
        }
        for c in (parsed.get("characters") or [])
        if isinstance(c, dict) and str(c.get("name", "")).strip()
    ]

    return BrainstormExtractResponse(
        title=text("title"),
        genre=one_of("genre", _GENRES),
        writing_style=one_of("writing_style", _STYLES),
        premise=text("premise"),
        plot_design=text("plot_design"),
        core_setting=text("core_setting"),
        world_rules_seed=text("world_rules_seed"),
        ending=text("ending"),
        protagonist_arc=text("protagonist_arc"),
        endgame_cards=cards,
        characters=characters,
    )
