from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.api.routes import novels, chapters, characters, generation, app_settings, chat
from app.api.routes import model_library, admin, writer_presets, world_entities, locations, api_providers


async def _auto_migrate_providers(session):
    """首次启动时将 .env 中已有的 API 配置自动创建为 DB 供应商记录。"""
    from sqlalchemy import select, func
    from app.models.api_provider import ApiProvider
    from app.models.model_library import ModelEntry

    count = await session.execute(select(func.count(ApiProvider.id)))
    if count.scalar() > 0:
        return  # 已有供应商，跳过迁移

    migrations = [
        (settings.openai_api_key, settings.openai_base_url, "openai", "OpenAI"),
        (settings.gemini_api_key, settings.gemini_base_url, "gemini", "Google Gemini"),
        (settings.anthropic_api_key, settings.anthropic_base_url, "anthropic", "Anthropic"),
    ]
    provider_by_format: dict[str, int] = {}
    for api_key, base_url, api_format, name in migrations:
        if api_key:
            p = ApiProvider(name=name, base_url=base_url, api_key=api_key, api_format=api_format)
            session.add(p)
            await session.flush()
            provider_by_format[api_format] = p.id

    if provider_by_format:
        result = await session.execute(select(ModelEntry))
        for m in result.scalars():
            pid = provider_by_format.get(m.api_format)
            if pid:
                m.provider_id = pid
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Auto-migrate .env API configs to DB providers (first run only)
    async with AsyncSessionLocal() as session:
        await _auto_migrate_providers(session)
    # Load provider + model format caches on startup
    from app.services import llm_client
    async with AsyncSessionLocal() as session:
        await llm_client.refresh_provider_cache(session)
        await llm_client.refresh_model_formats(session)
    yield


app = FastAPI(
    title=settings.app_title,
    description="AI 驱动的小说创作平台",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(novels.router,        prefix="/api/novels",      tags=["novels"])
app.include_router(chapters.router,      prefix="/api/chapters",    tags=["chapters"])
app.include_router(characters.router,    prefix="/api/characters",  tags=["characters"])
app.include_router(generation.router,    prefix="/api/generation",  tags=["generation"])
app.include_router(app_settings.router,  prefix="/api/settings",    tags=["settings"])
app.include_router(chat.router,          prefix="/api/chat",        tags=["chat"])
app.include_router(model_library.router, prefix="/api/models",      tags=["models"])
app.include_router(admin.router,         prefix="/api/admin",       tags=["admin"])
app.include_router(writer_presets.router, prefix="/api/writer-presets", tags=["writer-presets"])
app.include_router(world_entities.router, prefix="/api/world-entities", tags=["world-entities"])
app.include_router(locations.router,       prefix="/api/locations",      tags=["locations"])
app.include_router(api_providers.router,   prefix="/api/providers",      tags=["providers"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_title}
