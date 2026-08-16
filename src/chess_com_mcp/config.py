"""Strict environment-based configuration."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, cast
from urllib.parse import urlsplit

from .errors import AppError

_AGENT_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$", re.ASCII)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$", re.ASCII)
_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


def _configuration_error(message: str) -> AppError:
    return AppError("invalid_configuration", message)


def _parse_int(raw: str, name: str, minimum: int, maximum: int) -> int:
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise _configuration_error(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise _configuration_error(f"{name} must be between {minimum} and {maximum}.")
    return value


def _parse_float(raw: str, name: str, minimum: float, maximum: float) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise _configuration_error(f"{name} must be numeric.") from exc
    if not minimum <= value <= maximum:
        raise _configuration_error(f"{name} must be between {minimum:g} and {maximum:g}.")
    return value


def _parse_bind_host(raw: str) -> str:
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError as exc:
        raise _configuration_error("CHESS_COM_MCP_BIND_HOST must be an IPv4 or IPv6 literal.") from exc


def _decode_token(token: str) -> bytes:
    if not _TOKEN_RE.fullmatch(token):
        raise _configuration_error("Authentication tokens must be unpadded base64url strings.")
    padded = token + "=" * (-len(token) % 4)
    try:
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise _configuration_error("Authentication tokens must be valid base64url strings.") from exc
    if len(decoded) < 32:
        raise _configuration_error("Authentication tokens must decode to at least 32 bytes.")
    return decoded


def _parse_tokens(raw: str | None) -> dict[str, str]:
    if raw is None or raw == "":
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _configuration_error("CHESS_COM_MCP_AUTH_TOKENS must be a JSON object.") from exc
    if type(parsed) is not dict or not parsed:
        raise _configuration_error("CHESS_COM_MCP_AUTH_TOKENS must be a nonempty JSON object.")
    tokens: dict[str, str] = {}
    for agent, token in parsed.items():
        if type(agent) is not str or not _AGENT_RE.fullmatch(agent):
            raise _configuration_error("Authentication agent names have an invalid format.")
        if type(token) is not str:
            raise _configuration_error("Authentication token values must be strings.")
        _decode_token(token)
        if token in tokens.values():
            raise _configuration_error("Authentication tokens must be unique per agent.")
        tokens[agent] = token
    return tokens


def _parse_hosts(raw: str | None) -> tuple[str, ...]:
    if raw is None or raw.strip() == "":
        return ()
    hosts: list[str] = []
    for item in raw.split(","):
        host = item.strip()
        if (
            not host
            or host == "*"
            or "://" in host
            or any(character.isspace() or ord(character) < 32 for character in host)
            or any(character in host for character in "/\\?#@")
        ):
            raise _configuration_error("CHESS_COM_MCP_ALLOWED_HOSTS contains an invalid exact Host value.")
        if host in hosts:
            raise _configuration_error("CHESS_COM_MCP_ALLOWED_HOSTS contains a duplicate value.")
        hosts.append(host)
    return tuple(hosts)


def _parse_origins(raw: str | None) -> tuple[str, ...]:
    if raw is None or raw.strip() == "":
        return ()
    origins: list[str] = []
    for item in raw.split(","):
        origin = item.strip()
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "*" in origin
        ):
            raise _configuration_error("CHESS_COM_MCP_ALLOWED_ORIGINS contains an invalid exact origin.")
        normalized = f"{parsed.scheme}://{parsed.netloc}"
        if normalized in origins:
            raise _configuration_error("CHESS_COM_MCP_ALLOWED_ORIGINS contains a duplicate value.")
        origins.append(normalized)
    return tuple(origins)


@dataclass(frozen=True, slots=True)
class Config:
    transport: str = "stdio"
    bind_host: str = "127.0.0.1"
    port: int = 8765
    timeout_seconds: float = 20.0
    max_response_bytes: int = 10_485_760
    log_level: LogLevel = "WARNING"
    auth_tokens: Mapping[str, str] = field(default_factory=dict)
    allowed_hosts: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()

    @property
    def is_loopback(self) -> bool:
        return ipaddress.ip_address(self.bind_host).is_loopback

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str],
        *,
        transport_override: str | None = None,
    ) -> Config:
        transport = transport_override or env.get("CHESS_COM_MCP_TRANSPORT", "stdio")
        if transport not in {"stdio", "http"}:
            raise _configuration_error("CHESS_COM_MCP_TRANSPORT must be 'stdio' or 'http'.")
        log_level = env.get("CHESS_COM_MCP_LOG_LEVEL", "WARNING").upper()
        if log_level not in _LOG_LEVELS:
            raise _configuration_error("CHESS_COM_MCP_LOG_LEVEL is not supported.")
        config = cls(
            transport=transport,
            bind_host=_parse_bind_host(env.get("CHESS_COM_MCP_BIND_HOST", "127.0.0.1")),
            port=_parse_int(env.get("CHESS_COM_MCP_PORT", "8765"), "CHESS_COM_MCP_PORT", 1024, 65535),
            timeout_seconds=_parse_float(
                env.get("CHESS_COM_MCP_TIMEOUT_SECONDS", "20"),
                "CHESS_COM_MCP_TIMEOUT_SECONDS",
                1,
                60,
            ),
            max_response_bytes=_parse_int(
                env.get("CHESS_COM_MCP_MAX_RESPONSE_BYTES", "10485760"),
                "CHESS_COM_MCP_MAX_RESPONSE_BYTES",
                65_536,
                10_485_760,
            ),
            log_level=cast(LogLevel, log_level),
            auth_tokens=_parse_tokens(env.get("CHESS_COM_MCP_AUTH_TOKENS")),
            allowed_hosts=_parse_hosts(env.get("CHESS_COM_MCP_ALLOWED_HOSTS")),
            allowed_origins=_parse_origins(env.get("CHESS_COM_MCP_ALLOWED_ORIGINS")),
        )
        if config.transport == "http":
            if not config.auth_tokens:
                raise _configuration_error("HTTP transport requires CHESS_COM_MCP_AUTH_TOKENS.")
            if not config.allowed_hosts:
                raise _configuration_error("HTTP transport requires CHESS_COM_MCP_ALLOWED_HOSTS.")
        return config
