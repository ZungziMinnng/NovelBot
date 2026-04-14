from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.api.routes import novels, chapters, characters, generation, app_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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

app.include_router(novels.router, prefix="/api/novels", tags=["novels"])
app.include_router(chapters.router, prefix="/api/chapters", tags=["chapters"])
app.include_router(characters.router, prefix="/api/characters", tags=["characters"])
app.include_router(generation.router, prefix="/api/generation", tags=["generation"])
app.include_router(app_settings.router, prefix="/api/settings", tags=["settings"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_title}
