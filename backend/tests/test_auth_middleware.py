"""认证中间件测试：默认拒绝 + 全路由 401 扫描（防止漏改某个接口）。

不带 token 的请求在中间件层就被拦下，不会触到数据库或业务逻辑，
因此可以安全地对整个 app 扫描。
"""
import asyncio
import re
import unittest

import httpx
from fastapi.routing import APIRoute

from app.main import app
from app.api.auth_middleware import PUBLIC_EXACT, PUBLIC_PREFIXES


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _is_public(path: str) -> bool:
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


class AuthMiddlewareTests(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    def test_health_open(self):
        async def scenario():
            async with _client() as client:
                resp = await client.get("/api/health")
                self.assertEqual(resp.status_code, 200)

        self._run(scenario)

    def test_no_token_401(self):
        async def scenario():
            async with _client() as client:
                resp = await client.get("/api/novels/")
                self.assertEqual(resp.status_code, 401)
                self.assertIn("detail", resp.json())

        self._run(scenario)

    def test_options_passes_middleware(self):
        async def scenario():
            async with _client() as client:
                resp = await client.options("/api/novels/")
                self.assertNotEqual(resp.status_code, 401)

        self._run(scenario)

    def test_all_api_routes_require_auth(self):
        """遍历全部路由：/api/* 白名单之外的接口，未登录必须 401。
        漏掉归属校验的接口至少还有中间件兜底，这条测试保证兜底没有缺口。"""
        async def scenario():
            checked = 0
            async with _client() as client:
                for route in app.routes:
                    if not isinstance(route, APIRoute):
                        continue
                    path = route.path
                    if not path.startswith("/api") or _is_public(path):
                        continue
                    url = re.sub(r"\{[^}]+\}", "1", path)
                    method = next(m for m in route.methods if m not in ("HEAD", "OPTIONS"))
                    resp = await client.request(method, url)
                    self.assertEqual(
                        resp.status_code, 401,
                        f"{method} {path} 未登录返回了 {resp.status_code}，应为 401",
                    )
                    checked += 1
            # 保险丝：确保扫描真的覆盖了大量接口，而不是静默跳过
            self.assertGreater(checked, 100, f"只扫到 {checked} 个接口，路由枚举可能失效")

        self._run(scenario)

    def test_auth_routes_public(self):
        """登录/注册在白名单内：请求能到达业务层（返回参数校验错误而非 401）。"""
        async def scenario():
            async with _client() as client:
                resp = await client.post("/api/auth/login", json={})
                self.assertNotEqual(resp.status_code, 401)

        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
