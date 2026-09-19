"""27 MCP tool implementations — pure functions over SpotifyClient.

Each tool takes a validated pydantic input model and returns a list of
mcp.types.TextContent. Validation and exception-to-error-envelope translation
live in server.py.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import mcp.types as types
from pydantic import BaseModel

from spotify_mcp.client import SpotifyClient
from spotify_mcp.models import (
    AddToQueueInput,
    AddTracksToPlaylistInput,
    Album,
    Artist,
    ChangePlaylistDetailsInput,
    CreatePlaylistInput,
    Device,
    GetAlbumInput,
    GetArtistInput,
    GetCurrentPlaybackInput,
    GetPlaylistInput,
    GetPlaylistItemsInput,
    GetQueueInput,
    GetTrackInput,
    ListDevicesInput,
    ListMyPlaylistsInput,
    NextTrackInput,
    PausePlaybackInput,
    Playlist,
    PreviousTrackInput,
    RemoveTracksFromPlaylistInput,
    ReorderPlaylistItemsInput,
    ReplacePlaylistItemsInput,
    SaveTracksToLibraryInput,
    SearchAlbumsInput,
    SearchArtistsInput,
    SearchPlaylistsInput,
    SearchTracksInput,
    SeekInput,
    SetVolumeInput,
    StartPlaybackInput,
    Track,
)


def _text(payload: Any) -> list[types.TextContent]:
    return [
        types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))
    ]


def _items(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    container: dict[str, Any] = raw.get(key) or {}
    items: list[dict[str, Any]] = container.get("items") or []
    return items


# ============================================================
# Search (4)
# ============================================================


async def search_tracks(
    client: SpotifyClient, inp: SearchTracksInput
) -> list[types.TextContent]:
    raw = await client.search(inp.query, type_="track", limit=inp.limit)
    return _text([Track.from_spotify(t).model_dump() for t in _items(raw, "tracks")])


async def search_albums(
    client: SpotifyClient, inp: SearchAlbumsInput
) -> list[types.TextContent]:
    raw = await client.search(inp.query, type_="album", limit=inp.limit)
    return _text([Album.from_spotify(a).model_dump() for a in _items(raw, "albums")])


async def search_artists(
    client: SpotifyClient, inp: SearchArtistsInput
) -> list[types.TextContent]:
    raw = await client.search(inp.query, type_="artist", limit=inp.limit)
    return _text([Artist.from_spotify(a).model_dump() for a in _items(raw, "artists")])


async def search_playlists(
    client: SpotifyClient, inp: SearchPlaylistsInput
) -> list[types.TextContent]:
    raw = await client.search(inp.query, type_="playlist", limit=inp.limit)
    return _text(
        [Playlist.from_spotify(p).model_dump() for p in _items(raw, "playlists")]
    )


# ============================================================
# Get-info (4)
# ============================================================


async def get_track(
    client: SpotifyClient, inp: GetTrackInput
) -> list[types.TextContent]:
    raw = await client.get_track(inp.track_id)
    return _text(Track.from_spotify(raw).model_dump())


async def get_album(
    client: SpotifyClient, inp: GetAlbumInput
) -> list[types.TextContent]:
    raw = await client.get_album(inp.album_id)
    return _text(Album.from_spotify(raw).model_dump())


async def get_artist(
    client: SpotifyClient, inp: GetArtistInput
) -> list[types.TextContent]:
    # Per plan resolved Q#3: top-tracks endpoint is gone post-Feb-2026. Drop it.
    # Single GET /artists/{id} + /artists/{id}/albums survive.
    raw_artist = await client.get_artist(inp.artist_id)
    raw_albums = await client.get_artist_albums(inp.artist_id)
    album_items: list[dict[str, Any]] = raw_albums.get("items") or []
    return _text(
        {
            "artist": Artist.from_spotify(raw_artist).model_dump(),
            "albums": [Album.from_spotify(a).model_dump() for a in album_items],
        }
    )


async def get_playlist(
    client: SpotifyClient, inp: GetPlaylistInput
) -> list[types.TextContent]:
    raw = await client.get_playlist(inp.playlist_id)
    return _text(Playlist.from_spotify(raw).model_dump())


# ============================================================
# Playlist (8) — Feb-2026 endpoints (/me/playlists, /playlists/{id}/items)
# ============================================================


async def create_playlist(
    client: SpotifyClient, inp: CreatePlaylistInput
) -> list[types.TextContent]:
    raw = await client.create_playlist(
        name=inp.name, description=inp.description, public=inp.public
    )
    return _text(Playlist.from_spotify(raw).model_dump())


async def add_tracks_to_playlist(
    client: SpotifyClient, inp: AddTracksToPlaylistInput
) -> list[types.TextContent]:
    raw = await client.add_tracks_to_playlist(inp.playlist_id, inp.uris)
    return _text({"snapshot_id": raw.get("snapshot_id"), "added": len(inp.uris)})


async def remove_tracks_from_playlist(
    client: SpotifyClient, inp: RemoveTracksFromPlaylistInput
) -> list[types.TextContent]:
    raw = await client.remove_tracks_from_playlist(inp.playlist_id, inp.uris)
    return _text({"snapshot_id": raw.get("snapshot_id"), "removed": len(inp.uris)})


async def list_my_playlists(
    client: SpotifyClient, inp: ListMyPlaylistsInput
) -> list[types.TextContent]:
    raw = await client.list_my_playlists(limit=inp.limit)
    items: list[dict[str, Any]] = raw.get("items") or []
    return _text([Playlist.from_spotify(p).model_dump() for p in items])


async def change_playlist_details(
    client: SpotifyClient, inp: ChangePlaylistDetailsInput
) -> list[types.TextContent]:
    await client.change_playlist_details(
        inp.playlist_id,
        name=inp.name,
        description=inp.description,
        public=inp.public,
    )
    return _text({"playlist_id": inp.playlist_id, "updated": True})


async def get_playlist_items(
    client: SpotifyClient, inp: GetPlaylistItemsInput
) -> list[types.TextContent]:
    raw = await client.get_playlist_items(
        inp.playlist_id, limit=inp.limit, offset=inp.offset
    )
    items: list[dict[str, Any]] = raw.get("items") or []
    tracks: list[dict[str, Any]] = []
    for pos, it in enumerate(items, start=inp.offset):
        # Feb-2026 /items wraps each row as {"item": {...}} (not "track").
        t: dict[str, Any] = it.get("item") or {}
        if not t.get("id"):
            continue  # local files / unavailable tracks have no id
        d = Track.from_spotify(t).model_dump()
        d["position"] = pos
        tracks.append(d)
    return _text(
        {
            "playlist_id": inp.playlist_id,
            "total": raw.get("total"),
            "offset": inp.offset,
            "has_more": bool(raw.get("next")),
            "items": tracks,
        }
    )


async def replace_playlist_items(
    client: SpotifyClient, inp: ReplacePlaylistItemsInput
) -> list[types.TextContent]:
    raw = await client.replace_playlist_items(inp.playlist_id, inp.uris)
    return _text({"snapshot_id": raw.get("snapshot_id"), "count": len(inp.uris)})


async def reorder_playlist_items(
    client: SpotifyClient, inp: ReorderPlaylistItemsInput
) -> list[types.TextContent]:
    raw = await client.reorder_playlist_items(
        inp.playlist_id,
        range_start=inp.range_start,
        insert_before=inp.insert_before,
        range_length=inp.range_length,
        snapshot_id=inp.snapshot_id,
    )
    return _text(
        {
            "snapshot_id": raw.get("snapshot_id"),
            "moved": inp.range_length,
            "from": inp.range_start,
            "insert_before": inp.insert_before,
        }
    )


# ============================================================
# Playback + queue (10)
# ============================================================


async def get_current_playback(
    client: SpotifyClient, inp: GetCurrentPlaybackInput
) -> list[types.TextContent]:
    raw = await client.get_current_playback()
    if not raw:
        return _text({"is_playing": False, "track": None})
    item: dict[str, Any] = raw.get("item") or {}
    track = Track.from_spotify(item).model_dump() if item.get("id") else None
    return _text(
        {
            "is_playing": bool(raw.get("is_playing", False)),
            "progress_ms": raw.get("progress_ms"),
            "track": track,
        }
    )


async def start_playback(
    client: SpotifyClient, inp: StartPlaybackInput
) -> list[types.TextContent]:
    await client.start_playback(uri=inp.uri, device_id=inp.device_id)
    return _text({"started": True, "uri": inp.uri})


async def pause_playback(
    client: SpotifyClient, inp: PausePlaybackInput
) -> list[types.TextContent]:
    await client.pause_playback(device_id=inp.device_id)
    return _text({"paused": True})


async def next_track(
    client: SpotifyClient, inp: NextTrackInput
) -> list[types.TextContent]:
    await client.next_track(device_id=inp.device_id)
    return _text({"skipped": "next"})


async def previous_track(
    client: SpotifyClient, inp: PreviousTrackInput
) -> list[types.TextContent]:
    await client.previous_track(device_id=inp.device_id)
    return _text({"skipped": "previous"})


async def seek(client: SpotifyClient, inp: SeekInput) -> list[types.TextContent]:
    await client.seek(inp.position_ms, device_id=inp.device_id)
    return _text({"seeked_to_ms": inp.position_ms})


async def set_volume(
    client: SpotifyClient, inp: SetVolumeInput
) -> list[types.TextContent]:
    await client.set_volume(inp.volume_percent, device_id=inp.device_id)
    return _text({"volume_percent": inp.volume_percent})


async def list_devices(
    client: SpotifyClient, inp: ListDevicesInput
) -> list[types.TextContent]:
    raw = await client.list_devices()
    devices: list[dict[str, Any]] = raw.get("devices") or []
    return _text([Device.from_spotify(d).model_dump() for d in devices])


async def add_to_queue(
    client: SpotifyClient, inp: AddToQueueInput
) -> list[types.TextContent]:
    await client.add_to_queue(inp.uri, device_id=inp.device_id)
    return _text({"queued": inp.uri})


async def save_tracks_to_library(
    client: SpotifyClient, inp: SaveTracksToLibraryInput
) -> list[types.TextContent]:
    await client.save_tracks_to_library(inp.track_ids)
    return _text({"saved": len(inp.track_ids), "track_ids": inp.track_ids})


async def get_queue(
    client: SpotifyClient, inp: GetQueueInput
) -> list[types.TextContent]:
    raw = await client.get_queue()
    current: dict[str, Any] = raw.get("currently_playing") or {}
    queue: list[dict[str, Any]] = raw.get("queue") or []
    return _text(
        {
            "currently_playing": (
                Track.from_spotify(current).model_dump() if current.get("id") else None
            ),
            "queue": [Track.from_spotify(t).model_dump() for t in queue],
        }
    )


# ============================================================
# Registry: tool name → (input schema, async handler)
# Consumed by server.py for dispatch and JSON-schema generation.
# ============================================================


ToolHandler = Callable[
    [SpotifyClient, Any], Awaitable[list[types.TextContent]]
]

TOOLS: dict[str, tuple[type[BaseModel], ToolHandler]] = {
    "search_tracks": (SearchTracksInput, search_tracks),
    "search_albums": (SearchAlbumsInput, search_albums),
    "search_artists": (SearchArtistsInput, search_artists),
    "search_playlists": (SearchPlaylistsInput, search_playlists),
    "get_track": (GetTrackInput, get_track),
    "get_album": (GetAlbumInput, get_album),
    "get_artist": (GetArtistInput, get_artist),
    "get_playlist": (GetPlaylistInput, get_playlist),
    "create_playlist": (CreatePlaylistInput, create_playlist),
    "add_tracks_to_playlist": (AddTracksToPlaylistInput, add_tracks_to_playlist),
    "remove_tracks_from_playlist": (
        RemoveTracksFromPlaylistInput,
        remove_tracks_from_playlist,
    ),
    "list_my_playlists": (ListMyPlaylistsInput, list_my_playlists),
    "change_playlist_details": (ChangePlaylistDetailsInput, change_playlist_details),
    "get_playlist_items": (GetPlaylistItemsInput, get_playlist_items),
    "replace_playlist_items": (ReplacePlaylistItemsInput, replace_playlist_items),
    "reorder_playlist_items": (ReorderPlaylistItemsInput, reorder_playlist_items),
    "get_current_playback": (GetCurrentPlaybackInput, get_current_playback),
    "start_playback": (StartPlaybackInput, start_playback),
    "pause_playback": (PausePlaybackInput, pause_playback),
    "next_track": (NextTrackInput, next_track),
    "previous_track": (PreviousTrackInput, previous_track),
    "seek": (SeekInput, seek),
    "set_volume": (SetVolumeInput, set_volume),
    "list_devices": (ListDevicesInput, list_devices),
    "add_to_queue": (AddToQueueInput, add_to_queue),
    "get_queue": (GetQueueInput, get_queue),
    "save_tracks_to_library": (SaveTracksToLibraryInput, save_tracks_to_library),
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "search_tracks": "Search Spotify tracks by query. Returns minimal track DTOs.",
    "search_albums": "Search Spotify albums by query.",
    "search_artists": "Search Spotify artists by query.",
    "search_playlists": "Search public Spotify playlists by query.",
    "get_track": "Get a single Spotify track by ID.",
    "get_album": "Get a single Spotify album by ID.",
    "get_artist": "Get artist info + their albums (post-Feb-2026 top-tracks endpoint is gone).",
    "get_playlist": "Get a single playlist by ID.",
    "create_playlist": "Create a new playlist on the authenticated user's account. "
    "public defaults to False — pass public=True explicitly to share.",
    "add_tracks_to_playlist": "Append track URIs to a playlist (Feb-2026 /items endpoint).",
    "remove_tracks_from_playlist": "Remove track URIs from a playlist (Feb-2026 /items endpoint).",
    "list_my_playlists": "List the authenticated user's playlists.",
    "change_playlist_details": "Update a playlist's name, description, or public flag.",
    "get_playlist_items": "List a playlist's tracks in order with 0-based positions. "
    "Paginated (limit<=100, offset); loop while has_more.",
    "replace_playlist_items": "Replace the ENTIRE playlist contents with the given track URIs, "
    "in that order, in one atomic call (max 100 URIs; empty list clears). "
    "Use this to reorder or trim a playlist deterministically.",
    "reorder_playlist_items": "Move a contiguous block of items: range_length items starting at "
    "range_start are placed before insert_before (0-based positions). "
    "Pass snapshot_id from get_playlist to guard against concurrent edits.",
    "get_current_playback": "Get the user's currently-playing track and playback state.",
    "start_playback": "Start or resume playback. Pass a track URI for a single track, "
    "or an album/playlist/artist URI for a context.",
    "pause_playback": "Pause playback on the active device.",
    "next_track": "Skip to the next track.",
    "previous_track": "Skip to the previous track.",
    "seek": "Seek to a position in milliseconds in the current track.",
    "set_volume": "Set playback volume (0-100).",
    "list_devices": "List the user's Spotify Connect devices.",
    "add_to_queue": "Add a track URI to the playback queue.",
    "get_queue": "Get the playback queue (currently playing + upcoming).",
    "save_tracks_to_library": "Save up to 50 tracks to the user's Liked Songs in one call. "
    "Pass track IDs (the bare Spotify ID, not the full URI). Caller batches if >50.",
}
