from datetime import datetime
from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SensitiveWord(Base):
    """用户自定义的投稿敏感词。

    基线词库是随代码走的 JSON 文件（app/data/sensitive_words.json），这张表只存用户自己
    补充的词——各平台清单不同且常变，得让用户能随时粘进来。按用户存而非按书存，
    是因为同一个作者投同一个平台，清单是通用的。
    """

    __tablename__ = "sensitive_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    word: Mapped[str] = mapped_column(String(100), nullable=False)
    # 备注：为什么加这个词，方便日后回看
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
