from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PromptRule(Base):
    """规则广场条目：可复用的写作规则，按本书勾选后注入 Writer system prompt。

    与 WriterPreset 的区别：预设是前端快照拷贝进 novel 字段，改预设不影响已应用的书；
    规则是活链接，生成时后端实时解析，改内容立刻对所有启用它的书生效。
    """

    __tablename__ = "prompt_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 规则正文，原样拼进 prompt（name 只是界面标签，不进 prompt）
    content: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(30), default="style")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 内置规则可改可停用但不可删：可删的话幂等种子会在每次重启复活它
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    builtin_key: Mapped[str] = mapped_column(String(50), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
