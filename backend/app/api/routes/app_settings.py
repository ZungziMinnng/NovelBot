from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel
from app.config import settings

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


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-8:]


class SettingsUpdate(BaseModel):
    aihubmix_api_key: str = ""
    aihubmix_base_url: str = ""
    default_writer_model: str = ""
    default_fast_model: str = ""
    agent_writer_model: str = ""
    agent_critic_model: str = ""
    agent_memory_model: str = ""
    agent_outline_model: str = ""
    agent_character_model: str = ""
    agent_orchestrator_model: str = ""


class SettingsOut(BaseModel):
    aihubmix_api_key_set: bool
    aihubmix_api_key_masked: str
    aihubmix_base_url: str
    default_writer_model: str
    default_fast_model: str
    max_critic_retries: int
    agent_writer_model: str
    agent_critic_model: str
    agent_memory_model: str
    agent_outline_model: str
    agent_character_model: str
    agent_orchestrator_model: str


@router.get("/", response_model=SettingsOut)
async def get_settings():
    return SettingsOut(
        aihubmix_api_key_set=bool(settings.aihubmix_api_key),
        aihubmix_api_key_masked=_mask_key(settings.aihubmix_api_key) if settings.aihubmix_api_key else "",
        aihubmix_base_url=settings.aihubmix_base_url,
        default_writer_model=settings.default_writer_model,
        default_fast_model=settings.default_fast_model,
        max_critic_retries=settings.max_critic_retries,
        agent_writer_model=settings.agent_writer_model,
        agent_critic_model=settings.agent_critic_model,
        agent_memory_model=settings.agent_memory_model,
        agent_outline_model=settings.agent_outline_model,
        agent_character_model=settings.agent_character_model,
        agent_orchestrator_model=settings.agent_orchestrator_model,
    )


@router.patch("/")
async def update_settings(data: SettingsUpdate):
    """更新配置，同步写入 .env 文件并更新内存"""
    if data.aihubmix_api_key:
        settings.aihubmix_api_key = data.aihubmix_api_key
        _write_env("AIHUBMIX_API_KEY", data.aihubmix_api_key)
    if data.aihubmix_base_url:
        settings.aihubmix_base_url = data.aihubmix_base_url
        _write_env("AIHUBMIX_BASE_URL", data.aihubmix_base_url)
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
    return {"ok": True}


@router.post("/test")
async def test_connection():
    """测试 AiHubMix 连接"""
    from openai import AsyncOpenAI
    try:
        client = AsyncOpenAI(
            api_key=settings.aihubmix_api_key,
            base_url=settings.aihubmix_base_url,
        )
        resp = await client.chat.completions.create(
            model=settings.default_fast_model,
            messages=[{"role": "user", "content": "回复数字1"}],
            max_tokens=5,
        )
        return {"ok": True, "response": resp.choices[0].message.content}
    except Exception as e:
        return {"ok": False, "error": str(e)}
