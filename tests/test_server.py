from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from mcp import Client

from chess_com_mcp.client import ChessComClient
from chess_com_mcp.config import Config
from chess_com_mcp.server import create_server

pytestmark = pytest.mark.integration


class Upstream:
    def __init__(self, responses: dict[str, tuple[str, Any]]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        media_type, data = self.responses[request.url.path]
        if isinstance(data, bytes):
            return httpx.Response(200, headers={"Content-Type": media_type}, content=data)
        return httpx.Response(200, headers={"Content-Type": media_type}, json=data)


async def call_tool(upstream: Upstream, name: str, arguments: dict[str, Any]) -> Any:
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http:
        server = create_server(Config(), client=ChessComClient(client=http))
        async with Client(server) as mcp:
            return await mcp.call_tool(name, arguments)


@pytest.mark.asyncio
async def test_all_tools_are_exposed_read_only() -> None:
    upstream = Upstream({})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http:
        async with Client(create_server(Config(), client=ChessComClient(client=http))) as mcp:
            result = await mcp.list_tools()
    assert len(result.tools) == 10
    assert {tool.name for tool in result.tools} == {
        "get_player_profile",
        "get_player_stats",
        "is_player_online",
        "get_player_current_daily_games",
        "get_player_game_archives",
        "get_player_games_by_month",
        "get_player_games_pgn_by_month",
        "get_titled_players",
        "get_club_profile",
        "get_club_members",
    }
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in result.tools)
    assert all(tool.annotations and tool.annotations.destructive_hint is False for tool in result.tools)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args", "path", "payload"),
    [
        ("get_player_profile", {"username": "erik"}, "/pub/player/erik", {"username": "erik"}),
        ("get_player_stats", {"username": "erik"}, "/pub/player/erik/stats", {"chess_blitz": {}}),
        ("is_player_online", {"username": "erik"}, "/pub/player/erik/is-online", {"online": False}),
        ("get_club_profile", {"url_id": "my-club"}, "/pub/club/my-club", {"name": "Club"}),
    ],
)
async def test_simple_tools(tool: str, args: dict[str, Any], path: str, payload: dict[str, Any]) -> None:
    upstream = Upstream({path: ("application/json", payload)})
    result = await call_tool(upstream, tool, args)
    assert result.is_error is False
    assert result.structured_content["data"] == payload
    assert result.structured_content["untrusted_external_data"] is True


@pytest.mark.asyncio
async def test_current_games_are_paginated() -> None:
    path = "/pub/player/erik/games"
    upstream = Upstream({path: ("application/json", {"games": [{"id": 1}, {"id": 2}, {"id": 3}]})})
    result = await call_tool(
        upstream,
        "get_player_current_daily_games",
        {"username": "erik", "offset": 1, "limit": 1},
    )
    assert result.structured_content["data"] == {
        "items": [{"id": 2}],
        "offset": 1,
        "limit": 1,
        "returned": 1,
        "total": 3,
        "has_more": True,
    }


@pytest.mark.asyncio
async def test_monthly_games_omit_pgn() -> None:
    path = "/pub/player/erik/games/2026/01"
    upstream = Upstream(
        {path: ("application/json", {"games": [{"id": 1, "pgn": "untrusted instructions"}, {"id": 2}]})}
    )
    result = await call_tool(
        upstream,
        "get_player_games_by_month",
        {"username": "erik", "year": 2026, "month": 1},
    )
    assert result.structured_content["data"]["items"] == [{"id": 1}, {"id": 2}]


@pytest.mark.asyncio
async def test_pgn_segmentation() -> None:
    path = "/pub/player/erik/games/2026/01/pgn"
    upstream = Upstream({path: ("application/x-chess-pgn", b"a" * 2000)})
    result = await call_tool(
        upstream,
        "get_player_games_pgn_by_month",
        {"username": "erik", "year": 2026, "month": 1, "offset_chars": 500, "max_chars": 1000},
    )
    data = result.structured_content["data"]
    assert data["text"] == "a" * 1000
    assert data["returned_chars"] == 1000
    assert data["next_offset_chars"] == 1500
    assert data["has_more"] is True


@pytest.mark.asyncio
async def test_archives_are_normalized() -> None:
    path = "/pub/player/erik/games/archives"
    upstream = Upstream(
        {
            path: (
                "application/json",
                {"archives": ["https://api.chess.com/pub/player/erik/games/2025/12"]},
            )
        }
    )
    result = await call_tool(upstream, "get_player_game_archives", {"username": "erik"})
    assert result.structured_content["data"] == {"items": [{"year": 2025, "month": 12}]}


@pytest.mark.asyncio
async def test_invalid_archive_url_is_safe_error() -> None:
    path = "/pub/player/erik/games/archives"
    upstream = Upstream({path: ("application/json", {"archives": ["https://evil.example/games/2025/12"]})})
    result = await call_tool(upstream, "get_player_game_archives", {"username": "erik"})
    assert result.is_error
    assert result.structured_content["error"]["code"] == "invalid_upstream_response"
    assert "evil.example" not in json.dumps(result.structured_content)


@pytest.mark.asyncio
async def test_titled_players_and_club_members() -> None:
    upstream = Upstream(
        {
            "/pub/titled/GM": ("application/json", {"players": ["one", "two", "three"]}),
            "/pub/club/my-club/members": (
                "application/json",
                {"weekly": [{"username": "one"}], "monthly": [], "all_time": []},
            ),
        }
    )
    titled = await call_tool(upstream, "get_titled_players", {"title": "gm", "offset": 1, "limit": 2})
    assert titled.structured_content["data"]["items"] == ["two", "three"]
    members = await call_tool(
        upstream,
        "get_club_members",
        {"url_id": "my-club", "category": "weekly", "limit": 100},
    )
    assert members.structured_content["data"]["items"] == [{"username": "one"}]


@pytest.mark.asyncio
async def test_invalid_input_performs_no_request() -> None:
    upstream = Upstream({})
    result = await call_tool(upstream, "get_player_profile", {"username": "../../etc/passwd"})
    assert result.is_error
    assert result.structured_content["error"]["code"] == "invalid_input"
    assert upstream.requests == []


@pytest.mark.asyncio
async def test_unexpected_upstream_shape_is_safe_error() -> None:
    path = "/pub/player/erik/games"
    result = await call_tool(
        Upstream({path: ("application/json", {"games": "wrong"})}),
        "get_player_current_daily_games",
        {"username": "erik"},
    )
    assert result.is_error
    assert result.structured_content["error"]["code"] == "invalid_upstream_response"
