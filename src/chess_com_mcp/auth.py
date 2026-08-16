"""Strict ASGI transport boundary for HTTP MCP requests."""

from __future__ import annotations

import hmac
from collections.abc import Mapping, Sequence

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

_HeaderList = list[tuple[bytes, bytes]]


def _header_values(headers: _HeaderList, name: bytes) -> list[str]:
    return [value.decode("latin-1") for key, value in headers if key.lower() == name]


class SecurityBoundaryMiddleware:
    """Apply exact Host/Origin checks and bearer auth before MCP dispatch."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        tokens: Mapping[str, str],
        allowed_hosts: Sequence[str],
        allowed_origins: Sequence[str],
    ) -> None:
        self._app = app
        self._tokens = tuple(tokens.items())
        self._allowed_hosts = frozenset(allowed_hosts)
        self._allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers: _HeaderList = scope.get("headers", [])
        hosts = _header_values(headers, b"host")
        if len(hosts) != 1 or hosts[0] not in self._allowed_hosts:
            await self._respond(Response("Invalid Host header", status_code=421), scope, receive, send)
            return
        origins = _header_values(headers, b"origin")
        if len(origins) > 1 or (origins and origins[0] not in self._allowed_origins):
            await self._respond(Response("Invalid Origin header", status_code=403), scope, receive, send)
            return
        if scope.get("path") == "/mcp":
            if scope.get("query_string"):
                await self._respond(Response("Query strings are not accepted", status_code=400), scope, receive, send)
                return
            authorizations = _header_values(headers, b"authorization")
            principal = self._authenticate(authorizations)
            if principal is None:
                response = JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await self._respond(response, scope, receive, send)
                return
            state = dict(scope.get("state", {}))
            state["authenticated_principal"] = principal
            scope["state"] = state
        await self._app(scope, receive, send)

    def _authenticate(self, headers: list[str]) -> str | None:
        if len(headers) != 1:
            return None
        pieces = headers[0].split(" ")
        if len(pieces) != 2 or pieces[0].lower() != "bearer" or not pieces[1]:
            return None
        presented = pieces[1]
        matched: str | None = None
        for agent, expected in self._tokens:
            if hmac.compare_digest(presented, expected):
                matched = agent
        return matched

    @staticmethod
    async def _respond(response: Response, scope: Scope, receive: Receive, send: Send) -> None:
        await response(scope, receive, send)
