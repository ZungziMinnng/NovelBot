import asyncio
from pathlib import Path
from urllib.parse import urlparse
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.config import settings
from app.database import get_db
from app.models.api_provider import ApiProvider
from app.models.model_library import ModelEntry

router = APIRouter()

_ENV_PATH = Path(__file__).parent.parent.parent.parent / ".env"


def _write_env(key: str, value: str) -> None:
    """更新 .env 文件中指定 key 的值，不存在则追加"""
    env_key = key.upper()
    lines = _ENV_PATH.read_text(encoding="utf-8").splitlines() if _ENV_PATH.exists() else []
    new_lines = []
    found = False
    for line in lines:
        if line.startswith(f"{env_key}=") or line.startswith(f"{env_key} ="):
            new_lines.append(f"{env_key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{env_key}={value}")
    _ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


class SettingsUpdate(BaseModel):
    default_writer_model: str = ""
    default_fast_model: str = ""
    agent_writer_model: str = ""
    agent_critic_model: str = ""
    agent_memory_model: str = ""
    agent_outline_model: str = ""
    agent_character_model: str = ""
    agent_orchestrator_model: str = ""
    agent_review_model: str = ""
    enable_review: bool = False
    review_interval: int = 10
    https_proxy: str = ""
    http_proxy: str = ""


class SettingsOut(BaseModel):
    default_writer_model: str
    default_fast_model: str
    max_critic_retries: int
    agent_writer_model: str
    agent_critic_model: str
    agent_memory_model: str
    agent_outline_model: str
    agent_character_model: str
    agent_orchestrator_model: str
    agent_review_model: str
    enable_review: bool
    review_interval: int
    https_proxy: str
    http_proxy: str


@router.get("/", response_model=SettingsOut)
async def get_settings():
    return SettingsOut(
        default_writer_model=settings.default_writer_model,
        default_fast_model=settings.default_fast_model,
        max_critic_retries=settings.max_critic_retries,
        agent_writer_model=settings.agent_writer_model,
        agent_critic_model=settings.agent_critic_model,
        agent_memory_model=settings.agent_memory_model,
        agent_outline_model=settings.agent_outline_model,
        agent_character_model=settings.agent_character_model,
        agent_orchestrator_model=settings.agent_orchestrator_model,
        agent_review_model=settings.agent_review_model,
        enable_review=settings.enable_review,
        review_interval=settings.review_interval,
        https_proxy=settings.https_proxy,
        http_proxy=settings.http_proxy,
    )


@router.patch("/")
async def update_settings(data: SettingsUpdate):
    """更新配置，同步写入 .env 文件并更新内存"""
    # 模型配置
    if data.default_writer_model:
        settings.default_writer_model = data.default_writer_model
        _write_env("DEFAULT_WRITER_MODEL", data.default_writer_model)
    if data.default_fast_model:
        settings.default_fast_model = data.default_fast_model
        _write_env("DEFAULT_FAST_MODEL", data.default_fast_model)
    # Agent-level models (allow saving empty string to clear)
    settings.agent_writer_model = data.agent_writer_model
    _write_env("AGENT_WRITER_MODEL", data.agent_writer_model)
    settings.agent_critic_model = data.agent_critic_model
    _write_env("AGENT_CRITIC_MODEL", data.agent_critic_model)
    settings.agent_memory_model = data.agent_memory_model
    _write_env("AGENT_MEMORY_MODEL", data.agent_memory_model)
    settings.agent_outline_model = data.agent_outline_model
    _write_env("AGENT_OUTLINE_MODEL", data.agent_outline_model)
    settings.agent_character_model = data.agent_character_model
    _write_env("AGENT_CHARACTER_MODEL", data.agent_character_model)
    settings.agent_orchestrator_model = data.agent_orchestrator_model
    _write_env("AGENT_ORCHESTRATOR_MODEL", data.agent_orchestrator_model)
    settings.agent_review_model = data.agent_review_model
    _write_env("AGENT_REVIEW_MODEL", data.agent_review_model)
    settings.enable_review = data.enable_review
    _write_env("ENABLE_REVIEW", str(data.enable_review).lower())
    settings.review_interval = data.review_interval
    _write_env("REVIEW_INTERVAL", str(data.review_interval))
    # 代理设置（允许保存空字符串以清除代理）
    settings.https_proxy = data.https_proxy
    _write_env("NOVELBOT_HTTPS_PROXY", data.https_proxy)
    settings.http_proxy = data.http_proxy
    _write_env("NOVELBOT_HTTP_PROXY", data.http_proxy)
    return {"ok": True}


class ProxyStatusOut(BaseModel):
    enabled: bool          # 是否配置了代理（https/http 任一非空）
    proxy: str             # 当前代理地址（本地 127.0.0.1，与设置页输入框同值，无密钥）
    host: str = ""
    port: int = 0
    reachable: bool | None = None  # 实时 TCP 探测结果；未配置或解析失败为 None
    detail: str = ""       # 不可达时的原因


async def _probe_tcp(host: str, port: int, timeout: float = 2.0) -> tuple[bool, str]:
    """对 host:port 做一次 TCP 连接探测，判断代理端口是否在监听。"""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True, ""
    except Exception as e:
        return False, str(e) or e.__class__.__name__


@router.get("/proxy-status", response_model=ProxyStatusOut)
async def proxy_status():
    """探测当前代理端口是否可连通，用于设置页展示「socket 是否真的在线」。"""
    proxy = settings.https_proxy or settings.http_proxy
    if not proxy:
        return ProxyStatusOut(enabled=False, proxy="")
    parsed = urlparse(proxy)
    host = parsed.hostname or ""
    port = parsed.port or 0
    if not host or not port:
        return ProxyStatusOut(
            enabled=True, proxy=proxy, host=host, port=port,
            reachable=None, detail="无法解析代理地址的主机/端口",
        )
    reachable, detail = await _probe_tcp(host, port)
    return ProxyStatusOut(
        enabled=True, proxy=proxy, host=host, port=port,
        reachable=reachable, detail=detail,
    )


class TestRequest(BaseModel):
    model: str = ""


@router.post("/test")
async def test_connection(data: TestRequest = TestRequest(), db: AsyncSession = Depends(get_db)):
    """测试连接：支持指定模型，自动按 api_format 路由到对应 SDK"""
    from app.services import llm_client
    ref = data.model or settings.default_fast_model
    try:
        # data.model 可能是 ModelEntry.id（新方案）或旧 model_id 字符串
        entry = None
        if data.model:
            if data.model.isdigit():
                entry = await db.get(ModelEntry, int(data.model))
            if entry is None:
                result = await db.execute(
                    select(ModelEntry).where(ModelEntry.model_id == data.model).limit(1)
                )
                entry = result.scalar_one_or_none()
        # 实际调用 SDK / 展示用真实模型名；dispatch 仍收 ref 以按供应商消歧
        model = entry.model_id if entry else llm_client.resolve_model_ref(ref)[0]

        if entry and entry.model_type == "embedding":
            if entry.api_format != "openai":
                raise ValueError("嵌入模型测试目前仅支持 OpenAI 兼容接口")
            if not entry.provider_id:
                raise ValueError("嵌入模型未绑定供应商")
            provider = await db.get(ApiProvider, entry.provider_id)
            if not provider or not provider.api_key or not provider.base_url:
                raise ValueError("嵌入模型供应商缺少 API Key 或 Base URL")

            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=provider.api_key,
                base_url=provider.base_url,
                http_client=llm_client._build_httpx_client(provider.use_proxy),
            )
            response = await client.embeddings.create(
                input="测试文本",
                model=model,
            )
            dimensions = len(response.data[0].embedding)
            return {
                "ok": True,
                "response": f"嵌入测试成功，向量维度 {dimensions}",
                "model": model,
                "api_format": entry.api_format,
                "model_type": "embedding",
            }

        api_format = entry.api_format if entry else llm_client.resolve_model_ref(ref)[1]
        # 传 ref（非真实名）给 dispatch，以便按供应商精确路由
        response = await llm_client.dispatch_chat_complete(
            messages=[{"role": "user", "content": "回复数字1"}],
            model=ref,
            api_format=api_format,
            max_tokens=100,
        )
        return {
            "ok": True,
            "response": response,
            "model": model,
            "api_format": api_format,
            "model_type": entry.model_type if entry else "chat",
        }
    except Exception as e:
        api_format = entry.api_format if entry else llm_client.resolve_model_ref(ref)[1]
        return {
            "ok": False,
            "error": str(e),
            "model": model,
            "api_format": api_format,
            "model_type": entry.model_type if entry else "chat",
        }
