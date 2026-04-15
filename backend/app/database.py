from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def _run_migrations() -> None:
    """运行增量 DDL 迁移，对已有数据库新增列（SQLite ALTER TABLE）"""
    migrations = [
        "ALTER TABLE novels ADD COLUMN writer_system_prompt TEXT DEFAULT ''",
        "ALTER TABLE novels ADD COLUMN enable_critic INTEGER DEFAULT 1",
        "ALTER TABLE novels ADD COLUMN writer_temperature REAL DEFAULT 0.85",
        "ALTER TABLE novels ADD COLUMN writer_max_tokens INTEGER DEFAULT 4096",
        # 修复存量 NULL 值，防止 or "" 静默吃掉用户设置
        "UPDATE novels SET writer_system_prompt = '' WHERE writer_system_prompt IS NULL",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass  # 列已存在则忽略


async def init_db():
    from app.models import novel, chapter, character, memory, model_library  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _run_migrations()
