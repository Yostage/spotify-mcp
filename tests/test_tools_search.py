"""Phase E TDD test 9: search_tracks returns minimal DTOs (no pagination noise)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from spotify_mcp.auth import PKCEFlow
from spotify_mcp.client import SpotifyClient
from spotify_mcp.models import SearchTracksInput
from spotify_mcp.storage import Storage
from spotify_mcp.tools import search_tracks
from tests.conftest import load_fixture


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
async def test_search_tracks_returns_minimal_dtos(client: SpotifyClient) -> None:
    fixture = load_fixture("search_tracks.json")
    respx.get("https://api.spotify.com/v1/search").mock(
        return_value=httpx.Response(200, json=fixture),
    )

    result = await search_tracks(client, SearchTracksInput(query="halsey", limit=2))

    assert len(result) == 1
    items = json.loads(result[0].text)
    assert isinstance(items, list)
    assert len(items) == 2

    first = items[0]
    # Exactly the contract from plan test 9
    assert set(first.keys()) == {"id", "name", "artists", "album_name", "duration_ms", "uri"}
    assert first["id"] == "track_one_id"
    assert first["name"] == "Without Me"
    assert first["artists"] == ["Halsey"]
    assert first["album_name"] == "Manic"
    assert first["duration_ms"] == 201661

    # And explicitly: no pagination noise survived the projection
    assert "external_urls" not in first
    assert "available_markets" not in first
    assert "popularity" not in first
    assert "images" not in first


def test_search_limit_capped_at_10() -> None:
    """Spotify /search rejects limit > 10 with 400 "Invalid limit" — keep the schema in step."""
    from pydantic import ValidationError

    from spotify_mcp.models import (
        SearchAlbumsInput,
        SearchArtistsInput,
        SearchPlaylistsInput,
        SearchTracksInput,
    )

    for cls in (SearchTracksInput, SearchAlbumsInput, SearchArtistsInput, SearchPlaylistsInput):
        assert cls(query="q", limit=10).limit == 10
        with pytest.raises(ValidationError):
            cls(query="q", limit=11)
