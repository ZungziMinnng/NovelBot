from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ApiProvider(Base):
    __tablename__ = "api_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    api_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    api_format: Mapped[str] = mapped_column(String(20), nullable=False, default="openai")
    # 是否经全局代理访问：仅被墙的中转站（如 aihubmix）需要；可直连的（如 DeepSeek）关掉
    use_proxy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 仅 api_format=openai 时有意义：中转站另开的 Gemini 原生入口（如 https://xxx/gemini）。
    # 填了之后该供应商下名字带 gemini 的模型改走原生格式——OpenAI 兼容那条路带不上
    # safetySettings，Gemini 按默认严格档过滤。留空 = 维持 OpenAI 兼容
    gemini_base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
