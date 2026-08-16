from __future__ import annotations

from typing import Any

import httpx
import pytest
from starlette.responses import JSONResponse

from chess_com_mcp.auth import SecurityBoundaryMiddleware
from chess_com_mcp.config import Config
from chess_com_mcp.server import create_server
from chess_com_mcp.transport import create_http_app, run_http

pytestmark = pytest.mark.integration


def dummy_app() -> Any:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await JSONResponse({"accepted": scope.get("state", {}).get("authenticated_principal")})(scope, receive, send)

    return app


@pytest.mark.asyncio
async def test_security_boundary(token: str) -> None:
    app = SecurityBoundaryMiddleware(
        dummy_app(), tokens={"codex-one": token}, allowed_hosts=["chess.home.arpa"], allowed_origins=[]
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chess.home.arpa") as client:
        assert (await client.get("/healthz")).status_code == 200
        missing = await client.post("/mcp", json={})
        wrong = await client.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"})
        valid = await client.post("/mcp", json={}, headers={"Authorization": f"Bearer {token}"})
        query = await client.post("/mcp?token=nope", json={}, headers={"Authorization": f"Bearer {token}"})
    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json() == {"error": "unauthorized"}
    assert valid.json() == {"accepted": "codex-one"}
    assert query.status_code == 400


@pytest.mark.asyncio
async def test_host_origin_and_duplicate_headers(token: str) -> None:
    app = SecurityBoundaryMiddleware(
        dummy_app(),
        tokens={"codex-one": token},
        allowed_hosts=["chess.home.arpa"],
        allowed_origins=["https://agent.home.arpa"],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://chess.home.arpa") as client:
        assert (await client.get("/healthz", headers={"Host": "evil.example"})).status_code == 421
        assert (await client.get("/healthz", headers={"Origin": "https://evil.example"})).status_code == 403
        assert (await client.get("/healthz", headers={"Origin": "https://agent.home.arpa"})).status_code == 200
        duplicate_origin = await client.get(
            "/healthz", headers=[("Origin", "https://agent.home.arpa"), ("Origin", "https://agent.home.arpa")]
        )
        duplicate_auth = await client.post(
            "/mcp",
            json={},
            headers=[("Authorization", f"Bearer {token}"), ("Authorization", f"Bearer {token}")],
        )
    assert duplicate_origin.status_code == 403
    assert duplicate_auth.status_code == 401


@pytest.mark.asyncio
async def test_http_app_routes_and_health(token: str) -> None:
    config = Config(
        transport="http",
        auth_tokens={"codex": token},
        allowed_hosts=("chess.home.arpa",),
    )
    app = create_http_app(create_server(config), config)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://chess.home.arpa",
        ) as client:
            health = await client.get("/healthz")
            unknown = await client.get("/docs")
            unauthenticated = await client.post("/mcp", json={})
            oversized = await client.post(
                "/mcp",
                content=b"x" * (1_048_576 + 1),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
    assert health.json() == {"status": "ok"}
    assert unknown.status_code == 404
    assert unauthenticated.status_code == 401
    assert oversized.status_code == 413


def test_run_http_uses_hardened_uvicorn(monkeypatch: pytest.MonkeyPatch, token: str) -> None:
    captured: dict[str, Any] = {}

    def fake_run(app: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("chess_com_mcp.transport.uvicorn.run", fake_run)
    config = Config(
        transport="http",
        bind_host="0.0.0.0",
        auth_tokens={"codex": token},
        allowed_hosts=("chess.home.arpa",),
    )
    run_http(create_server(config), config)
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8765
    assert captured["access_log"] is False
    assert captured["proxy_headers"] is False
