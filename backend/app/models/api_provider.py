from datetime import datetime
from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ApiProvider(Base):
    __tablename__ = "api_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    api_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    api_format: Mapped[str] = mapped_column(String(20), nullable=False, default="openai")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
