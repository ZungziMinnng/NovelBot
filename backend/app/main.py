from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.api.routes import novels, chapters, characters, generation, app_settings, chat
from app.api.routes import model_library, admin, writer_presets


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Load model format cache on startup
    from app.services import llm_client
    async with AsyncSessionLocal() as session:
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


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_title}
