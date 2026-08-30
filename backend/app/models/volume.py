from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Volume(Base):
    __tablename__ = "volumes"
    __table_args__ = (UniqueConstraint("novel_id", "number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")

    # 库存三问（见 services/outline_health.check_volume_reserves）：
    # 留到结尾才揭的牌、实力体系还剩几档、本卷已经用掉的大爆点。
    # 一行一条的自由文本，只用来数条数和给作者自查，不参与写作注入。
    endgame_cards: Mapped[str] = mapped_column(Text, default="")
    power_tiers: Mapped[str] = mapped_column(Text, default="")
    tier_count: Mapped[int] = mapped_column(Integer, default=0)
    words_per_tier: Mapped[int] = mapped_column(Integer, default=0)
    spent_payoffs: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novel: Mapped["Novel"] = relationship("Novel", back_populates="volumes")  # noqa: F821
