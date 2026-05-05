import logging
import httpx
from openai import AsyncOpenAI
from typing import AsyncIterator, Union
from app.config import settings

# ─── 客户端字典缓存（按供应商凭据缓存，支持多个同格式供应商）──────────────
_openai_clients: dict[tuple, AsyncOpenAI] = {}
_gemini_clients: dict[tuple, object] = {}
_anthropic_clients: dict[tuple, object] = {}

# ─── 向后兼容：全局单例（供未关联 provider 的旧模型使用）─────────────────────
_cached_client: AsyncOpenAI | None = None
_cached_client_key: tuple = ("", "", "", "")

_cached_gemini_client = None
_cached_gemini_key: tuple = ("", "", "", "")

_cached_anthropic_client = None
_cached_anthropic_key: tuple = ("", "", "", "")

# ─── 模型格式缓存（model_id → api_format）─────────────────────────────────
_model_formats: dict[str, str] = {}

# ─── 供应商缓存 ─────────────────────────────────────────────────────────────
_providers_cache: dict[int, dict] = {}       # provider_id → {name, api_key, base_url, api_format}
_model_provider_map: dict[str, int] = {}     # model_id → provider_id


def _build_httpx_client() -> httpx.AsyncClient:
    """构建带代理设置的 httpx 客户端"""
    mounts: dict = {}
    if settings.https_proxy:
        mounts["https://"] = httpx.AsyncHTTPTransport(proxy=settings.https_proxy)
    if settings.http_proxy:
        mounts["http://"] = httpx.AsyncHTTPTransport(proxy=settings.http_proxy)
    return httpx.AsyncClient(mounts=mounts or None, trust_env=False)


def _get_openai_client_for(api_key: str, base_url: str) -> AsyncOpenAI:
    """按 (api_key, base_url) 获取或创建缓存的 AsyncOpenAI 客户端。"""
    cache_key = (api_key, base_url, settings.https_proxy, settings.http_proxy)
    if cache_key not in _openai_clients:
        _openai_clients[cache_key] = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=_build_httpx_client(),
        )
    return _openai_clients[cache_key]


def _get_gemini_client_for(api_key: str, base_url: str):
    """按 (api_key, base_url) 获取或创建缓存的 genai.Client。"""
    cache_key = (api_key, base_url, settings.https_proxy, settings.http_proxy)
    if cache_key not in _gemini_clients:
        from google import genai
        client_kwargs: dict = {"api_key": api_key}
        if base_url:
            client_kwargs["http_options"] = {"base_url": base_url}
        _gemini_clients[cache_key] = genai.Client(**client_kwargs)
    return _gemini_clients[cache_key]


def _get_anthropic_client_for(api_key: str, base_url: str):
    """按 (api_key, base_url) 获取或创建缓存的 AsyncAnthropic 客户端。"""
    cache_key = (api_key, base_url, settings.https_proxy, settings.http_proxy)
    if cache_key not in _anthropic_clients:
        import anthropic
        kwargs = {
            "api_key": api_key or "placeholder",
            "http_client": _build_httpx_client(),
        }
        if base_url:
            kwargs["base_url"] = base_url
        _anthropic_clients[cache_key] = anthropic.AsyncAnthropic(**kwargs)
    return _anthropic_clients[cache_key]


def _make_client() -> AsyncOpenAI:
    """返回全局复用的 AsyncOpenAI 客户端（向后兼容，未配置 provider 时使用）。"""
    global _cached_client, _cached_client_key
    key = (settings.openai_api_key, settings.openai_base_url,
           settings.https_proxy, settings.http_proxy)
    if _cached_client is None or _cached_client_key != key:
        _cached_client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            http_client=_build_httpx_client(),
        )
        _cached_client_key = key
    return _cached_client


async def refresh_model_formats(session) -> None:
    """从数据库重建 model_id → api_format 内存映射"""
    from sqlalchemy import select
    from app.models.model_library import ModelEntry
    result = await session.execute(select(ModelEntry))
    _model_formats.clear()
    _model_provider_map.clear()
    for m in result.scalars():
        _model_formats[m.model_id] = m.api_format
        if m.provider_id:
            _model_provider_map[m.model_id] = m.provider_id


async def refresh_provider_cache(session) -> None:
    """从数据库重建 provider_id → 供应商凭据 内存映射"""
    from sqlalchemy import select
    from app.models.api_provider import ApiProvider
    result = await session.execute(select(ApiProvider))
    _providers_cache.clear()
    for p in result.scalars():
        _providers_cache[p.id] = {
            "name": p.name,
            "api_key": p.api_key,
            "base_url": p.base_url,
            "api_format": p.api_format,
        }


def _get_provider_config(model: str) -> dict | None:
    """查找模型对应的供应商配置。未找到则返回 None（回退到全局 settings）。"""
    provider_id = _model_provider_map.get(model)
    if provider_id and provider_id in _providers_cache:
        return _providers_cache[provider_id]
    return None


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

def _resolve_client(model: str, api_format: str):
    """根据模型的供应商配置获取对应客户端。回退到全局 settings 单例。"""
    provider = _get_provider_config(model)
    if provider:
        fmt = provider["api_format"]
        if fmt == "gemini":
            return "gemini", _get_gemini_client_for(provider["api_key"], provider["base_url"])
        elif fmt == "anthropic":
            return "anthropic", _get_anthropic_client_for(provider["api_key"], provider["base_url"])
        else:
            return "openai", _get_openai_client_for(provider["api_key"], provider["base_url"])
    # 回退到全局 settings
    if api_format == "gemini":
        return "gemini", _make_gemini_client()
    elif api_format == "anthropic":
        return "anthropic", _make_anthropic_client()
    else:
        return "openai", _make_client()


async def dispatch_chat_complete(
    messages: list[dict],
    model: str,
    api_format: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """根据 api_format 分发非流式调用，返回文本内容"""
    fmt, client = _resolve_client(model, api_format)
    if fmt == "gemini":
        return await _gemini_complete(messages, model, temperature, max_tokens, client)
    elif fmt == "anthropic":
        return await _anthropic_complete(messages, model, temperature, max_tokens, client)
    else:
        return await chat_complete(messages, model, client, temperature, max_tokens)


async def dispatch_chat_complete_with_usage(
    messages: list[dict],
    model: str,
    api_format: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> tuple[str, int, int]:
    """根据 api_format 分发非流式调用，返回 (content, input_tokens, output_tokens)"""
    fmt, client = _resolve_client(model, api_format)
    if fmt == "gemini":
        return await _gemini_complete_with_usage(messages, model, temperature, max_tokens, client)
    elif fmt == "anthropic":
        return await _anthropic_complete_with_usage(messages, model, temperature, max_tokens, client)
    else:
        return await chat_complete_with_usage(messages, model, client, temperature, max_tokens)


async def dispatch_chat_stream_with_usage(
    messages: list[dict],
    model: str,
    api_format: str,
    temperature: float = 0.85,
    max_tokens: int = 4096,
    thinking_level: str = "medium",
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    """根据 api_format 分发流式调用，yield str token 最后 yield (in_tok, out_tok)。
    可能 yield dict 表示元信息（如 {"warning": "..."} 重试提醒）。"""
    fmt, client = _resolve_client(model, api_format)
    if fmt == "gemini":
        async for item in _gemini_stream_with_usage(messages, model, temperature, max_tokens, thinking_level, client):
            yield item
    elif fmt == "anthropic":
        async for item in _anthropic_stream_with_usage(messages, model, temperature, max_tokens, client):
            yield item
    else:
        async for item in chat_stream_with_usage(messages, model, client, temperature, max_tokens, thinking_level):
            yield item


# ─── Gemini REST 实现（匹配 Cherry Studio payload 格式）──────────────────
# 不使用 google-genai SDK，直接用 httpx POST REST API，
# 完全控制发出的 JSON 格式，避免代理（AiHubMix）不透传 safetySettings 等问题。


# ─── Gemini Thinking 分级管理 ─────────────────────────────────────────────

def _is_gemini_3x(model_id: str) -> bool:
    """Gemini 3.x 系列（3.0、3.1 等），使用 thinkingLevel API"""
    return "gemini-3" in model_id.lower()


def _is_gemini_pro(model_id: str) -> bool:
    return "-pro" in model_id.lower()


def _is_gemini_flash(model_id: str) -> bool:
    return "-flash" in model_id.lower()


def _is_deepseek_model(model_id: str) -> bool:
    """DeepSeek 模型，需要通过 extra_body 启用 thinking"""
    return "deepseek" in model_id.lower()


# 参考 Cherry Studio THINKING_TOKEN_MAP (config/models/reasoning.ts:775-779)
_GEMINI_2X_THINKING_LIMITS: dict[str, tuple[int, int]] = {
    "flash_lite": (512, 24576),
    "flash":      (0, 24576),
    "pro":        (128, 32768),
}


def _get_2x_thinking_limits(model_id: str) -> tuple[int, int]:
    """获取 Gemini 2.x 模型的 (min_budget, max_budget)"""
    lower = model_id.lower()
    if "flash-lite" in lower:
        return _GEMINI_2X_THINKING_LIMITS["flash_lite"]
    elif "-flash" in lower:
        return _GEMINI_2X_THINKING_LIMITS["flash"]
    return _GEMINI_2X_THINKING_LIMITS["pro"]


def _resolve_gemini_thinking(model_id: str, thinking_level: str = "medium"):
    """根据模型版本和 thinking_level 返回 types.ThinkingConfig。

    thinking_level: "off" | "low" | "medium" | "high"
    """
    from google.genai import types as genai_types

    if thinking_level == "off":
        if _is_gemini_3x(model_id):
            lowest = genai_types.ThinkingLevel.MINIMAL if _is_gemini_flash(model_id) else genai_types.ThinkingLevel.LOW
            return genai_types.ThinkingConfig(thinking_level=lowest)
        min_budget, _ = _get_2x_thinking_limits(model_id)
        return genai_types.ThinkingConfig(thinking_budget=min_budget)

    if _is_gemini_3x(model_id):
        level_map = {
            "low": genai_types.ThinkingLevel.LOW,
            "medium": genai_types.ThinkingLevel.MEDIUM,
            "high": genai_types.ThinkingLevel.HIGH,
        }
        level = level_map.get(thinking_level, genai_types.ThinkingLevel.MEDIUM)
        if _is_gemini_pro(model_id) and level == genai_types.ThinkingLevel.MEDIUM and "3.0" in model_id:
            level = genai_types.ThinkingLevel.LOW
        return genai_types.ThinkingConfig(thinking_level=level)

    # Gemini 2.x → thinkingBudget
    min_budget, max_budget = _get_2x_thinking_limits(model_id)
    ratio_map = {"low": 0.2, "medium": 0.5, "high": 0.85}
    ratio = ratio_map.get(thinking_level, 0.5)
    budget = int((max_budget - min_budget) * ratio + min_budget)
    return genai_types.ThinkingConfig(thinking_budget=budget)


def _make_gemini_client():
    """返回复用的 genai.Client，按 AiHubMix 推荐：api_key 通过 header 传递，非 URL 参数。"""
    global _cached_gemini_client, _cached_gemini_key
    key = (settings.gemini_api_key, settings.gemini_base_url,
           settings.https_proxy, settings.http_proxy)
    if _cached_gemini_client is not None and _cached_gemini_key == key:
        return _cached_gemini_client

    from google import genai

    client_kwargs: dict = {"api_key": settings.gemini_api_key}
    if settings.gemini_base_url:
        client_kwargs["http_options"] = {"base_url": settings.gemini_base_url}
    proxy = settings.https_proxy or settings.http_proxy or None
    if proxy:
        client_kwargs["http_options"] = {
            **(client_kwargs.get("http_options", {})),
            "headers": {},  # placeholder; proxy 由底层 httpx 环境变量处理
        }

    _cached_gemini_client = genai.Client(**client_kwargs)
    _cached_gemini_key = key
    return _cached_gemini_client


def _parse_gemini_response(response) -> tuple[str, int, int, str]:
    """解析 genai SDK 响应 → (text, input_tokens, output_tokens, finish_reason_str)"""
    text = ""
    finish_reason = ""
    if response.candidates:
        candidate = response.candidates[0]
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                # 跳过 thinking 部分，只取正文
                if part.text and not getattr(part, "thought", False):
                    text += part.text
        if candidate.finish_reason:
            finish_reason = str(candidate.finish_reason.name) if hasattr(candidate.finish_reason, "name") else str(candidate.finish_reason)

    in_tok = 0
    out_tok = 0
    if response.usage_metadata:
        in_tok = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        out_tok = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
    return text, in_tok, out_tok, finish_reason


async def _gemini_call(
    model: str,
    contents: list,
    system_instruction: str = "",
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
    thinking_config=None,
    client=None,
):
    """使用 genai SDK 发送非流式 Gemini 请求，返回 SDK response 对象。"""
    from google.genai import types as genai_types

    if client is None:
        client = _make_gemini_client()

    config_kwargs: dict = {"temperature": temperature}
    if max_output_tokens is not None:
        config_kwargs["max_output_tokens"] = max_output_tokens
    if thinking_config is not None:
        config_kwargs["thinking_config"] = thinking_config
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction

    return await client.aio.models.generate_content(
        model=model,
        contents=contents,
        config=genai_types.GenerateContentConfig(**config_kwargs),
    )


async def _gemini_complete(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
    client=None,
) -> str:
    system_instruction, contents = _to_gemini_contents(messages)
    response = await _gemini_call(
        model=model,
        contents=contents,
        system_instruction=system_instruction,
        temperature=temperature,
        max_output_tokens=max_tokens,
        thinking_config=_resolve_gemini_thinking(model, thinking_level="off"),
        client=client,
    )
    text, _, _, _ = _parse_gemini_response(response)
    return text


async def _gemini_complete_with_usage(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
    client=None,
) -> tuple[str, int, int]:
    system_instruction, contents = _to_gemini_contents(messages)
    response = await _gemini_call(
        model=model,
        contents=contents,
        system_instruction=system_instruction,
        temperature=temperature,
        max_output_tokens=max_tokens,
        thinking_config=_resolve_gemini_thinking(model, thinking_level="off"),
        client=client,
    )
    text, in_tok, out_tok, finish_reason = _parse_gemini_response(response)
    if finish_reason and finish_reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
        logging.getLogger(__name__).warning(
            "Gemini 非流式调用异常结束: finish_reason=%s, model=%s, out_tok=%d",
            finish_reason, model, out_tok,
        )
    return text, in_tok, out_tok


async def _gemini_stream_with_usage(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
    thinking_level: str = "medium",
    client=None,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    """Gemini 生成（genai SDK 非流式调用 + 模拟流式输出）。

    先通过 SDK 获取完整响应，检查空响应/安全拦截后按 chunk 逐段 yield。
    """
    import asyncio
    import logging
    logger = logging.getLogger(__name__)
    system_instruction, contents = _to_gemini_contents(messages)

    thinking_config = _resolve_gemini_thinking(model, thinking_level=thinking_level)

    # Writer 场景不传 max_output_tokens，让模型自由决定输出长度
    response = await _gemini_call(
        model=model,
        contents=contents,
        system_instruction=system_instruction,
        temperature=temperature,
        max_output_tokens=None,
        thinking_config=thinking_config,
        client=client,
    )
    text, in_tok, out_tok, finish_reason_str = _parse_gemini_response(response)

    finish_reason: str | None = None
    if "MAX_TOKENS" in finish_reason_str:
        finish_reason = "length"

    # ── 空响应时记录原始响应用于诊断 ──
    if not text:
        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(prompt_feedback, "block_reason", "") if prompt_feedback else ""
        logger.warning(
            "Gemini 空响应诊断: model=%s, finish_reason=%s, block_reason=%s, "
            "has_candidates=%s",
            model, finish_reason_str, block_reason, bool(response.candidates),
        )
        if block_reason:
            raise RuntimeError(
                f"Gemini 在 prompt 级别拦截了请求（blockReason={block_reason}）。"
                f"这是模型对输入内容的安全过滤，与 safetySettings 无关。"
            )

    # ── 空响应时自动重试一次：关闭 thinking、降低温度 ──
    if not text and in_tok > 0:
        logger.warning(
            "Gemini 非流式空响应（model=%s, finish_reason=%s, in_tok=%d），"
            "关闭 thinking 重试...",
            model, finish_reason_str, in_tok,
        )
        yield {"warning": "Gemini 首次生成无输出，正在关闭 Thinking 并降低温度重试..."}
        response = await _gemini_call(
            model=model,
            contents=contents,
            system_instruction=system_instruction,
            temperature=max(temperature - 0.2, 0.1),
            max_output_tokens=max_tokens,
            thinking_config=_resolve_gemini_thinking(model, thinking_level="off"),
            client=client,
        )
        text, in_tok, out_tok, finish_reason_str = _parse_gemini_response(response)
        finish_reason = None
        if "MAX_TOKENS" in finish_reason_str:
            finish_reason = "length"

    # ── 检测非正常结束 ──
    if not text:
        _NORMAL = {"STOP", "MAX_TOKENS", "FINISH_REASON_UNSPECIFIED"}
        if finish_reason_str and finish_reason_str not in _NORMAL:
            raise RuntimeError(
                f"Gemini 安全过滤拦截了本次生成（finish_reason={finish_reason_str}）。"
                f"请修改指令内容，避免涉及敏感描写，或更换过滤较宽松的模型。"
            )
        if in_tok > 0:
            raise RuntimeError(
                f"Gemini 处理了请求（input_tokens={in_tok}）但未生成任何内容，"
                f"通常是安全过滤触发。请修改指令中的敏感内容，或更换模型（如 GPT-4o）。"
            )

    # ── 模拟流式输出：按 chunk yield ──
    CHUNK_SIZE = 20
    for i in range(0, len(text), CHUNK_SIZE):
        yield text[i:i + CHUNK_SIZE]
        await asyncio.sleep(0)

    yield (finish_reason, in_tok, out_tok)


# ─── Anthropic 原生实现 ────────────────────────────────────────────────────

def _make_anthropic_client():
    """返回全局复用的 Anthropic 客户端，当配置变化时自动重建。"""
    global _cached_anthropic_client, _cached_anthropic_key
    key = (settings.anthropic_api_key, settings.anthropic_base_url,
           settings.https_proxy, settings.http_proxy)
    if _cached_anthropic_client is not None and _cached_anthropic_key == key:
        return _cached_anthropic_client

    import anthropic
    mounts: dict = {}
    if settings.https_proxy:
        mounts["https://"] = httpx.AsyncHTTPTransport(proxy=settings.https_proxy)
    if settings.http_proxy:
        mounts["http://"] = httpx.AsyncHTTPTransport(proxy=settings.http_proxy)
    http_client = httpx.AsyncClient(mounts=mounts or None, trust_env=False)
    kwargs = {
        "api_key": settings.anthropic_api_key or "placeholder",
        "http_client": http_client,
    }
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    _cached_anthropic_client = anthropic.AsyncAnthropic(**kwargs)
    _cached_anthropic_key = key
    return _cached_anthropic_client


async def _anthropic_complete(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
    client=None,
) -> str:
    system_prompt, filtered = _to_anthropic_messages(messages)
    if client is None:
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
    client=None,
) -> tuple[str, int, int]:
    system_prompt, filtered = _to_anthropic_messages(messages)
    if client is None:
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
    client=None,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    system_prompt, filtered = _to_anthropic_messages(messages)
    if client is None:
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
    finish_reason: str | None = None
    async with client.messages.stream(**kwargs) as stream:
        async for text in stream.text_stream:
            yield text
        final = await stream.get_final_message()
        finish_reason = getattr(final, "stop_reason", None)  # "max_tokens" = truncated
        if finish_reason == "max_tokens":
            finish_reason = "length"
        if final.usage:
            in_tok = final.usage.input_tokens or 0
            out_tok = final.usage.output_tokens or 0
    yield (finish_reason, in_tok, out_tok)


# ─── 旧式 OpenAI 调用（保留向后兼容）─────────────────────────────────────

async def chat_complete(
    messages: list[dict],
    model: str,
    client: AsyncOpenAI,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """非流式调用"""
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # DeepSeek V4 默认开启 thinking，非流式结构化任务需显式关闭
    if _is_deepseek_model(model):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


async def chat_complete_with_usage(
    messages: list[dict],
    model: str,
    client: AsyncOpenAI,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> tuple[str, int, int]:
    """非流式调用，返回 (content, input_tokens, output_tokens)"""
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if _is_deepseek_model(model):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    response = await client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    content = choice.message.content or ""
    if choice.finish_reason and choice.finish_reason != "stop":
        logging.getLogger(__name__).warning(
            "OpenAI 非流式调用异常结束: finish_reason=%s, model=%s",
            choice.finish_reason, model,
        )
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
    thinking_level: str = "off",
) -> AsyncIterator[str]:
    """流式调用，逐 token yield"""
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if _is_deepseek_model(model):
        if thinking_level != "off":
            kwargs["extra_body"] = {
                "thinking": {"type": "enabled"},
                "reasoning_effort": thinking_level,
            }
        else:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    stream = await client.chat.completions.create(**kwargs)
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
    thinking_level: str = "off",
) -> AsyncIterator[Union[str, tuple]]:
    """
    流式调用，逐 token yield str。
    最后 yield (finish_reason, input_tokens, output_tokens)。
    finish_reason == "length" 表示内容被 token 上限截断。
    """
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if _is_deepseek_model(model):
        if thinking_level != "off":
            kwargs["extra_body"] = {
                "thinking": {"type": "enabled"},
                "reasoning_effort": thinking_level,
            }
        else:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    stream = await client.chat.completions.create(**kwargs)
    in_tok = 0
    out_tok = 0
    finish_reason: str | None = None
    async for chunk in stream:
        if chunk.choices:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason
        if chunk.usage:
            in_tok = chunk.usage.prompt_tokens or 0
            out_tok = chunk.usage.completion_tokens or 0
    yield (finish_reason, in_tok, out_tok)
