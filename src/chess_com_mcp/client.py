"""Bounded client for the fixed Chess.com Published Data API origin."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .errors import AppError

BASE_URL = "https://api.chess.com/pub"
USER_AGENT = "chess-com-mcp/0.1.0"
_RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})


class ChessComClient:
    """An async, fixed-destination Chess.com client."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        max_response_bytes: int = 10_485_760,
        concurrency: int = 4,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._max_response_bytes = max_response_bytes
        self._semaphore = asyncio.Semaphore(concurrency)
        self._sleep = sleep
        self._owns_client = client is None
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=timeout_seconds,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=timeout_seconds,
        )
        self._client = client or httpx.AsyncClient(
            verify=True,
            follow_redirects=False,
            trust_env=False,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_json(self, path: str) -> dict[str, Any]:
        body = await self._request(path, accept="application/json", expected="json")
        try:
            parsed = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AppError("invalid_upstream_response", "Chess.com returned malformed JSON.") from exc
        if type(parsed) is not dict:
            raise AppError("invalid_upstream_response", "Chess.com returned an unexpected JSON value.")
        return parsed

    async def get_pgn(self, path: str) -> str:
        body = await self._request(path, accept="application/x-chess-pgn", expected="pgn")
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AppError("invalid_upstream_response", "Chess.com returned invalid PGN text.") from exc

    async def _request(self, path: str, *, accept: str, expected: str) -> bytes:
        if not path.startswith("/") or "//" in path or ".." in path or any(character in path for character in "?#"):
            raise RuntimeError("Unsafe internal Chess.com endpoint")
        url = f"{BASE_URL}{path}"
        for attempt in range(2):
            try:
                async with self._semaphore:
                    async with self._client.stream("GET", url, headers={"Accept": accept}) as response:
                        if response.status_code in _RETRYABLE_STATUSES and attempt == 0:
                            delay = self._retry_delay(response.headers.get("Retry-After"))
                        else:
                            delay = None
                        if delay is None:
                            self._raise_for_status(response.status_code)
                            self._validate_content_type(response.headers.get("Content-Type"), expected)
                            content_length = response.headers.get("Content-Length")
                            if content_length is not None:
                                try:
                                    if int(content_length, 10) > self._max_response_bytes:
                                        raise AppError(
                                            "response_too_large",
                                            "Chess.com response exceeded the configured size limit.",
                                        )
                                except ValueError:
                                    pass
                            return await self._read_limited(response)
                await self._sleep(delay)
            except httpx.ConnectTimeout as exc:
                if attempt == 0:
                    await self._sleep(0.25)
                    continue
                raise AppError("upstream_timeout", "Timed out connecting to Chess.com.") from exc
            except httpx.TimeoutException as exc:
                raise AppError("upstream_timeout", "Timed out while contacting Chess.com.") from exc
            except httpx.NetworkError as exc:
                if attempt == 0:
                    await self._sleep(0.25)
                    continue
                raise AppError("upstream_unavailable", "Chess.com is currently unavailable.") from exc
            except httpx.DecodingError as exc:
                raise AppError("invalid_upstream_response", "Chess.com returned invalid encoded data.") from exc
        raise AppError("upstream_unavailable", "Chess.com is currently unavailable.")  # pragma: no cover

    async def _read_limited(self, response: httpx.Response) -> bytes:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > self._max_response_bytes:
                raise AppError("response_too_large", "Chess.com response exceeded the configured size limit.")
            body.extend(chunk)
        if not body:
            raise AppError("invalid_upstream_response", "Chess.com returned an empty response.")
        return bytes(body)

    @staticmethod
    def _retry_delay(retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                delay = float(retry_after)
                if 0 <= delay <= 5:
                    return delay
            except ValueError:
                pass
        return 0.25

    @staticmethod
    def _validate_content_type(raw: str | None, expected: str) -> None:
        if raw is None:
            raise AppError("invalid_upstream_response", "Chess.com response had no content type.")
        media_type = raw.split(";", 1)[0].strip().lower()
        if expected == "json":
            valid = media_type == "application/json" or media_type.endswith("+json")
        else:
            valid = media_type == "application/x-chess-pgn"
        if not valid:
            raise AppError("invalid_upstream_response", "Chess.com returned an unexpected content type.")

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if 200 <= status < 300:
            return
        if status == 404:
            raise AppError("not_found", "The requested Chess.com resource was not found.")
        if status == 429:
            raise AppError("rate_limited", "Chess.com rate limited the request.")
        if 400 <= status < 500:
            raise AppError("upstream_rejected", "Chess.com rejected the request.")
        if 500 <= status < 600:
            raise AppError("upstream_unavailable", "Chess.com is currently unavailable.")
        raise AppError("invalid_upstream_response", "Chess.com returned an unexpected HTTP status.")
