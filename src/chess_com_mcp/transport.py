"""MCP transport assembly and secure HTTP startup."""

from __future__ import annotations

import logging

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from .auth import SecurityBoundaryMiddleware
from .config import Config
from .server import AppContext

logger = logging.getLogger(__name__)


def create_http_app(server: MCPServer[AppContext], config: Config) -> Starlette:
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(config.allowed_hosts),
        allowed_origins=list(config.allowed_origins),
    )
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=1_048_576,
        transport_security=security,
        host=config.bind_host,
    )
    app.add_middleware(
        SecurityBoundaryMiddleware,
        tokens=config.auth_tokens,
        allowed_hosts=config.allowed_hosts,
        allowed_origins=config.allowed_origins,
    )
    return app


def run_http(server: MCPServer[AppContext], config: Config) -> None:
    if not config.is_loopback:
        logger.warning(
            "MCP is binding to a non-loopback address without built-in TLS; use a trusted TLS reverse proxy."
        )
    uvicorn.run(
        create_http_app(server, config),
        host=config.bind_host,
        port=config.port,
        log_level=config.log_level.lower(),
        access_log=False,
        proxy_headers=False,
        server_header=False,
        date_header=False,
        timeout_keep_alive=5,
        h11_max_incomplete_event_size=16_384,
    )
