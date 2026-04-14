from pydantic_settings import BaseSettings
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

    # 数据路径
    data_dir: str = "./data"
    database_url: str = "sqlite+aiosqlite:///./data/novelbot.db"
    chroma_path: str = "./data/chroma"

    # 应用
    app_title: str = "NovelBot"
    debug: bool = True
    max_critic_retries: int = 1  # 1 = Writer 最多执行两次（初次 + 1 次修改）

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def ensure_data_dir(self):
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.chroma_path).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_data_dir()
