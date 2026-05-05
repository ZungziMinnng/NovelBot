from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False, "timeout": 30},
)

@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()

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
        # 章节生成指令（构思备忘）
        "ALTER TABLE chapters ADD COLUMN instruction TEXT DEFAULT NULL",
        # 查询性能索引
        "CREATE INDEX IF NOT EXISTS idx_memories_novel_type_chapter ON memories(novel_id, memory_type, chapter_number)",
        "CREATE INDEX IF NOT EXISTS idx_memories_chapter_type ON memories(chapter_id, memory_type)",
        "CREATE INDEX IF NOT EXISTS idx_chapters_novel_vol_num ON chapters(novel_id, volume, number)",
        "CREATE INDEX IF NOT EXISTS idx_characters_novel ON characters(novel_id)",
        "CREATE INDEX IF NOT EXISTS idx_outlines_novel_level_vol_ch ON outlines(novel_id, level, volume, chapter_number)",
        # 上下文配置字段
        "ALTER TABLE novels ADD COLUMN rolling_summary_count INTEGER DEFAULT 5",
        "ALTER TABLE novels ADD COLUMN rag_top_k INTEGER DEFAULT 3",
        "ALTER TABLE novels ADD COLUMN chat_context_rounds INTEGER DEFAULT 20",
        "ALTER TABLE novels ADD COLUMN enable_thinking INTEGER DEFAULT 1",
        "ALTER TABLE novels ADD COLUMN thinking_level TEXT DEFAULT 'medium'",
        # 世界实体索引
        "CREATE INDEX IF NOT EXISTS idx_world_entities_novel ON world_entities(novel_id)",
        "CREATE INDEX IF NOT EXISTS idx_world_entities_novel_type ON world_entities(novel_id, type)",
        # 地点索引
        "CREATE INDEX IF NOT EXISTS idx_locations_novel ON locations(novel_id)",
        "CREATE INDEX IF NOT EXISTS idx_locations_novel_type ON locations(novel_id, type)",
        # 供应商关联
        "ALTER TABLE model_library ADD COLUMN provider_id INTEGER DEFAULT NULL",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass  # 列已存在则忽略


async def init_db():
    from app.models import novel, chapter, character, memory, model_library, writer_preset, world_entity, location, api_provider  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _run_migrations()
