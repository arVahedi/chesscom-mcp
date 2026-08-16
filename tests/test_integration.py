from __future__ import annotations

import os

import pytest

from chess_com_mcp.client import ChessComClient


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("CHESS_COM_MCP_RUN_INTEGRATION") != "1", reason="live tests are opt-in")
@pytest.mark.asyncio
async def test_public_profile_live() -> None:
    client = ChessComClient()
    try:
        profile = await client.get_json("/player/erik")
    finally:
        await client.close()
    assert profile["username"].lower() == "erik"
