from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.logging_config import setup_logging

# 必须在导入其它 app 模块之前装好 handler：这些模块在导入期就会取 logger 并可能记日志
setup_logging(settings.log_level, settings.log_dir if settings.log_to_file else None)

from app.database import init_db, seed_admin, seed_builtin_rules, AsyncSessionLocal
from app.api.auth_middleware import AuthMiddleware
from app.api.routes import novels, chapters, characters, generation, app_settings, chat
from app.api.routes import model_library, admin, writer_presets, prompt_rules, world_entities, locations, api_providers, novel_notes, factions, techniques, volumes, outlines, prompts, corrections, worldview_changes, glossary, world_rules, story_threads, text_replace, tavern
from app.api.routes import auth, submission


async def _auto_migrate_providers(session, admin_id: int):
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
            p = ApiProvider(name=name, base_url=base_url, api_key=api_key, api_format=api_format, user_id=admin_id)
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
    admin_id = await seed_admin()
    await seed_builtin_rules()
    # Auto-migrate .env API configs to DB providers (first run only)
    async with AsyncSessionLocal() as session:
        await _auto_migrate_providers(session, admin_id)
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

# 认证中间件先添加、CORS 后添加：后添加者在最外层，401 响应才能带上 CORS 头
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,          prefix="/api/auth",        tags=["auth"])
app.include_router(novels.router,        prefix="/api/novels",      tags=["novels"])
app.include_router(chapters.router,      prefix="/api/chapters",    tags=["chapters"])
app.include_router(characters.router,    prefix="/api/characters",  tags=["characters"])
app.include_router(generation.router,    prefix="/api/generation",  tags=["generation"])
app.include_router(app_settings.router,  prefix="/api/settings",    tags=["settings"])
app.include_router(chat.router,          prefix="/api/chat",        tags=["chat"])
app.include_router(model_library.router, prefix="/api/models",      tags=["models"])
app.include_router(admin.router,         prefix="/api/admin",       tags=["admin"])
app.include_router(writer_presets.router, prefix="/api/writer-presets", tags=["writer-presets"])
app.include_router(prompt_rules.router,   prefix="/api/prompt-rules",   tags=["prompt-rules"])
app.include_router(world_entities.router, prefix="/api/world-entities", tags=["world-entities"])
app.include_router(locations.router,       prefix="/api/locations",      tags=["locations"])
app.include_router(api_providers.router,   prefix="/api/providers",      tags=["providers"])
app.include_router(novel_notes.router,     prefix="/api/notes",          tags=["notes"])
app.include_router(factions.router,        prefix="/api/factions",       tags=["factions"])
app.include_router(techniques.router,     prefix="/api/techniques",     tags=["techniques"])
app.include_router(volumes.router,        prefix="/api/volumes",        tags=["volumes"])
app.include_router(outlines.router,      prefix="/api/outlines",       tags=["outlines"])
app.include_router(prompts.router,       prefix="/api/prompts",        tags=["prompts"])
app.include_router(corrections.router,   prefix="/api/corrections",    tags=["corrections"])
app.include_router(worldview_changes.router, prefix="/api/worldview-changes", tags=["worldview-changes"])
app.include_router(glossary.router,        prefix="/api/glossary",       tags=["glossary"])
app.include_router(world_rules.router,     prefix="/api/world-rules",    tags=["world-rules"])
app.include_router(story_threads.router,   prefix="/api/story-threads",  tags=["story-threads"])
app.include_router(text_replace.router,    prefix="/api/text-replace",   tags=["text-replace"])
app.include_router(tavern.router,          prefix="/api/tavern",         tags=["tavern"])
app.include_router(submission.router,      prefix="/api/submission",     tags=["submission"])


_avatars_dir = Path("data/avatars")
_avatars_dir.mkdir(parents=True, exist_ok=True)
app.mount("/api/avatars", StaticFiles(directory=str(_avatars_dir)), name="avatars")


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_title}


# ── 前端静态托管（分发包用）───────────────────────────────────────────────────
# 存在 web/ 目录时由后端直接托管前端产物，整个程序只开一个端口，用户机器不需要 Node。
# 开发时没有 web/，前端照旧跑 vite dev server 并代理 /api 到这里，这段自动跳过。
# 注册必须在所有 /api 路由之后：catch-all 会吃掉任何未匹配路径。
_web_dir = Path(__file__).resolve().parents[1] / "web"
if (_web_dir / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=str(_web_dir / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """SPA 回退。前端用 BrowserRouter，刷新 /novel/3 这类深链接时服务端并没有
        对应路由，必须回 index.html 交给前端路由，否则用户一刷新就是 404。"""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (_web_dir / full_path).resolve()
        # 限定在 web/ 内，防止 ../ 穿越读到源码或数据库
        if full_path and candidate.is_file() and candidate.is_relative_to(_web_dir):
            return FileResponse(candidate)
        return FileResponse(_web_dir / "index.html")
