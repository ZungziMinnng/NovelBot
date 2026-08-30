"""默认拒绝的认证中间件。

必须保持纯 ASGI 实现（不要改成 BaseHTTPMiddleware）：StreamingResponse 的
生成器要在同一协程上下文里迭代，current_user_var 才能在流式生成期间可见。
"""
import json

from app.database import AsyncSessionLocal
from app.services import auth as auth_service
from app.services.auth import current_user_var

# 只有注册/登录能免认证。整个 /api/auth/ 都放行会让中间件跳过 current_user_var，
# 于是 /auth/me 这类依赖 CurrentUser 的端点无论带什么 token 都拿不到用户，恒定 401。
PUBLIC_EXACT = {"/api/health", "/api/auth/register", "/api/auth/login"}
PUBLIC_PREFIXES = ("/api/avatars/",)


def _bearer_token(headers: list[tuple[bytes, bytes]]) -> str:
    for key, value in headers:
        if key == b"authorization":
            text = value.decode("latin-1")
            if text.lower().startswith("bearer "):
                return text[7:].strip()
    return ""


async def _send_401(send) -> None:
    body = json.dumps({"detail": "未登录或登录已过期"}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if (
            not path.startswith("/api")
            or scope["method"] == "OPTIONS"
            or path in PUBLIC_EXACT
            or path.startswith(PUBLIC_PREFIXES)
        ):
            return await self.app(scope, receive, send)

        token = _bearer_token(scope.get("headers", []))
        user = None
        if token:
            async with AsyncSessionLocal() as db:
                user = await auth_service.resolve_token(db, token)
        if user is None:
            return await _send_401(send)

        ctx_token = current_user_var.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_var.reset(ctx_token)
