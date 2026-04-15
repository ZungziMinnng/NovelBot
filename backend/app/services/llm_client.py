import httpx
from openai import AsyncOpenAI
from typing import AsyncIterator, Union
from app.config import settings

# ─── 单例客户端（避免每次调用新建 httpx 连接）─────────────────────────────
_cached_client: AsyncOpenAI | None = None
_cached_client_key: tuple = ("", "", "", "")

# ─── 模型格式缓存（model_id → api_format）─────────────────────────────────
_model_formats: dict[str, str] = {}


def _make_client() -> AsyncOpenAI:
    """返回全局复用的 AsyncOpenAI 客户端，当 API Key / Base URL / 代理变化时自动重建。"""
    global _cached_client, _cached_client_key
    key = (settings.aihubmix_api_key, settings.aihubmix_base_url,
           settings.https_proxy, settings.http_proxy)
    if _cached_client is None or _cached_client_key != key:
        mounts: dict = {}
        if settings.https_proxy:
            mounts["https://"] = httpx.AsyncHTTPTransport(proxy=settings.https_proxy)
        if settings.http_proxy:
            mounts["http://"] = httpx.AsyncHTTPTransport(proxy=settings.http_proxy)
        http_client = httpx.AsyncClient(mounts=mounts or None, trust_env=True)
        _cached_client = AsyncOpenAI(
            api_key=settings.aihubmix_api_key,
            base_url=settings.aihubmix_base_url,
            http_client=http_client,
        )
        _cached_client_key = key
    return _cached_client


async def refresh_model_formats(session) -> None:
    """从数据库重建 model_id → api_format 内存映射"""
    from sqlalchemy import select
    from app.models.model_library import ModelEntry
    result = await session.execute(select(ModelEntry))
    _model_formats.clear()
    for m in result.scalars():
        _model_formats[m.model_id] = m.api_format


def get_model_api_format(model_id: str) -> str:
    """查询模型的 api_format，未录入则默认 openai"""
    return _model_formats.get(model_id, "openai")


def _resolve_model(agent_type: str, novel_override: str = "") -> str:
    """按优先级解析最终使用的 model_id"""
    if novel_override:
        return novel_override
    setting_field, category = _AGENT_MODEL_MAP.get(agent_type, ("", "fast"))
    agent_model = getattr(settings, setting_field, "") if setting_field else ""
    if agent_model:
        return agent_model
    if category == "writer":
        return settings.default_writer_model
    return settings.default_fast_model


def get_writer_client(novel_writer_model: str = "") -> tuple[str, str]:
    """返回 (model_id, api_format) 用于高质量生成"""
    model = novel_writer_model or settings.default_writer_model
    return model, get_model_api_format(model)


def get_fast_client(novel_fast_model: str = "") -> tuple[str, str]:
    """返回 (model_id, api_format) 用于规划/摘要等低成本任务"""
    model = novel_fast_model or settings.default_fast_model
    return model, get_model_api_format(model)


# Agent-type → (agent_setting_field, fallback_category)
_AGENT_MODEL_MAP: dict[str, tuple[str, str]] = {
    "writer":       ("agent_writer_model",       "writer"),
    "critic":       ("agent_critic_model",        "fast"),
    "memory":       ("agent_memory_model",        "fast"),
    "outline":      ("agent_outline_model",       "fast"),
    "character":    ("agent_character_model",     "fast"),
    "orchestrator": ("agent_orchestrator_model",  "fast"),
    "world":        ("agent_orchestrator_model",  "fast"),
}


def get_agent_client(
    agent_type: str,
    novel_override: str = "",
) -> tuple[str, str]:
    """
    按优先级解析 Agent 使用的模型：
      novel_override > agent-level setting > category default (writer/fast)
    返回 (model_id, api_format)
    """
    model = _resolve_model(agent_type, novel_override)
    return model, get_model_api_format(model)


# ─── 消息格式转换辅助函数 ──────────────────────────────────────────────────

def _to_gemini_contents(messages: list[dict]) -> tuple[str, list]:
    """提取 system prompt，其余转为 Gemini {role: user/model, parts: [{text}]} 格式"""
    system_instruction = ""
    contents = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_instruction = content
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})
        else:
            contents.append({"role": "user", "parts": [{"text": content}]})
    return system_instruction, contents


def _to_anthropic_messages(messages: list[dict]) -> tuple[str, list]:
    """提取 system prompt，其余保持 {role, content} 格式"""
    system_prompt = ""
    filtered = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_prompt = content
        else:
            filtered.append({"role": role, "content": content})
    return system_prompt, filtered


# ─── 统一分发函数 ──────────────────────────────────────────────────────────

async def dispatch_chat_complete(
    messages: list[dict],
    model: str,
    api_format: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """根据 api_format 分发非流式调用，返回文本内容"""
    if api_format == "gemini":
        return await _gemini_complete(messages, model, temperature, max_tokens)
    elif api_format == "anthropic":
        return await _anthropic_complete(messages, model, temperature, max_tokens)
    else:
        client = _make_client()
        return await chat_complete(messages, model, client, temperature, max_tokens)


async def dispatch_chat_complete_with_usage(
    messages: list[dict],
    model: str,
    api_format: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> tuple[str, int, int]:
    """根据 api_format 分发非流式调用，返回 (content, input_tokens, output_tokens)"""
    if api_format == "gemini":
        return await _gemini_complete_with_usage(messages, model, temperature, max_tokens)
    elif api_format == "anthropic":
        return await _anthropic_complete_with_usage(messages, model, temperature, max_tokens)
    else:
        client = _make_client()
        return await chat_complete_with_usage(messages, model, client, temperature, max_tokens)


async def dispatch_chat_stream_with_usage(
    messages: list[dict],
    model: str,
    api_format: str,
    temperature: float = 0.85,
    max_tokens: int = 4096,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    """根据 api_format 分发流式调用，yield str token 最后 yield (in_tok, out_tok)"""
    if api_format == "gemini":
        async for item in _gemini_stream_with_usage(messages, model, temperature, max_tokens):
            yield item
    elif api_format == "anthropic":
        async for item in _anthropic_stream_with_usage(messages, model, temperature, max_tokens):
            yield item
    else:
        client = _make_client()
        async for item in chat_stream_with_usage(messages, model, client, temperature, max_tokens):
            yield item


# ─── Gemini 原生实现 ───────────────────────────────────────────────────────

def _make_gemini_client():
    from google import genai
    kwargs = {}
    if settings.aihubmix_api_key:
        kwargs["api_key"] = settings.aihubmix_api_key
    if settings.gemini_base_url:
        kwargs["http_options"] = {"base_url": settings.gemini_base_url}
    return genai.Client(**kwargs)


async def _gemini_complete(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    from google.genai import types
    system_instruction, contents = _to_gemini_contents(messages)
    client = _make_gemini_client()
    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        system_instruction=system_instruction or None,
    )
    response = await client.aio.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )
    return response.text or ""


async def _gemini_complete_with_usage(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
) -> tuple[str, int, int]:
    from google.genai import types
    system_instruction, contents = _to_gemini_contents(messages)
    client = _make_gemini_client()
    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        system_instruction=system_instruction or None,
    )
    response = await client.aio.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )
    text = response.text or ""
    in_tok = 0
    out_tok = 0
    if response.usage_metadata:
        in_tok = response.usage_metadata.prompt_token_count or 0
        out_tok = response.usage_metadata.candidates_token_count or 0
    return text, in_tok, out_tok


async def _gemini_stream_with_usage(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    from google.genai import types
    system_instruction, contents = _to_gemini_contents(messages)
    client = _make_gemini_client()
    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        system_instruction=system_instruction or None,
    )
    in_tok = 0
    out_tok = 0
    async for chunk in await client.aio.models.generate_content_stream(
        model=model,
        contents=contents,
        config=config,
    ):
        if chunk.text:
            yield chunk.text
        if chunk.usage_metadata:
            in_tok = chunk.usage_metadata.prompt_token_count or 0
            out_tok = chunk.usage_metadata.candidates_token_count or 0
    yield (in_tok, out_tok)


# ─── Anthropic 原生实现 ────────────────────────────────────────────────────

def _make_anthropic_client():
    import anthropic
    kwargs = {"api_key": settings.aihubmix_api_key or "placeholder"}
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    return anthropic.AsyncAnthropic(**kwargs)


async def _anthropic_complete(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    system_prompt, filtered = _to_anthropic_messages(messages)
    client = _make_anthropic_client()
    kwargs = {
        "model": model,
        "messages": filtered,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    response = await client.messages.create(**kwargs)
    return response.content[0].text if response.content else ""


async def _anthropic_complete_with_usage(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
) -> tuple[str, int, int]:
    system_prompt, filtered = _to_anthropic_messages(messages)
    client = _make_anthropic_client()
    kwargs = {
        "model": model,
        "messages": filtered,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    response = await client.messages.create(**kwargs)
    text = response.content[0].text if response.content else ""
    in_tok = response.usage.input_tokens if response.usage else 0
    out_tok = response.usage.output_tokens if response.usage else 0
    return text, in_tok, out_tok


async def _anthropic_stream_with_usage(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    system_prompt, filtered = _to_anthropic_messages(messages)
    client = _make_anthropic_client()
    kwargs = {
        "model": model,
        "messages": filtered,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    in_tok = 0
    out_tok = 0
    async with client.messages.stream(**kwargs) as stream:
        async for text in stream.text_stream:
            yield text
        final = await stream.get_final_message()
        if final.usage:
            in_tok = final.usage.input_tokens or 0
            out_tok = final.usage.output_tokens or 0
    yield (in_tok, out_tok)


# ─── 旧式 OpenAI 调用（保留向后兼容）─────────────────────────────────────

async def chat_complete(
    messages: list[dict],
    model: str,
    client: AsyncOpenAI,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """非流式调用"""
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


async def chat_complete_with_usage(
    messages: list[dict],
    model: str,
    client: AsyncOpenAI,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> tuple[str, int, int]:
    """非流式调用，返回 (content, input_tokens, output_tokens)"""
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content or ""
    usage = response.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0
    return content, in_tok, out_tok


async def chat_stream(
    messages: list[dict],
    model: str,
    client: AsyncOpenAI,
    temperature: float = 0.85,
    max_tokens: int = 4096,
) -> AsyncIterator[str]:
    """流式调用，逐 token yield"""
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def chat_stream_with_usage(
    messages: list[dict],
    model: str,
    client: AsyncOpenAI,
    temperature: float = 0.85,
    max_tokens: int = 4096,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    """
    流式调用，逐 token yield str。
    最后 yield tuple[int, int] = (input_tokens, output_tokens)。
    """
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
        if chunk.usage:
            yield (chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
