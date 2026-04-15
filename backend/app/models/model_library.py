from datetime import datetime
from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ModelEntry(Base):
    __tablename__ = "model_library"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    api_format: Mapped[str] = mapped_column(String(20), nullable=False, default="openai")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
