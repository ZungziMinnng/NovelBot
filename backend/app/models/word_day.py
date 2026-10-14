from sqlalchemy import String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class WordDay(Base):
    """日更统计：每本书每天一行，记当天开始时和最后一次改动后的全书字数。

    当天净增 = total - base。生成、手改、删章、全书替换都算，所以是全书净增长而不是「敲了多少字」。
    """

    __tablename__ = "word_days"
    __table_args__ = (
        UniqueConstraint("novel_id", "day", name="uq_word_days_novel_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    # 本地日期 YYYY-MM-DD
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    base: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)

    novel: Mapped["Novel"] = relationship("Novel", back_populates="word_days")  # noqa: F821
