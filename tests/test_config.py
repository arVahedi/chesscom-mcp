from __future__ import annotations

import json

import pytest

from chess_com_mcp.config import Config
from chess_com_mcp.errors import AppError


def http_env(token: str) -> dict[str, str]:
    return {
        "CHESS_COM_MCP_TRANSPORT": "http",
        "CHESS_COM_MCP_AUTH_TOKENS": json.dumps({"codex-one": token}),
        "CHESS_COM_MCP_ALLOWED_HOSTS": "chess.home.arpa, chess.home.arpa:443",
    }


def test_defaults_are_safe() -> None:
    config = Config.from_env({})
    assert config.transport == "stdio"
    assert config.bind_host == "127.0.0.1"
    assert config.port == 8765
    assert config.is_loopback
    assert config.timeout_seconds == 20
    assert config.max_response_bytes == 10_485_760


def test_http_configuration_and_override(token: str) -> None:
    env = http_env(token)
    env.update(
        {
            "CHESS_COM_MCP_BIND_HOST": "::",
            "CHESS_COM_MCP_PORT": "9443",
            "CHESS_COM_MCP_TIMEOUT_SECONDS": "2.5",
            "CHESS_COM_MCP_MAX_RESPONSE_BYTES": "65536",
            "CHESS_COM_MCP_LOG_LEVEL": "info",
            "CHESS_COM_MCP_ALLOWED_ORIGINS": "https://agent.home.arpa/",
        }
    )
    config = Config.from_env(env, transport_override="http")
    assert config.bind_host == "::"
    assert not config.is_loopback
    assert config.port == 9443
    assert config.log_level == "INFO"
    assert config.allowed_origins == ("https://agent.home.arpa",)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "::1", "192.168.1.20"])
def test_ip_literal_bind_hosts(token: str, host: str) -> None:
    env = http_env(token)
    env["CHESS_COM_MCP_BIND_HOST"] = host
    assert Config.from_env(env).bind_host == host


@pytest.mark.parametrize("host", ["localhost", "http://127.0.0.1", "eth0", "999.1.1.1", ""])
def test_invalid_bind_hosts(host: str) -> None:
    with pytest.raises(AppError, match="IPv4 or IPv6"):
        Config.from_env({"CHESS_COM_MCP_BIND_HOST": host})


def test_http_requires_tokens_and_hosts(token: str) -> None:
    with pytest.raises(AppError, match="AUTH_TOKENS"):
        Config.from_env({"CHESS_COM_MCP_TRANSPORT": "http", "CHESS_COM_MCP_ALLOWED_HOSTS": "localhost:8765"})
    with pytest.raises(AppError, match="ALLOWED_HOSTS"):
        Config.from_env({"CHESS_COM_MCP_TRANSPORT": "http", "CHESS_COM_MCP_AUTH_TOKENS": json.dumps({"agent": token})})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CHESS_COM_MCP_PORT", "80"),
        ("CHESS_COM_MCP_PORT", "abc"),
        ("CHESS_COM_MCP_TIMEOUT_SECONDS", "0"),
        ("CHESS_COM_MCP_TIMEOUT_SECONDS", "nan"),
        ("CHESS_COM_MCP_MAX_RESPONSE_BYTES", "65535"),
        ("CHESS_COM_MCP_LOG_LEVEL", "TRACE"),
        ("CHESS_COM_MCP_TRANSPORT", "sse"),
    ],
)
def test_invalid_scalar_configuration(name: str, value: str) -> None:
    with pytest.raises(AppError):
        Config.from_env({name: value})


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "{}",
        json.dumps({"bad agent": "x"}),
        json.dumps({"agent": 42}),
        json.dumps({"agent": "short"}),
    ],
)
def test_invalid_token_maps(raw: str) -> None:
    with pytest.raises(AppError):
        Config.from_env({"CHESS_COM_MCP_AUTH_TOKENS": raw})


def test_duplicate_tokens_are_rejected(token: str) -> None:
    with pytest.raises(AppError, match="unique"):
        Config.from_env({"CHESS_COM_MCP_AUTH_TOKENS": json.dumps({"one": token, "two": token})})


@pytest.mark.parametrize("raw", ["*", "https://host", "host/path", "host name", "host,host"])
def test_invalid_host_allowlists(raw: str) -> None:
    with pytest.raises(AppError):
        Config.from_env({"CHESS_COM_MCP_ALLOWED_HOSTS": raw})


@pytest.mark.parametrize("raw", ["*", "https://host/path", "file://host", "https://user@host", "https://*.host"])
def test_invalid_origin_allowlists(raw: str) -> None:
    with pytest.raises(AppError):
        Config.from_env({"CHESS_COM_MCP_ALLOWED_ORIGINS": raw})
