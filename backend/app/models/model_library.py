from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ModelEntry(Base):
    __tablename__ = "model_library"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    api_format: Mapped[str] = mapped_column(String(20), nullable=False, default="openai")
    model_type: Mapped[str] = mapped_column(String(20), nullable=False, default="chat")
    provider_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_window: Mapped[int] = mapped_column(Integer, default=65536)
    input_price: Mapped[float] = mapped_column(Float, default=0.0)
    output_price: Mapped[float] = mapped_column(Float, default=0.0)
    price_currency: Mapped[str] = mapped_column(String(10), default="CNY")
    currency_to_cny_rate: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
