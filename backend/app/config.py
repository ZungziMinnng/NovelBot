from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Self


class Settings(BaseSettings):
    # ── API 密钥（每种格式独立的中转站 Key）─────────────────────────────────
    # OpenAI 兼容格式（大多数中转站）
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    # Gemini 原生格式
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    # Anthropic 原生格式
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""

    # ── 模型配置（全局默认）─────────────────────────────────────────────────
    default_writer_model: str = "gpt-4o"
    default_fast_model: str = "gpt-4o-mini"
    writer_temperature: float = 0.85
    fast_temperature: float = 0.3

    # ── 各 Agent 独立模型配置（留空则回退到对应类别的全局默认）─────────────
    agent_writer_model: str = ""       # Writer Agent → 默认使用 default_writer_model
    agent_critic_model: str = ""       # Critic Agent → 默认使用 default_fast_model
    agent_memory_model: str = ""       # Memory/Summarizer → 默认使用 default_fast_model
    agent_outline_model: str = ""      # Outline Agent → 默认使用 default_fast_model
    agent_character_model: str = ""    # Character Agent → 默认使用 default_fast_model
    agent_orchestrator_model: str = "" # Orchestrator/World → 默认使用 default_fast_model

    # ── 网络代理（开启 VPN 时填写，例：http://127.0.0.1:7890）───────────────
    # 使用 NOVELBOT_ 前缀，避免与操作系统标准环境变量 HTTPS_PROXY/HTTP_PROXY 冲突
    https_proxy: str = Field(default="", validation_alias="NOVELBOT_HTTPS_PROXY")
    http_proxy: str = Field(default="", validation_alias="NOVELBOT_HTTP_PROXY")

    # ── 数据路径 ──────────────────────────────────────────────────────────────
    data_dir: str = "./data"
    database_url: str = "sqlite+aiosqlite:///./data/novelbot.db"
    chroma_path: str = "./data/chroma"

    # ── 应用 ──────────────────────────────────────────────────────────────────
    app_title: str = "NovelBot"
    debug: bool = True
    max_critic_retries: int = 1  # 1 = Writer 最多执行两次（初次 + 1 次修改）

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略 .env 中已废弃的旧字段（如 AIHUBMIX_*）
    )

    @model_validator(mode="after")
    def _migrate_aihubmix_keys(self) -> Self:
        """向后兼容：检测旧 AIHUBMIX_* 环境变量，自动迁移到新字段"""
        import os
        old_key = os.getenv("AIHUBMIX_API_KEY", "")
        old_url = os.getenv("AIHUBMIX_BASE_URL", "")
        if old_key:
            if not self.openai_api_key:
                object.__setattr__(self, "openai_api_key", old_key)
            if not self.gemini_api_key:
                object.__setattr__(self, "gemini_api_key", old_key)
            if not self.anthropic_api_key:
                object.__setattr__(self, "anthropic_api_key", old_key)
        if old_url:
            if not self.openai_base_url or self.openai_base_url == "https://api.openai.com/v1":
                object.__setattr__(self, "openai_base_url", old_url)
        old_gemini_url = os.getenv("GEMINI_BASE_URL", "")
        if not old_gemini_url and old_url and not self.gemini_base_url:
            # 旧的 aihubmix 模式下 gemini 走 /gemini 子路径
            pass  # 不强制覆盖已有的 gemini_base_url
        return self

    def ensure_data_dir(self):
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.chroma_path).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_data_dir()
