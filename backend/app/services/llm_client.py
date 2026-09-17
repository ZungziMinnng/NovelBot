import logging
import httpx
from openai import AsyncOpenAI
from typing import AsyncIterator, Union
from app.config import settings
from app.services.auth import current_user_var

logger = logging.getLogger(__name__)


def _current_non_admin():
    """当前请求上下文中的非 admin 用户；admin 或无上下文（启动/测试/后台任务）返回 None。
    非 admin 用户的模型解析必须限制在其本人的模型库内，绝不回退到全局 .env 配置。"""
    user = current_user_var.get()
    if user is None or user.is_admin:
        return None
    return user

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
_providers_cache: dict[int, dict] = {}
_model_provider_map: dict[str, int] = {}

# ─── 模型条目索引（ModelEntry.id → 明细）：以 id 作唯一身份消歧同名 model_id ──
_entry_index: dict[int, dict] = {}


def clear_llm_client_cache() -> None:
    global _cached_client, _cached_client_key
    global _cached_gemini_client, _cached_gemini_key
    global _cached_anthropic_client, _cached_anthropic_key
    _openai_clients.clear()
    _gemini_clients.clear()
    _anthropic_clients.clear()
    _cached_client = None
    _cached_client_key = ("", "", "", "")
    _cached_gemini_client = None
    _cached_gemini_key = ("", "", "", "")
    _cached_anthropic_client = None
    _cached_anthropic_key = ("", "", "", "")


def _build_httpx_client(use_proxy: bool = True) -> httpx.AsyncClient:
    """构建 httpx 客户端。use_proxy=False 时即使配置了全局代理也直连（供可直连的供应商用）。"""
    mounts: dict = {}
    if use_proxy and settings.https_proxy:
        mounts["https://"] = httpx.AsyncHTTPTransport(proxy=settings.https_proxy)
    if use_proxy and settings.http_proxy:
        mounts["http://"] = httpx.AsyncHTTPTransport(proxy=settings.http_proxy)
    return httpx.AsyncClient(mounts=mounts or None, trust_env=False)


def _gemini_http_options(base_url: str = "", use_proxy: bool = True) -> dict:
    """构建 genai.Client 的 http_options：注入 base_url、NOVELBOT 代理，并 trust_env=False。
    genai SDK 不走 _build_httpx_client，需经 client_args 把这些透传给底层 httpx。
    trust_env=False 关键：否则 genai 默认读取 OS 环境代理（如不被 httpx 支持的 socks4），
    构造即失败 / 连接全失败。与 OpenAI/Anthropic 客户端保持一致。"""
    http_options: dict = {}
    if base_url:
        http_options["base_url"] = base_url
    client_args: dict = {"trust_env": False}
    proxy = (settings.https_proxy or settings.http_proxy) if use_proxy else ""
    if proxy:
        client_args["proxy"] = proxy
    http_options["client_args"] = client_args
    http_options["async_client_args"] = dict(client_args)
    return http_options


def _get_openai_client_for(api_key: str, base_url: str, use_proxy: bool = True) -> AsyncOpenAI:
    """按 (api_key, base_url, use_proxy) 获取或创建缓存的 AsyncOpenAI 客户端。"""
    cache_key = (api_key, base_url, use_proxy, settings.https_proxy, settings.http_proxy)
    if cache_key not in _openai_clients:
        _openai_clients[cache_key] = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=_build_httpx_client(use_proxy),
        )
    return _openai_clients[cache_key]


def _get_gemini_client_for(api_key: str, base_url: str, use_proxy: bool = True):
    """按 (api_key, base_url, use_proxy) 获取或创建缓存的 genai.Client。"""
    cache_key = (api_key, base_url, use_proxy, settings.https_proxy, settings.http_proxy)
    if cache_key not in _gemini_clients:
        from google import genai
        client_kwargs: dict = {"api_key": api_key}
        http_options = _gemini_http_options(base_url, use_proxy)
        if http_options:
            client_kwargs["http_options"] = http_options
        _gemini_clients[cache_key] = genai.Client(**client_kwargs)
    return _gemini_clients[cache_key]


def _get_anthropic_client_for(api_key: str, base_url: str, use_proxy: bool = True):
    """按 (api_key, base_url, use_proxy) 获取或创建缓存的 AsyncAnthropic 客户端。"""
    cache_key = (api_key, base_url, use_proxy, settings.https_proxy, settings.http_proxy)
    if cache_key not in _anthropic_clients:
        import anthropic
        kwargs = {
            "api_key": api_key or "placeholder",
            "http_client": _build_httpx_client(use_proxy),
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
    # 按 id 升序 + 首次写入优先：model_id 无唯一约束，若两个供应商注册同名 model_id，
    # 保持最早注册者的路由，新增供应商不会静默劫持已有模型（否则新供应商 base_url
    # 若填错会让原本正常的模型请求打到错误端点）。
    result = await session.execute(select(ModelEntry).order_by(ModelEntry.id))
    _model_formats.clear()
    _model_provider_map.clear()
    _entry_index.clear()
    for m in result.scalars():
        _model_formats.setdefault(m.model_id, m.api_format)
        if m.provider_id:
            _model_provider_map.setdefault(m.model_id, m.provider_id)
        # id 全局唯一：以 id 为键索引，供 resolve_model_ref 精确消歧同名 model_id
        _entry_index[m.id] = {
            "model_id": m.model_id,
            "api_format": m.api_format,
            "provider_id": m.provider_id,
            "user_id": m.user_id,
        }
    logger.info("LLM 模型映射缓存已刷新: models=%d provider_links=%d", len(_model_formats), len(_model_provider_map))


async def refresh_provider_cache(session) -> None:
    """从数据库重建 provider_id → 供应商凭据 内存映射"""
    from sqlalchemy import select
    from app.models.api_provider import ApiProvider
    result = await session.execute(select(ApiProvider))
    clear_llm_client_cache()
    _providers_cache.clear()
    for p in result.scalars():
        _providers_cache[p.id] = {
            "name": p.name,
            "api_key": p.api_key,
            "base_url": p.base_url,
            "api_format": p.api_format,
            "use_proxy": p.use_proxy,
            "user_id": p.user_id,
        }
    logger.info("LLM 供应商缓存已刷新，客户端缓存已清空: providers=%d", len(_providers_cache))


def get_model_api_format(model_id: str) -> str:
    """查询模型的 api_format，未录入则默认 openai"""
    return _model_formats.get(model_id, "openai")


def resolve_model_ref(ref: str) -> tuple[str, str, int | None]:
    """把存储的模型引用解析为 (real_model_id, api_format, provider_id|None)。

    ref 优先按 ModelEntry.id 解释（新方案，唯一无歧义）；否则按旧的 model_id
    字符串走"最早注册优先"回退（向后兼容旧数据 / 旧 .env，路由行为不变）。

    非 admin 用户只接受本人的 ModelEntry.id：字符串引用会命中"最早注册的同名
    模型"（可能是别人的供应商），必须拒绝，防止烧他人 API Key。"""
    user = _current_non_admin()
    if user is not None:
        entry = _entry_index.get(int(ref)) if ref and ref.isdigit() else None
        if entry is None or entry.get("user_id") != user.id:
            raise ValueError("模型引用无效或不属于当前用户")
        return entry["model_id"], entry["api_format"], entry["provider_id"]
    if ref and ref.isdigit() and int(ref) in _entry_index:
        e = _entry_index[int(ref)]
        return e["model_id"], e["api_format"], e["provider_id"]
    return ref, _model_formats.get(ref, "openai"), _model_provider_map.get(ref)


def _resolve_model(agent_type: str, novel_override: str = "") -> str:
    """按优先级解析最终使用的 model_id。
    非 admin 用户：小说指定 → 本人默认模型 → 报错，绝不落到全局 .env 配置。"""
    if novel_override:
        return novel_override
    setting_field, category = _AGENT_MODEL_MAP.get(agent_type, ("", "fast"))
    user = _current_non_admin()
    if user is not None:
        ref = user.default_writer_model if category == "writer" else user.default_fast_model
        if not ref:
            raise ValueError("请先在设置页配置默认模型，或在小说设置中选择模型")
        return ref
    agent_model = getattr(settings, setting_field, "") if setting_field else ""
    if agent_model:
        return agent_model
    if category == "writer":
        return settings.default_writer_model
    return settings.default_fast_model


def get_fast_client(novel_fast_model: str = "") -> tuple[str, str]:
    """返回 (model_ref, api_format) 用于规划/摘要等低成本任务。
    model_ref 原样透传（可能是 ModelEntry.id 或旧 model_id），由 dispatch 消歧。"""
    user = _current_non_admin()
    if user is not None:
        ref = novel_fast_model or user.default_fast_model
        if not ref:
            raise ValueError("请先在设置页配置默认模型，或在小说设置中选择模型")
    else:
        ref = novel_fast_model or settings.default_fast_model
    return ref, resolve_model_ref(ref)[1]


# Agent-type → (agent_setting_field, fallback_category)
_AGENT_MODEL_MAP: dict[str, tuple[str, str]] = {
    "writer":       ("agent_writer_model",       "writer"),
    "critic":       ("agent_critic_model",        "fast"),
    "memory":       ("agent_memory_model",        "fast"),
    "outline":      ("agent_outline_model",       "fast"),
    "character":    ("agent_character_model",     "fast"),
    "orchestrator": ("agent_orchestrator_model",  "fast"),
    "world":        ("agent_orchestrator_model",  "fast"),
    "review":       ("agent_review_model",        "fast"),
}


def get_agent_client(
    agent_type: str,
    novel_override: str = "",
) -> tuple[str, str]:
    """
    按优先级解析 Agent 使用的模型：
      novel_override > agent-level setting > category default (writer/fast)
    返回 (model_ref, api_format)。model_ref 原样透传（ModelEntry.id 或旧 model_id），
    由 dispatch 消歧；api_format 已解析正确以供调用方按格式分支。
    """
    ref = _resolve_model(agent_type, novel_override)
    return ref, resolve_model_ref(ref)[1]


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
    if not contents and system_instruction:
        # Gemini 要求 contents 非空。只发一条 system 的调用（RPG 一键生成那类
        # 纯指令活）抽完 system 就什么都不剩了，会被 400 掉，把它当 user 轮发出去
        return "", [{"role": "user", "parts": [{"text": system_instruction}]}]
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
    if not filtered and system_prompt:
        # 同 _to_gemini_contents：Anthropic 的 messages 也不能为空
        return "", [{"role": "user", "content": system_prompt}]
    return system_prompt, filtered


# ─── 统一分发函数 ──────────────────────────────────────────────────────────

def _resolve_dispatch(model_ref: str, api_format: str):
    """把流转的 model_ref（ModelEntry.id 或旧 model_id）解析为
    (real_model_id, client_fmt, client)。provider 由 id 精确定位，彻底消歧；
    未关联 provider 时回退全局 settings 单例。real_model_id 传给 provider SDK，
    确保 _is_deepseek_model / _gemini_* 等按模型名判断的逻辑收到真实名。"""
    real_model, fmt, provider_id = resolve_model_ref(model_ref)
    provider = _providers_cache.get(provider_id) if provider_id else None
    if provider:
        pfmt = provider["api_format"]
        up = provider.get("use_proxy", True)
        if pfmt == "gemini":
            return real_model, "gemini", _get_gemini_client_for(provider["api_key"], provider["base_url"], up)
        elif pfmt == "anthropic":
            return real_model, "anthropic", _get_anthropic_client_for(provider["api_key"], provider["base_url"], up)
        else:
            return real_model, "openai", _get_openai_client_for(provider["api_key"], provider["base_url"], up)
    # 回退到全局 settings（用解析出的 fmt，兜底调用方传入的 api_format）
    use_fmt = fmt or api_format
    if use_fmt == "gemini":
        return real_model, "gemini", _make_gemini_client()
    elif use_fmt == "anthropic":
        return real_model, "anthropic", _make_anthropic_client()
    else:
        return real_model, "openai", _make_client()


async def dispatch_chat_complete(
    messages: list[dict],
    model: str,
    api_format: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """根据 api_format 分发非流式调用，返回文本内容"""
    real_model, fmt, client = _resolve_dispatch(model, api_format)
    # 同流式那条路：思考模型的 max_output_tokens 是「思考链 + 正文」共用的，
    # 原样透传会让思考挤掉正文，正文说到一半就 MAX_TOKENS。
    # 在分发**之前**算，openai 兼容那一路上也可能挂着思考模型
    eff_max_tokens = _effective_max_tokens(real_model, fmt, max_tokens, "off", "off")
    if fmt == "gemini":
        return await _gemini_complete(
            messages, real_model, temperature, eff_max_tokens, client,
        )
    elif fmt == "anthropic":
        return await _anthropic_complete(messages, real_model, temperature, max_tokens, client)
    else:
        return await chat_complete(messages, real_model, client, temperature, eff_max_tokens)


async def dispatch_chat_complete_with_usage(
    messages: list[dict],
    model: str,
    api_format: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> tuple[str, int, int]:
    """根据 api_format 分发非流式调用，返回 (content, input_tokens, output_tokens)"""
    real_model, fmt, client = _resolve_dispatch(model, api_format)
    eff_max_tokens = _effective_max_tokens(real_model, fmt, max_tokens, "off", "off")
    if fmt == "gemini":
        return await _gemini_complete_with_usage(
            messages, real_model, temperature, eff_max_tokens, client,
        )
    elif fmt == "anthropic":
        return await _anthropic_complete_with_usage(messages, real_model, temperature, max_tokens, client)
    else:
        return await chat_complete_with_usage(messages, real_model, client, temperature, eff_max_tokens)


async def dispatch_chat_stream_with_usage(
    messages: list[dict],
    model: str,
    api_format: str,
    temperature: float = 0.85,
    max_tokens: int = 4096,
    gemini_thinking_level: str = "medium",
    deepseek_thinking_level: str = "high",
    gemini_stream: bool = False,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    """根据 api_format 分发流式调用，yield str token 最后 yield (in_tok, out_tok)。
    Gemini 用 gemini_thinking_level，DeepSeek（走 openai 格式）用 deepseek_thinking_level。
    可能 yield dict 表示元信息（如 {"warning": "..."} 重试提醒）。"""
    real_model, fmt, client = _resolve_dispatch(model, api_format)
    # 思考模型的 max_output_tokens 覆盖「思考链 + 正文」，在用户配置之上叠加思考预算，
    # 使配置值实际作用于正文，避免正文被思考链挤占而提前截断。
    eff_max_tokens = _effective_max_tokens(
        real_model, fmt, max_tokens, gemini_thinking_level, deepseek_thinking_level)
    if fmt == "gemini":
        if gemini_stream:
            async for item in _gemini_true_stream_with_usage(messages, real_model, temperature, eff_max_tokens, gemini_thinking_level, client):
                yield item
        else:
            # 假流式=非流式大请求+本地切片：在 SOCKS 代理上零字节空等整段响应，
            # 极易被闪断（ReadError）。若在吐出任何正文前遭遇传输层网络错误，自动改走
            # 真流式重试一次——真流式持续有字节流动，代理不掐断。此刻必然未 yield 过 str
            # （切片在拿到完整响应之后、纯内存操作），故切换不会重复输出；produced 双保险。
            produced = False
            try:
                async for item in _gemini_stream_with_usage(messages, real_model, temperature, eff_max_tokens, gemini_thinking_level, client):
                    if isinstance(item, str):
                        produced = True
                    yield item
            except _TRANSIENT_NET_ERRORS as e:
                if produced:
                    raise
                logging.getLogger(__name__).warning(
                    "Gemini 假流式网络闪断（%s: %r），自动改走真流式重试", type(e).__name__, e,
                )
                yield {"warning": "Gemini 非流式连接闪断，正在自动改用真实流式重试..."}
                async for item in _gemini_true_stream_with_usage(messages, real_model, temperature, eff_max_tokens, gemini_thinking_level, client):
                    yield item
    elif fmt == "anthropic":
        async for item in _anthropic_stream_with_usage(messages, real_model, temperature, eff_max_tokens, client):
            yield item
    else:
        async for item in chat_stream_with_usage(messages, real_model, client, temperature, eff_max_tokens, deepseek_thinking_level):
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


def _deepseek_reasoning_effort(thinking_level: str) -> str:
    """将 DeepSeek 思考档位映射到 reasoning_effort 值。
    档位为 "high" | "max"（"off" 在上层走 thinking disabled，不会进入此函数）。"""
    return "max" if thinking_level == "max" else "high"


def _apply_deepseek_fast_thinking(kwargs: dict) -> None:
    """非流式快速任务按全局设置决定 DeepSeek 思考档位。
    开启时提高 max_tokens 下限：V4 的 max_tokens 覆盖思维链+正文，过低会截断输出。"""
    level = settings.deepseek_fast_thinking
    if level in ("high", "max"):
        kwargs["extra_body"] = {
            "thinking": {"type": "enabled"},
            "reasoning_effort": _deepseek_reasoning_effort(level),
        }
        kwargs["max_tokens"] = max(kwargs["max_tokens"], 8192)
    else:
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}


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


# Gemini 3.x 用 thinkingLevel（无显式预算），按档位估算需要额外预留的思考预算
_GEMINI_3X_THINKING_HEADROOM = {"low": 8192, "medium": 16384, "high": 32768}


def _gemini_thinking_headroom(model_id: str, thinking_level: str) -> int:
    """Gemini 的 max_output_tokens 覆盖「思考链 + 正文」。为使用户配置的
    max_tokens 实际作用于正文，这里返回需在其之上额外预留的思考预算。"""
    if thinking_level == "off":
        # "off" 不等于不思考：_resolve_gemini_thinking 给 3.x 的是 MINIMAL/LOW，
        # 给 2.x 的是 min_budget（pro 是 128）而不是 0。这里返回 0 的话，那点思考
        # 就从正文预算里扣，短 max_tokens 的调用会说到一半就 MAX_TOKENS
        if _is_gemini_3x(model_id):
            return _GEMINI_3X_THINKING_HEADROOM["low"]
        return _get_2x_thinking_limits(model_id)[0]
    if _is_gemini_3x(model_id):
        return _GEMINI_3X_THINKING_HEADROOM.get(thinking_level, 16384)
    # Gemini 2.x：思考预算显式可算
    min_budget, max_budget = _get_2x_thinking_limits(model_id)
    ratio_map = {"low": 0.2, "medium": 0.5, "high": 0.85}
    ratio = ratio_map.get(thinking_level, 0.5)
    return int((max_budget - min_budget) * ratio + min_budget)


def _effective_max_tokens(model_id: str, api_format: str, max_tokens: int,
                          gemini_thinking_level: str, deepseek_thinking_level: str) -> int:
    """在用户配置的 max_tokens 之上叠加思考预算，避免思考链挤占正文导致截断。
    仅作上限放宽：若上游本就不把思考计入 max_output_tokens，多出的预算不会被用到。"""
    GEMINI_HARD_CAP = 65536
    # 也认 openai 格式下的 Gemini：中转站（AiHubMix 这类）把 Gemini 挂在
    # OpenAI 兼容端点上，api_format 是 "openai"，但上游仍是 Gemini，
    # max_output_tokens 照样覆盖思考链。只看 api_format 会把这一路漏掉
    if api_format == "gemini" or "gemini" in model_id.lower():
        headroom = _gemini_thinking_headroom(model_id, gemini_thinking_level)
        return min(max_tokens + headroom, GEMINI_HARD_CAP)
    if _is_deepseek_model(model_id) and deepseek_thinking_level in ("high", "max"):
        # DeepSeek max_tokens 覆盖思维链 + 正文，思维链可达数万 token
        return min(max_tokens + 32768, GEMINI_HARD_CAP)
    return max_tokens


def _make_gemini_client():
    """返回复用的 genai.Client，按 AiHubMix 推荐：api_key 通过 header 传递，非 URL 参数。"""
    global _cached_gemini_client, _cached_gemini_key
    key = (settings.gemini_api_key, settings.gemini_base_url,
           settings.https_proxy, settings.http_proxy)
    if _cached_gemini_client is not None and _cached_gemini_key == key:
        return _cached_gemini_client

    from google import genai

    client_kwargs: dict = {"api_key": settings.gemini_api_key}
    http_options = _gemini_http_options(settings.gemini_base_url)
    if http_options:
        client_kwargs["http_options"] = http_options

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


def _gemini_block_message(block_reason) -> str:
    """根据 blockReason 给出可操作的中文报错。"""
    reason = getattr(block_reason, "name", str(block_reason))
    if "PROHIBITED_CONTENT" in reason:
        return (
            "Gemini 在 prompt 级别拦截了请求（blockReason=PROHIBITED_CONTENT）。"
            "这属于 Google 核心政策的硬过滤，无法通过 safetySettings 或任何 API 参数绕过。"
            "请软化/改写输入内容，或为该场景改用其他模型（如 NSFW 场景换非 Gemini 模型）。"
        )
    return (
        f"Gemini 在 prompt 级别拦截了请求（blockReason={reason}）。"
        "已对可配置类别设为 BLOCK_NONE；若仍被拦截，请改写输入内容或更换模型。"
    )


_cached_gemini_safety = None


def _gemini_safety_settings():
    """对四个可配置类别设 BLOCK_NONE，尽量放宽 SAFETY 类拦截。
    注意：PROHIBITED_CONTENT 属 Google 核心政策硬过滤，不受 safetySettings 影响。"""
    global _cached_gemini_safety
    if _cached_gemini_safety is not None:
        return _cached_gemini_safety
    from google.genai import types as genai_types

    categories = [
        genai_types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        genai_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        genai_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        genai_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    ]
    _cached_gemini_safety = [
        genai_types.SafetySetting(category=c, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE)
        for c in categories
    ]
    return _cached_gemini_safety


# 传输层瞬时网络错误：经代理调用 Gemini 时常见的闪断/超时。google-genai 自带的
# tenacity 重试只认部分 HTTP 状态码（429/503 等），不覆盖这些 httpx 传输异常，
# 一次闪断就会让整章生成失败并 ROLLBACK，故在非流式入口自行重试。
_TRANSIENT_NET_ERRORS = (
    httpx.ReadError, httpx.WriteError, httpx.ConnectError,
    httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout,
    httpx.PoolTimeout, httpx.RemoteProtocolError,
)
_GEMINI_NET_RETRIES = 3


async def _gemini_call(
    model: str,
    contents: list,
    system_instruction: str = "",
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
    thinking_config=None,
    client=None,
):
    """使用 genai SDK 发送非流式 Gemini 请求，返回 SDK response 对象。
    非流式调用幂等，对传输层瞬时网络错误做带退避重试（代理闪断兜底）。"""
    import asyncio
    from google.genai import types as genai_types

    if client is None:
        client = _make_gemini_client()

    config_kwargs: dict = {}
    if temperature >= 0:
        config_kwargs["temperature"] = temperature
    if max_output_tokens is not None:
        config_kwargs["max_output_tokens"] = max_output_tokens
    if thinking_config is not None:
        config_kwargs["thinking_config"] = thinking_config
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    config_kwargs["safety_settings"] = _gemini_safety_settings()

    last_exc: Exception | None = None
    for attempt in range(_GEMINI_NET_RETRIES):
        try:
            return await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=genai_types.GenerateContentConfig(**config_kwargs),
            )
        except _TRANSIENT_NET_ERRORS as e:
            last_exc = e
            if attempt < _GEMINI_NET_RETRIES - 1:
                delay = 1.5 * (attempt + 1)
                logger.warning(
                    "Gemini 非流式网络闪断（%s: %r），%.1fs 后重试 (%d/%d)",
                    type(e).__name__, e, delay, attempt + 1, _GEMINI_NET_RETRIES - 1,
                )
                await asyncio.sleep(delay)
    raise last_exc


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
    text, _, _, cut = _parse_gemini_response(response)
    # 吐了一半也是截断，只是不为空所以下面那些 raise 都躲过去了。JSON 那条路
    # repair_json 还会把残缺补成合法结构，静默得更彻底——至少留条日志能查
    if text and cut == "MAX_TOKENS":
        logger.warning(
            "Gemini 非流式输出被截断: model=%s, max_tokens=%d, 已出 %d 字",
            model, max_tokens, len(text),
        )
    if not text:
        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(prompt_feedback, "block_reason", "") if prompt_feedback else ""
        _, in_tok, out_tok, finish_reason = _parse_gemini_response(response)
        logger.warning(
            "Gemini 非流式空响应: model=%s, finish_reason=%s, block_reason=%s, in_tok=%d, out_tok=%d",
            model, finish_reason, block_reason, in_tok, out_tok,
        )
        if block_reason:
            raise RuntimeError(_gemini_block_message(block_reason))
        if finish_reason == "MAX_TOKENS":
            raise RuntimeError(
                f"Gemini 输出 token 预算耗尽（finish_reason=MAX_TOKENS, max_tokens={max_tokens}），"
                "请增大 max_tokens 或缩短输入内容。"
            )
        safety_reasons = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
        if finish_reason in safety_reasons:
            raise RuntimeError(f"Gemini 未生成内容（finish_reason={finish_reason}），内容被安全过滤。")
        if finish_reason and finish_reason not in ("", "STOP", "FINISH_REASON_UNSPECIFIED"):
            raise RuntimeError(f"Gemini 未生成内容（finish_reason={finish_reason}），模型提前终止。")
        raise RuntimeError("Gemini 未生成任何内容，请修改输入内容或更换大纲/快速模型。")
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
            "Gemini 非流式调用异常结束: finish_reason=%s, model=%s, out_tok=%d, 已出 %d 字",
            finish_reason, model, out_tok, len(text),
        )
        if not text and finish_reason == "MAX_TOKENS":
            raise RuntimeError(
                f"Gemini 输出 token 预算耗尽（finish_reason=MAX_TOKENS, max_tokens={max_tokens}），"
                "请增大 max_tokens 或缩短输入内容。"
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
            raise RuntimeError(_gemini_block_message(block_reason))

    # ── 空响应时自动重试一次：关闭 thinking、降低温度 ──
    # 含 in_tok==0 的瞬时空响应（aihubmix/Gemini 偶发，has_candidates=False）也重试，
    # 避免单次上游抖动直接整章失败 ROLLBACK。
    if not text:
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


async def _gemini_true_stream_with_usage(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
    thinking_level: str = "medium",
    client=None,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    """Gemini 真实流式生成：使用 SDK generate_content_stream 逐 chunk 输出。"""
    import asyncio
    import logging
    from google.genai import types as genai_types
    logger = logging.getLogger(__name__)

    if client is None:
        client = _make_gemini_client()

    system_instruction, contents = _to_gemini_contents(messages)
    thinking_config = _resolve_gemini_thinking(model, thinking_level=thinking_level)

    config_kwargs: dict = {"temperature": temperature}
    if max_tokens is not None:
        config_kwargs["max_output_tokens"] = max_tokens
    if thinking_config is not None:
        config_kwargs["thinking_config"] = thinking_config
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    # 与非流式路径对齐：不加 safety_settings 时 Gemini 用默认严格过滤，
    # 小说正文（尤其敏感描写）会被拦截并抛空异常，导致整章生成失败。
    config_kwargs["safety_settings"] = _gemini_safety_settings()

    accumulated_text = ""
    in_tok = 0
    out_tok = 0
    finish_reason: str | None = None

    try:
        stream = await client.aio.models.generate_content_stream(
            model=model,
            contents=contents,
            config=genai_types.GenerateContentConfig(**config_kwargs),
        )
        async for chunk in stream:
            chunk_text = ""
            if chunk.candidates:
                candidate = chunk.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text and not getattr(part, "thought", False):
                            chunk_text += part.text
                if candidate.finish_reason:
                    reason_str = str(candidate.finish_reason.name) if hasattr(candidate.finish_reason, "name") else str(candidate.finish_reason)
                    if "MAX_TOKENS" in reason_str:
                        finish_reason = "length"

            if chunk.usage_metadata:
                in_tok = getattr(chunk.usage_metadata, "prompt_token_count", 0) or 0
                out_tok = getattr(chunk.usage_metadata, "candidates_token_count", 0) or 0

            if chunk_text:
                accumulated_text += chunk_text
                yield chunk_text
                await asyncio.sleep(0)

    except Exception as e:
        logger.error("Gemini 真实流式调用失败: %s: %r", type(e).__name__, e, exc_info=True)
        if not accumulated_text:
            # 尚无任何输出：回退非流式（带空响应重试与更清晰的安全拦截报错），
            # 避免上游流式抖动/过滤直接导致整章失败 ROLLBACK。
            logger.warning("Gemini 真实流式无输出，回退非流式重试 (model=%s)", model)
            yield {"warning": "Gemini 流式生成失败，正在回退到非流式重试..."}
            async for item in _gemini_stream_with_usage(messages, model, temperature, max_tokens, thinking_level, client):
                yield item
            return
        # 已有部分输出则不重抛，正常结束

    if not accumulated_text:
        logger.warning("Gemini 真实流式返回空内容 (model=%s), 回退到非流式重试", model)
        yield {"warning": "Gemini 流式生成无输出，正在回退到非流式重试..."}
        async for item in _gemini_stream_with_usage(messages, model, temperature, max_tokens, thinking_level, client):
            yield item
        return

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
        "max_tokens": max_tokens,
    }
    if temperature >= 0:
        kwargs["temperature"] = temperature
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
        "max_tokens": max_tokens,
    }
    if temperature >= 0:
        kwargs["temperature"] = temperature
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
        "max_tokens": max_tokens,
    }
    if temperature >= 0:
        kwargs["temperature"] = temperature
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


# ─── OpenAI 格式实现（dispatch_* 的 openai 分支）──────────────────────────

def _log_cached_tokens(usage, model: str) -> None:
    """观测 provider 端 prompt 缓存命中情况（不输出该字段的供应商不打日志）。
    用于决定是否值得为吃缓存重排消息前缀。"""
    details = getattr(usage, "prompt_tokens_details", None) if usage else None
    cached = getattr(details, "cached_tokens", None) if details else None
    if cached is not None:
        logger.info(
            "prompt 缓存观测: model=%s cached_tokens=%s prompt_tokens=%s",
            model, cached, usage.prompt_tokens,
        )


def _first_choice(response, model: str):
    """部分中转站会返回 HTTP 200 但 choices 为空/None 的错误载荷，
    直接下标会抛难读的 NoneType 错误，这里把上游原始信息透出来。"""
    if response.choices:
        return response.choices[0]
    extra = getattr(response, "model_extra", None) or {}
    detail = extra.get("error") or extra or "响应中没有 choices 字段"
    raise RuntimeError(f"上游返回异常响应（model={model}）：{detail}")


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
        "max_tokens": max_tokens,
    }
    if temperature >= 0:
        kwargs["temperature"] = temperature
    # DeepSeek 非流式任务思考档位由全局设置控制（默认关闭）
    if _is_deepseek_model(model):
        _apply_deepseek_fast_thinking(kwargs)
    response = await client.chat.completions.create(**kwargs)
    return _first_choice(response, model).message.content or ""


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
        "max_tokens": max_tokens,
    }
    if temperature >= 0:
        kwargs["temperature"] = temperature
    if _is_deepseek_model(model):
        _apply_deepseek_fast_thinking(kwargs)
    response = await client.chat.completions.create(**kwargs)
    choice = _first_choice(response, model)
    content = choice.message.content or ""
    if choice.finish_reason and choice.finish_reason != "stop":
        logging.getLogger(__name__).warning(
            "OpenAI 非流式调用异常结束: finish_reason=%s, model=%s",
            choice.finish_reason, model,
        )
    usage = response.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0
    if not content:
        # 中转站常以 200 + 空正文表示内容过滤或上游故障；此处不抛错（摘要路径依赖空串走脱敏重试），只留诊断日志
        logging.getLogger(__name__).warning(
            "OpenAI 非流式空响应: model=%s, finish_reason=%s, input_tokens=%d",
            model, choice.finish_reason, in_tok,
        )
    _log_cached_tokens(usage, model)
    return content, in_tok, out_tok


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
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if temperature >= 0:
        kwargs["temperature"] = temperature
    if _is_deepseek_model(model):
        if thinking_level != "off":
            kwargs["extra_body"] = {
                "thinking": {"type": "enabled"},
                "reasoning_effort": _deepseek_reasoning_effort(thinking_level),
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
            _log_cached_tokens(chunk.usage, model)
    yield (finish_reason, in_tok, out_tok)
