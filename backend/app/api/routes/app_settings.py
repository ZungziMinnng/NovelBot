from pathlib import Path
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


class TestRequest(BaseModel):
    model: str = ""


@router.post("/test")
async def test_connection(data: TestRequest = TestRequest(), db: AsyncSession = Depends(get_db)):
    """测试连接：支持指定模型，自动按 api_format 路由到对应 SDK"""
    from app.services import llm_client
    model = data.model or settings.default_fast_model
    try:
        entry = None
        if data.model:
            result = await db.execute(
                select(ModelEntry).where(ModelEntry.model_id == data.model).limit(1)
            )
            entry = result.scalar_one_or_none()

        if entry and entry.model_type == "embedding":
            if entry.api_format != "openai":
                raise ValueError("嵌入模型测试目前仅支持 OpenAI 兼容接口")
            if not entry.provider_id:
                raise ValueError("嵌入模型未绑定供应商")
            provider = await db.get(ApiProvider, entry.provider_id)
            if not provider or not provider.api_key or not provider.base_url:
                raise ValueError("嵌入模型供应商缺少 API Key 或 Base URL")

            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url)
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

        api_format = llm_client.get_model_api_format(model)
        response = await llm_client.dispatch_chat_complete(
            messages=[{"role": "user", "content": "回复数字1"}],
            model=model,
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
        api_format = entry.api_format if entry else llm_client.get_model_api_format(model)
        return {
            "ok": False,
            "error": str(e),
            "model": model,
            "api_format": api_format,
            "model_type": entry.model_type if entry else "chat",
        }
