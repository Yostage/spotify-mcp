"""Phase E TDD tests 10-11: playlist tools use Feb-2026 endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from spotify_mcp.auth import PKCEFlow
from spotify_mcp.client import SpotifyClient
from spotify_mcp.models import (
    AddTracksToPlaylistInput,
    CreatePlaylistInput,
    RemoveTracksFromPlaylistInput,
)
from spotify_mcp.storage import Storage
from spotify_mcp.tools import (
    add_tracks_to_playlist,
    create_playlist,
    remove_tracks_from_playlist,
)


@pytest.fixture
async def client(
    fake_keyring: dict[tuple[str, str], str],
) -> AsyncIterator[SpotifyClient]:
    storage = Storage(client_id="CID")
    storage.set_refresh_token("rt_initial")
    sc = SpotifyClient(client_id="CID", storage=storage, auth=PKCEFlow("CID"))
    sc._access_token = "at_xyz"
    yield sc
    await sc.aclose()


@respx.mock
async def test_create_playlist_uses_me_playlists_endpoint(client: SpotifyClient) -> None:
    """Feb-2026: POST /v1/me/playlists (NOT /v1/users/{id}/playlists)."""
    route = respx.post("https://api.spotify.com/v1/me/playlists").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "pl_new",
                "name": "x",
                "uri": "spotify:playlist:pl_new",
                "owner": {"id": "u", "display_name": "u"},
                "public": False,
                "description": "",
                "tracks": {"total": 0},
            },
        ),
    )

    await create_playlist(client, CreatePlaylistInput(name="x"))

    call = route.calls.last
    assert call.request.url.path == "/v1/me/playlists"
    assert "users" not in call.request.url.path
    body = call.request.content.decode("utf-8")
    # Body must carry name + public + (optionally) description
    assert '"name":"x"' in body
    assert '"public":false' in body


@respx.mock
async def test_add_tracks_to_playlist_uses_items_endpoint(client: SpotifyClient) -> None:
    """Feb-2026: POST /v1/playlists/{id}/items (NOT /tracks)."""
    route = respx.post("https://api.spotify.com/v1/playlists/P/items").mock(
        return_value=httpx.Response(201, json={"snapshot_id": "snap_xyz"}),
    )

    await add_tracks_to_playlist(
        client,
        AddTracksToPlaylistInput(playlist_id="P", uris=["spotify:track:T"]),
    )

    call = route.calls.last
    assert call.request.url.path == "/v1/playlists/P/items"
    assert not call.request.url.path.endswith("/tracks")
    body = call.request.content.decode("utf-8")
    assert '"uris":["spotify:track:T"]' in body


@respx.mock
async def test_remove_tracks_from_playlist_uses_items_body_key(client: SpotifyClient) -> None:
    """Feb-2026: DELETE /v1/playlists/{id}/items takes {"items": [{"uri": ...}]}, not "tracks"."""
    route = respx.delete("https://api.spotify.com/v1/playlists/P/items").mock(
        return_value=httpx.Response(200, json={"snapshot_id": "snap_rm"}),
    )

    await remove_tracks_from_playlist(
        client,
        RemoveTracksFromPlaylistInput(playlist_id="P", uris=["spotify:track:T"]),
    )

    call = route.calls.last
    assert call.request.url.path == "/v1/playlists/P/items"
    assert call.request.content.decode("utf-8") == '{"items":[{"uri":"spotify:track:T"}]}'
