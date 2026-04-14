from openai import AsyncOpenAI
from typing import AsyncIterator, Union
from app.config import settings

# ─── 单例客户端（避免每次调用新建 httpx 连接）─────────────────────────────
_cached_client: AsyncOpenAI | None = None
_cached_client_key: tuple[str, str] = ("", "")


def _make_client() -> AsyncOpenAI:
    """返回全局复用的 AsyncOpenAI 客户端，当 API Key / Base URL 变化时自动重建。"""
    global _cached_client, _cached_client_key
    key = (settings.aihubmix_api_key, settings.aihubmix_base_url)
    if _cached_client is None or _cached_client_key != key:
        _cached_client = AsyncOpenAI(
            api_key=settings.aihubmix_api_key,
            base_url=settings.aihubmix_base_url,
        )
        _cached_client_key = key
    return _cached_client


def get_writer_client(novel_writer_model: str = "") -> tuple[AsyncOpenAI, str]:
    """返回 (client, model_name) 用于高质量生成"""
    model = novel_writer_model or settings.default_writer_model
    return _make_client(), model


def get_fast_client(novel_fast_model: str = "") -> tuple[AsyncOpenAI, str]:
    """返回 (client, model_name) 用于规划/摘要等低成本任务"""
    model = novel_fast_model or settings.default_fast_model
    return _make_client(), model


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
) -> tuple[AsyncOpenAI, str]:
    """
    按优先级解析 Agent 使用的模型：
      novel_override > agent-level setting > category default (writer/fast)
    """
    if novel_override:
        return _make_client(), novel_override

    setting_field, category = _AGENT_MODEL_MAP.get(agent_type, ("", "fast"))
    agent_model = getattr(settings, setting_field, "") if setting_field else ""
    if agent_model:
        return _make_client(), agent_model

    if category == "writer":
        return _make_client(), settings.default_writer_model
    return _make_client(), settings.default_fast_model


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
