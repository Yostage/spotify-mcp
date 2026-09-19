"""Phase F TDD tests 15-16: server lists all 23 tools, unknown tool returns error."""

from __future__ import annotations

import json
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from spotify_mcp.client import SpotifyClient
from spotify_mcp.server import handle_call_tool, handle_list_tools

EXPECTED_TOOL_NAMES = {
    "search_tracks",
    "search_albums",
    "search_artists",
    "search_playlists",
    "get_track",
    "get_album",
    "get_artist",
    "get_playlist",
    "create_playlist",
    "add_tracks_to_playlist",
    "remove_tracks_from_playlist",
    "list_my_playlists",
    "change_playlist_details",
    "get_playlist_items",
    "replace_playlist_items",
    "reorder_playlist_items",
    "get_current_playback",
    "start_playback",
    "pause_playback",
    "next_track",
    "previous_track",
    "seek",
    "set_volume",
    "list_devices",
    "add_to_queue",
    "get_queue",
    "save_tracks_to_library",
}


async def test_server_lists_all_27_tools() -> None:
    tools = await handle_list_tools()
    assert len(tools) == 27
    assert {t.name for t in tools} == EXPECTED_TOOL_NAMES
    # Every tool must have a non-empty description and an inputSchema.
    for t in tools:
        assert t.description, f"tool {t.name} has empty description"
        assert t.inputSchema, f"tool {t.name} has no inputSchema"


async def test_call_tool_unknown_name_returns_error_text_content() -> None:
    # Dummy client — should never be touched since lookup fails before dispatch.
    fake_client = cast(SpotifyClient, MagicMock(spec=SpotifyClient))

    result = await handle_call_tool(fake_client, "not_a_tool", {})

    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["error"] == "unknown_tool"
    assert "unknown tool" in payload["message"].lower()
    assert "not_a_tool" in payload["message"]


async def test_call_tool_translates_no_refresh_token_to_structured_error() -> None:
    from spotify_mcp.storage import NoRefreshTokenError

    fake_client = MagicMock(spec=SpotifyClient)
    fake_client.get_me = AsyncMock(side_effect=NoRefreshTokenError("missing"))
    # We have to monkeypatch a tool to raise — use search_tracks since it calls client.search
    fake_client.search = AsyncMock(side_effect=NoRefreshTokenError("no token"))

    result = await handle_call_tool(
        cast(SpotifyClient, fake_client),
        "search_tracks",
        {"query": "halsey", "limit": 5},
    )

    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["error"] == "no_refresh_token"
    assert "auth flow" in payload["remediation"]


async def test_call_tool_validation_error_caught_in_envelope() -> None:
    fake_client = cast(SpotifyClient, MagicMock(spec=SpotifyClient))

    # Missing required field `query` for search_tracks — pydantic raises
    result = await handle_call_tool(fake_client, "search_tracks", {})

    assert len(result) == 1
    payload = json.loads(result[0].text)
    # Pydantic raises ValidationError — type name surfaces in envelope
    assert payload["error"] == "ValidationError"


@pytest.mark.skipif(
    True, reason="smoke check, opt-in only — exercises build_server wiring"
)
async def test_build_server_wires_handlers() -> None:
    from spotify_mcp.server import build_server

    def provider() -> SpotifyClient:
        return cast(SpotifyClient, MagicMock(spec=SpotifyClient))

    srv = build_server(provider)
    assert srv is not None
