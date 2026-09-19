"""Pydantic schemas: 23 MCP tool inputs + 5 lightweight response DTOs.

DTOs surface only what an LLM needs — no pagination cursors, no HATEOAS noise,
no external_urls dictionaries seven levels deep.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field


class _Input(BaseModel):
    """Strict base for tool inputs — unknown fields are a hard error."""

    model_config = ConfigDict(extra="forbid")


# ============================================================
# Tool input schemas (23 — one per MCP tool)
# ============================================================


# Spotify now rejects /search with limit > 10 (400 "Invalid limit"); observed
# 2026-09 against a development-mode app. Cap the schema so the LLM can't ask.
class SearchTracksInput(_Input):
    query: str
    limit: int = Field(default=10, ge=1, le=10)


class SearchAlbumsInput(_Input):
    query: str
    limit: int = Field(default=10, ge=1, le=10)


class SearchArtistsInput(_Input):
    query: str
    limit: int = Field(default=10, ge=1, le=10)


class SearchPlaylistsInput(_Input):
    query: str
    limit: int = Field(default=10, ge=1, le=10)


class GetTrackInput(_Input):
    track_id: str


class GetAlbumInput(_Input):
    album_id: str


class GetArtistInput(_Input):
    artist_id: str


class GetPlaylistInput(_Input):
    playlist_id: str


class CreatePlaylistInput(_Input):
    name: str
    description: str | None = None
    # Locked default False — see plan resolved Q#4. Diverges from Spotify's API
    # default (True) because an AI tool shouldn't spam the user's public profile.
    public: bool = False


class AddTracksToPlaylistInput(_Input):
    playlist_id: str
    uris: list[str] = Field(min_length=1)


class RemoveTracksFromPlaylistInput(_Input):
    playlist_id: str
    uris: list[str] = Field(min_length=1)


class ListMyPlaylistsInput(_Input):
    limit: int = Field(default=50, ge=1, le=50)


class ChangePlaylistDetailsInput(_Input):
    playlist_id: str
    name: str | None = None
    description: str | None = None
    public: bool | None = None


class GetCurrentPlaybackInput(_Input):
    pass


class StartPlaybackInput(_Input):
    uri: str | None = None
    device_id: str | None = None


class PausePlaybackInput(_Input):
    device_id: str | None = None


class NextTrackInput(_Input):
    device_id: str | None = None


class PreviousTrackInput(_Input):
    device_id: str | None = None


class SeekInput(_Input):
    position_ms: int = Field(ge=0)
    device_id: str | None = None


class SetVolumeInput(_Input):
    volume_percent: int = Field(ge=0, le=100)
    device_id: str | None = None


class ListDevicesInput(_Input):
    pass


class AddToQueueInput(_Input):
    uri: str
    device_id: str | None = None


class GetQueueInput(_Input):
    pass


class SaveTracksToLibraryInput(_Input):
    # Spotify accepts up to 50 IDs per call — caller batches if more.
    track_ids: list[str] = Field(min_length=1, max_length=50)


# ============================================================
# Response DTOs — minimal, LLM-friendly projections of Spotify API objects
# ============================================================


def _names(items: list[dict[str, Any]] | None) -> list[str]:
    return [str(i["name"]) for i in (items or []) if "name" in i]


class Track(BaseModel):
    id: str
    name: str
    artists: list[str]
    album_name: str | None = None
    duration_ms: int | None = None
    uri: str

    @classmethod
    def from_spotify(cls, payload: dict[str, Any]) -> Self:
        album: dict[str, Any] = payload.get("album") or {}
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            artists=_names(payload.get("artists")),
            album_name=album.get("name"),
            duration_ms=payload.get("duration_ms"),
            uri=str(payload["uri"]),
        )


class Album(BaseModel):
    id: str
    name: str
    artists: list[str]
    release_date: str | None = None
    total_tracks: int | None = None
    uri: str

    @classmethod
    def from_spotify(cls, payload: dict[str, Any]) -> Self:
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            artists=_names(payload.get("artists")),
            release_date=payload.get("release_date"),
            total_tracks=payload.get("total_tracks"),
            uri=str(payload["uri"]),
        )


class Artist(BaseModel):
    id: str
    name: str
    genres: list[str] = Field(default_factory=list)
    followers: int | None = None
    uri: str

    @classmethod
    def from_spotify(cls, payload: dict[str, Any]) -> Self:
        followers: dict[str, Any] = payload.get("followers") or {}
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            genres=[str(g) for g in payload.get("genres", [])],
            followers=followers.get("total"),
            uri=str(payload["uri"]),
        )


class Playlist(BaseModel):
    id: str
    name: str
    description: str | None = None
    owner: str | None = None
    public: bool | None = None
    total_tracks: int | None = None
    uri: str

    @classmethod
    def from_spotify(cls, payload: dict[str, Any]) -> Self:
        owner_obj: dict[str, Any] = payload.get("owner") or {}
        owner: str | None = owner_obj.get("display_name") or owner_obj.get("id")
        tracks_obj: dict[str, Any] = payload.get("tracks") or {}
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            description=payload.get("description") or None,
            owner=owner,
            public=payload.get("public"),
            total_tracks=tracks_obj.get("total"),
            uri=str(payload["uri"]),
        )


class Device(BaseModel):
    id: str | None
    name: str
    type: str
    volume_percent: int | None = None
    is_active: bool
    is_restricted: bool

    @classmethod
    def from_spotify(cls, payload: dict[str, Any]) -> Self:
        return cls(
            id=payload.get("id"),
            name=str(payload["name"]),
            type=str(payload["type"]),
            volume_percent=payload.get("volume_percent"),
            is_active=bool(payload.get("is_active", False)),
            is_restricted=bool(payload.get("is_restricted", False)),
        )


# ============================================================
# Tool name → input schema registry (server.py consumes this)
# ============================================================

TOOL_INPUTS: dict[str, type[_Input]] = {
    "search_tracks": SearchTracksInput,
    "search_albums": SearchAlbumsInput,
    "search_artists": SearchArtistsInput,
    "search_playlists": SearchPlaylistsInput,
    "get_track": GetTrackInput,
    "get_album": GetAlbumInput,
    "get_artist": GetArtistInput,
    "get_playlist": GetPlaylistInput,
    "create_playlist": CreatePlaylistInput,
    "add_tracks_to_playlist": AddTracksToPlaylistInput,
    "remove_tracks_from_playlist": RemoveTracksFromPlaylistInput,
    "list_my_playlists": ListMyPlaylistsInput,
    "change_playlist_details": ChangePlaylistDetailsInput,
    "get_current_playback": GetCurrentPlaybackInput,
    "start_playback": StartPlaybackInput,
    "pause_playback": PausePlaybackInput,
    "next_track": NextTrackInput,
    "previous_track": PreviousTrackInput,
    "seek": SeekInput,
    "set_volume": SetVolumeInput,
    "list_devices": ListDevicesInput,
    "add_to_queue": AddToQueueInput,
    "get_queue": GetQueueInput,
    "save_tracks_to_library": SaveTracksToLibraryInput,
}
