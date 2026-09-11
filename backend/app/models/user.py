from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 每用户默认模型（ModelEntry.id 字符串），非 admin 生成时的回退链终点
    default_writer_model: Mapped[str] = mapped_column(String(100), default="")
    default_fast_model: Mapped[str] = mapped_column(String(100), default="")
    # 隐藏的小说 / 写手预设 id。存库而非 localStorage：同一份数据会从
    # localhost:5173 和 127.0.0.1:8000 两个源打开，localStorage 按源隔离会看不到彼此
    hidden_novel_ids: Mapped[list] = mapped_column(JSON, default=list)
    hidden_preset_ids: Mapped[list] = mapped_column(JSON, default=list)
    tavern_prompts: Mapped[dict] = mapped_column(JSON, default=dict)
    rpg_prompts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 存 sha256(token)，库泄露不等于 token 泄露
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
