"""Playlist tools use Feb-2026 endpoints (/me/playlists, /playlists/{id}/items)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from spotify_mcp.auth import PKCEFlow
from spotify_mcp.client import SpotifyClient
from spotify_mcp.models import (
    AddTracksToPlaylistInput,
    CreatePlaylistInput,
    GetPlaylistItemsInput,
    RemoveTracksFromPlaylistInput,
    ReorderPlaylistItemsInput,
    ReplacePlaylistItemsInput,
)
from spotify_mcp.storage import Storage
from spotify_mcp.tools import (
    add_tracks_to_playlist,
    create_playlist,
    get_playlist_items,
    remove_tracks_from_playlist,
    reorder_playlist_items,
    replace_playlist_items,
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
async def test_replace_playlist_items_puts_full_uri_list(client: SpotifyClient) -> None:
    """PUT /v1/playlists/{id}/items with {"uris": [...]} replaces contents in order."""
    route = respx.put("https://api.spotify.com/v1/playlists/P/items").mock(
        return_value=httpx.Response(200, json={"snapshot_id": "snap_new"}),
    )

    out = await replace_playlist_items(
        client,
        ReplacePlaylistItemsInput(
            playlist_id="P", uris=["spotify:track:B", "spotify:track:A"]
        ),
    )

    call = route.calls.last
    assert call.request.method == "PUT"
    assert call.request.url.path == "/v1/playlists/P/items"
    body = call.request.content.decode("utf-8")
    assert body == '{"uris":["spotify:track:B","spotify:track:A"]}'
    assert '"snapshot_id": "snap_new"' in out[0].text
    assert '"count": 2' in out[0].text


@respx.mock
async def test_replace_playlist_items_empty_list_clears(client: SpotifyClient) -> None:
    route = respx.put("https://api.spotify.com/v1/playlists/P/items").mock(
        return_value=httpx.Response(200, json={"snapshot_id": "snap_empty"}),
    )
    await replace_playlist_items(client, ReplacePlaylistItemsInput(playlist_id="P", uris=[]))
    assert route.calls.last.request.content.decode("utf-8") == '{"uris":[]}'


def test_replace_playlist_items_rejects_over_100() -> None:
    with pytest.raises(ValueError):
        ReplacePlaylistItemsInput(playlist_id="P", uris=[f"spotify:track:{i}" for i in range(101)])


@respx.mock
async def test_reorder_playlist_items_sends_range_body(client: SpotifyClient) -> None:
    route = respx.put("https://api.spotify.com/v1/playlists/P/items").mock(
        return_value=httpx.Response(200, json={"snapshot_id": "snap_moved"}),
    )

    await reorder_playlist_items(
        client,
        ReorderPlaylistItemsInput(
            playlist_id="P", range_start=5, insert_before=0, range_length=2, snapshot_id="s0"
        ),
    )

    body = route.calls.last.request.content.decode("utf-8")
    assert body == '{"range_start":5,"insert_before":0,"range_length":2,"snapshot_id":"s0"}'


@respx.mock
async def test_get_playlist_items_returns_positions_and_has_more(client: SpotifyClient) -> None:
    route = respx.get("https://api.spotify.com/v1/playlists/P/items").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 3,
                "next": "https://api.spotify.com/v1/playlists/P/items?offset=2&limit=2",
                "items": [
                    {
                        "item": {
                            "id": "A",
                            "name": "a",
                            "uri": "spotify:track:A",
                            "duration_ms": 1000,
                            "artists": [{"name": "X"}],
                            "album": {"name": "Al"},
                        }
                    },
                    {"item": {"id": None, "name": "local", "uri": "spotify:local:x"}},
                ],
            },
        ),
    )

    out = await get_playlist_items(
        client, GetPlaylistItemsInput(playlist_id="P", limit=2, offset=0)
    )

    call = route.calls.last
    assert call.request.url.path == "/v1/playlists/P/items"
    assert call.request.url.params["limit"] == "2"
    assert call.request.url.params["offset"] == "0"
    payload = json.loads(out[0].text)
    assert payload["total"] == 3
    assert payload["has_more"] is True
    assert [i["position"] for i in payload["items"]] == [0]  # id-less item skipped
    assert payload["items"][0]["uri"] == "spotify:track:A"


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
