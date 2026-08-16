from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from chess_com_mcp.client import BASE_URL, USER_AGENT, ChessComClient
from chess_com_mcp.errors import AppError


@pytest.mark.asyncio
async def test_json_request_is_fixed_and_honest() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"Content-Type": "application/json; charset=utf-8"}, json={"ok": 1})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"User-Agent": USER_AGENT})
    client = ChessComClient(client=http)
    assert await client.get_json("/player/erik") == {"ok": 1}
    assert seen[0].method == "GET"
    assert str(seen[0].url) == f"{BASE_URL}/player/erik"
    assert seen[0].headers["accept"] == "application/json"
    assert seen[0].headers["user-agent"] == USER_AGENT
    await client.close()
    assert not http.is_closed
    await http.aclose()


@pytest.mark.asyncio
async def test_pgn_response() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"Content-Type": "application/x-chess-pgn"},
            content=b'[Event "x"]',
        )
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = ChessComClient(client=http)
        assert await client.get_pgn("/player/erik/games/2026/01/pgn") == '[Event "x"]'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [(404, "not_found"), (400, "upstream_rejected"), (418, "upstream_rejected"), (500, "upstream_unavailable")],
)
async def test_status_mapping(status: int, code: str) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, headers={"Content-Type": "application/json"})
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = ChessComClient(client=http, sleep=_no_sleep)
        with pytest.raises(AppError) as caught:
            await client.get_json("/player/erik")
        assert caught.value.code == code


async def _no_sleep(_: float) -> None:
    return None


@pytest.mark.asyncio
async def test_retries_rate_limit_then_succeeds() -> None:
    statuses = [429, 200]
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses.pop(0)
        if status == 429:
            return httpx.Response(status, headers={"Retry-After": "2"})
        return httpx.Response(status, headers={"Content-Type": "application/json"}, json={"done": True})

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ChessComClient(client=http, sleep=sleep)
        assert await client.get_json("/player/erik") == {"done": True}
    assert delays == [2.0]


@pytest.mark.asyncio
async def test_retry_after_is_bounded() -> None:
    statuses = [503, 503]
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(statuses.pop(0), headers={"Retry-After": "99"})

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(AppError, match="unavailable"):
            await ChessComClient(client=http, sleep=sleep).get_json("/player/erik")
    assert delays == [0.25]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"{}"), "invalid_upstream_response"),
        (httpx.Response(200, headers={"Content-Type": "application/json"}, content=b""), "invalid_upstream_response"),
        (httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"{"), "invalid_upstream_response"),
        (httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"[]"), "invalid_upstream_response"),
    ],
)
async def test_invalid_responses(response: httpx.Response, code: str) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as http:
        with pytest.raises(AppError) as caught:
            await ChessComClient(client=http).get_json("/player/erik")
        assert caught.value.code == code


@pytest.mark.asyncio
async def test_size_limit_exact_and_over() -> None:
    exact = json.dumps({"x": "a" * 10}).encode()

    def make_client(content: bytes, declared: str | None = None) -> tuple[ChessComClient, httpx.AsyncClient]:
        headers = {"Content-Type": "application/json"}
        if declared is not None:
            headers["Content-Length"] = declared
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, headers=headers, content=content))
        )
        return ChessComClient(client=http, max_response_bytes=len(exact)), http

    client, http = make_client(exact)
    assert await client.get_json("/player/erik") == {"x": "a" * 10}
    await http.aclose()
    client, http = make_client(exact + b" ")
    with pytest.raises(AppError, match="size limit"):
        await client.get_json("/player/erik")
    await http.aclose()
    client, http = make_client(exact, declared=str(len(exact) + 1))
    with pytest.raises(AppError, match="size limit"):
        await client.get_json("/player/erik")
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception_factory", "code"),
    [
        (lambda request: httpx.ReadTimeout("read", request=request), "upstream_timeout"),
        (lambda request: httpx.ConnectError("connect", request=request), "upstream_unavailable"),
    ],
)
async def test_network_errors(exception_factory: Callable[[httpx.Request], Exception], code: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> Any:
        nonlocal calls
        calls += 1
        raise exception_factory(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(AppError) as caught:
            await ChessComClient(client=http, sleep=_no_sleep).get_json("/player/erik")
        assert caught.value.code == code
    assert calls == (2 if code == "upstream_unavailable" else 1)


@pytest.mark.asyncio
async def test_unsafe_internal_path_is_rejected_without_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(RuntimeError):
            await ChessComClient(client=http).get_json("//evil.example")
    assert calls == 0
