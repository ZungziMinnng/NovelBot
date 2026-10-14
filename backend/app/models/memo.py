from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Memo(Base):
    """主页备忘录：脑子里冒出来的点子，随手记一笔。

    挂在用户身上、不挂书或模组——点子往往还没想好要放进哪本。
    scope 分开小说侧和游戏侧两块板子，互不显示。只给人看，不进任何提示词。
    和 AuthorNote（编辑器里挂章的便签）不是一回事：那个属于某本书。
    """
    __tablename__ = "memos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(10), nullable=False, default="novel")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
