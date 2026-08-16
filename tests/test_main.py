from __future__ import annotations

import json
from typing import Any

import pytest

import chess_com_mcp.__main__ as cli


class FakeServer:
    def __init__(self) -> None:
        self.transports: list[str] = []

    def run(self, transport: str) -> None:
        self.transports.append(transport)


def clear_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "CHESS_COM_MCP_TRANSPORT",
        "CHESS_COM_MCP_BIND_HOST",
        "CHESS_COM_MCP_PORT",
        "CHESS_COM_MCP_TIMEOUT_SECONDS",
        "CHESS_COM_MCP_MAX_RESPONSE_BYTES",
        "CHESS_COM_MCP_LOG_LEVEL",
        "CHESS_COM_MCP_AUTH_TOKENS",
        "CHESS_COM_MCP_ALLOWED_HOSTS",
        "CHESS_COM_MCP_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_main_defaults_to_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_configuration(monkeypatch)
    server = FakeServer()
    monkeypatch.setattr(cli, "create_server", lambda config: server)
    cli.main([])
    assert server.transports == ["stdio"]


def test_main_starts_http(monkeypatch: pytest.MonkeyPatch, token: str) -> None:
    clear_configuration(monkeypatch)
    server = FakeServer()
    captured: dict[str, Any] = {}
    monkeypatch.setenv("CHESS_COM_MCP_AUTH_TOKENS", json.dumps({"codex": token}))
    monkeypatch.setenv("CHESS_COM_MCP_ALLOWED_HOSTS", "chess.home.arpa")
    monkeypatch.setattr(cli, "create_server", lambda config: server)

    def fake_run_http(selected_server: Any, config: Any) -> None:
        captured.update(server=selected_server, config=config)

    monkeypatch.setattr(cli, "run_http", fake_run_http)
    cli.main(["--transport", "http"])
    assert captured["server"] is server
    assert captured["config"].transport == "http"


def test_main_reports_configuration_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    clear_configuration(monkeypatch)
    monkeypatch.setenv("CHESS_COM_MCP_PORT", "invalid")
    with pytest.raises(SystemExit) as caught:
        cli.main([])
    assert caught.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "Configuration error" in output.err
