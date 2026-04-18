from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    # AiHubMix
    aihubmix_api_key: str = ""
    aihubmix_base_url: str = "https://aihubmix.com/v1"

    # 模型配置（全局默认）
    default_writer_model: str = "gpt-4o"
    default_fast_model: str = "gpt-4o-mini"
    writer_temperature: float = 0.85
    fast_temperature: float = 0.3

    # 各 Agent 独立模型配置（留空则回退到对应类别的全局默认）
    agent_writer_model: str = ""       # Writer Agent → 默认使用 default_writer_model
    agent_critic_model: str = ""       # Critic Agent → 默认使用 default_fast_model
    agent_memory_model: str = ""       # Memory/Summarizer → 默认使用 default_fast_model
    agent_outline_model: str = ""      # Outline Agent → 默认使用 default_fast_model
    agent_character_model: str = ""    # Character Agent → 默认使用 default_fast_model
    agent_orchestrator_model: str = "" # Orchestrator/World → 默认使用 default_fast_model

    # 原生 SDK 端点（留空则直连 Google/Anthropic 官方，填写 AiHubMix 端点则走代理）
    gemini_base_url: str = "https://aihubmix.com/gemini"
    anthropic_base_url: str = ""

    # 网络代理（开启 VPN 时填写，例：http://127.0.0.1:7890）
    # 使用 NOVELBOT_ 前缀，避免与操作系统标准环境变量 HTTPS_PROXY/HTTP_PROXY 冲突
    https_proxy: str = Field(default="", validation_alias="NOVELBOT_HTTPS_PROXY")
    http_proxy: str = Field(default="", validation_alias="NOVELBOT_HTTP_PROXY")

    # 数据路径
    data_dir: str = "./data"
    database_url: str = "sqlite+aiosqlite:///./data/novelbot.db"
    chroma_path: str = "./data/chroma"

    # 应用
    app_title: str = "NovelBot"
    debug: bool = True
    max_critic_retries: int = 1  # 1 = Writer 最多执行两次（初次 + 1 次修改）

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    def ensure_data_dir(self):
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.chroma_path).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_data_dir()
