"""Authenticated httpx client for the Spotify Web API.

Owns the wire format so we can ship the Feb-2026 endpoint changes without
waiting on an upstream library PR. Single retry on 401 (after token refresh)
and single retry on 429 (after honoring Retry-After) — never an unbounded loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx

from spotify_mcp.auth import PKCEFlow
from spotify_mcp.storage import Storage

BASE_URL = "https://api.spotify.com/v1"
DEFAULT_TIMEOUT_S = 15.0

# Spotify's Retry-After can legitimately be HOURS or even days when their dev-mode
# rate limiter punishes an app. Community-confirmed values: 21h, 49000s, even 48h.
# We refuse to silently sleep that long — surface the requested wait so the caller
# can decide. 60s caps it at "tool feels slow" not "tool freezes the MCP session".
MAX_RETRY_AFTER_SLEEP_S = 60.0


class AuthenticationError(Exception):
    """Still 401 after a single token refresh — caller must re-auth."""


class RateLimitError(Exception):
    """Rate-limited 429 twice in a row, even after honoring Retry-After."""


class SpotifyClient:
    """Authenticated wrapper around httpx for the Spotify Web API."""

    def __init__(
        self,
        client_id: str,
        *,
        storage: Storage | None = None,
        auth: PKCEFlow | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._client_id = client_id
        self._storage = storage if storage is not None else Storage(client_id)
        self._auth = auth if auth is not None else PKCEFlow(client_id)
        http_kwargs: dict[str, Any] = {"base_url": BASE_URL, "timeout": timeout}
        if transport is not None:
            http_kwargs["transport"] = transport
        self._http = httpx.AsyncClient(**http_kwargs)
        self._access_token: str | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> SpotifyClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    # ---- core request machinery ----

    async def _refresh_access_token(self) -> None:
        refresh_token = self._storage.get_refresh_token()
        tokens = await self._auth.refresh_access_token(refresh_token)
        self._access_token = str(tokens["access_token"])
        # Spotify may rotate the refresh_token on /api/token. If it does, persist
        # the new one immediately or the stored one eventually becomes invalid.
        if rotated := tokens.get("refresh_token"):
            self._storage.set_refresh_token(str(rotated))

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if self._access_token is None:
            await self._refresh_access_token()

        user_headers = cast(dict[str, str], kwargs.pop("headers", None) or {})

        async def send() -> httpx.Response:
            headers: dict[str, str] = {
                "Authorization": f"Bearer {self._access_token}",
                **user_headers,
            }
            return await self._http.request(method, path, headers=headers, **kwargs)

        resp = await send()

        if resp.status_code == 401:
            await self._refresh_access_token()
            resp = await send()
            if resp.status_code == 401:
                raise AuthenticationError(
                    f"Still 401 after refresh for {method} {path}: {resp.text[:200]}"
                )
        elif resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "1"))
            if retry_after > MAX_RETRY_AFTER_SLEEP_S:
                # Don't silently wait hours. Surface immediately so the caller
                # (LLM/user) sees the real cost and can decide to abandon or
                # wait deliberately at a higher level.
                raise RateLimitError(
                    f"Rate-limited on {method} {path} with Retry-After={retry_after}s "
                    f"(exceeds {MAX_RETRY_AFTER_SLEEP_S}s cap — refusing to wait silently). "
                    f"Spotify dev-mode has punished this app; back off and retry later."
                )
            await asyncio.sleep(retry_after)
            resp = await send()
            if resp.status_code == 429:
                raise RateLimitError(
                    f"Rate-limited twice for {method} {path} "
                    f"(Retry-After={retry_after}s)"
                )

        resp.raise_for_status()
        if not resp.content:
            return {}
        return resp.json()

    # ---- typed helpers (one per Spotify endpoint we use) ----

    async def get_me(self) -> dict[str, Any]:
        return await self._request("GET", "/me")

    async def search(self, query: str, *, type_: str, limit: int = 10) -> dict[str, Any]:
        return await self._request(
            "GET", "/search", params={"q": query, "type": type_, "limit": limit}
        )

    async def get_track(self, track_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/tracks/{track_id}")

    async def get_album(self, album_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/albums/{album_id}")

    async def get_artist(self, artist_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/artists/{artist_id}")

    async def get_artist_albums(
        self, artist_id: str, *, include_groups: str = "album,single", limit: int = 20
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/artists/{artist_id}/albums",
            params={"include_groups": include_groups, "limit": limit},
        )

    async def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/playlists/{playlist_id}")

    # ---- playlist mutation (Feb-2026 endpoints) ----

    async def create_playlist(
        self,
        *,
        name: str,
        description: str | None = None,
        public: bool = False,
    ) -> dict[str, Any]:
        # POST /v1/me/playlists — replaces deprecated /users/{id}/playlists.
        body: dict[str, Any] = {"name": name, "public": public}
        if description is not None:
            body["description"] = description
        return await self._request("POST", "/me/playlists", json=body)

    async def list_my_playlists(self, *, limit: int = 50) -> dict[str, Any]:
        return await self._request("GET", "/me/playlists", params={"limit": limit})

    async def add_tracks_to_playlist(
        self, playlist_id: str, uris: list[str]
    ) -> dict[str, Any]:
        # POST /v1/playlists/{id}/items — replaces deprecated /tracks suffix.
        return await self._request(
            "POST", f"/playlists/{playlist_id}/items", json={"uris": uris}
        )

    async def remove_tracks_from_playlist(
        self, playlist_id: str, uris: list[str]
    ) -> dict[str, Any]:
        # DELETE /v1/playlists/{id}/items — Feb-2026 endpoint.
        return await self._request(
            "DELETE",
            f"/playlists/{playlist_id}/items",
            json={"tracks": [{"uri": u} for u in uris]},
        )

    async def get_playlist_items(
        self, playlist_id: str, *, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        # GET /v1/playlists/{id}/items — Feb-2026 endpoint. Paginated; caller
        # walks `offset` until `next` is null. Fields trimmed to what the DTO needs.
        return await self._request(
            "GET",
            f"/playlists/{playlist_id}/items",
            params={
                "limit": limit,
                "offset": offset,
                "fields": (
                    "total,next,items(item(id,name,uri,duration_ms,"
                    "artists(name),album(name)))"
                ),
            },
        )

    async def replace_playlist_items(
        self, playlist_id: str, uris: list[str]
    ) -> dict[str, Any]:
        # PUT /v1/playlists/{id}/items with `uris` replaces the ENTIRE playlist
        # contents in one atomic call (max 100 URIs). Empty list clears it.
        if len(uris) > 100:
            raise ValueError(f"replace_playlist_items: max 100 uris per call, got {len(uris)}")
        return await self._request(
            "PUT", f"/playlists/{playlist_id}/items", json={"uris": uris}
        )

    async def reorder_playlist_items(
        self,
        playlist_id: str,
        *,
        range_start: int,
        insert_before: int,
        range_length: int = 1,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        # Same PUT endpoint, different body shape: range_start/insert_before move
        # a contiguous block. snapshot_id guards against concurrent edits.
        body: dict[str, Any] = {
            "range_start": range_start,
            "insert_before": insert_before,
            "range_length": range_length,
        }
        if snapshot_id is not None:
            body["snapshot_id"] = snapshot_id
        return await self._request("PUT", f"/playlists/{playlist_id}/items", json=body)

    async def change_playlist_details(
        self,
        playlist_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        public: bool | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if public is not None:
            body["public"] = public
        return await self._request("PUT", f"/playlists/{playlist_id}", json=body)

    # ---- playback ----

    async def get_current_playback(self) -> dict[str, Any]:
        return await self._request("GET", "/me/player")

    async def list_devices(self) -> dict[str, Any]:
        return await self._request("GET", "/me/player/devices")

    async def start_playback(
        self, *, uri: str | None = None, device_id: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if uri is not None:
            if uri.startswith("spotify:track:"):
                body["uris"] = [uri]
            elif uri.startswith(
                ("spotify:album:", "spotify:playlist:", "spotify:artist:")
            ):
                body["context_uri"] = uri
            else:
                raise ValueError(f"Unsupported playback URI: {uri!r}")
        params = {"device_id": device_id} if device_id else None
        return await self._request("PUT", "/me/player/play", json=body, params=params)

    async def pause_playback(self, *, device_id: str | None = None) -> dict[str, Any]:
        params = {"device_id": device_id} if device_id else None
        return await self._request("PUT", "/me/player/pause", params=params)

    async def next_track(self, *, device_id: str | None = None) -> dict[str, Any]:
        params = {"device_id": device_id} if device_id else None
        return await self._request("POST", "/me/player/next", params=params)

    async def previous_track(self, *, device_id: str | None = None) -> dict[str, Any]:
        params = {"device_id": device_id} if device_id else None
        return await self._request("POST", "/me/player/previous", params=params)

    async def seek(self, position_ms: int, *, device_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"position_ms": position_ms}
        if device_id:
            params["device_id"] = device_id
        return await self._request("PUT", "/me/player/seek", params=params)

    async def set_volume(
        self, volume_percent: int, *, device_id: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"volume_percent": volume_percent}
        if device_id:
            params["device_id"] = device_id
        return await self._request("PUT", "/me/player/volume", params=params)

    async def add_to_queue(self, uri: str, *, device_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"uri": uri}
        if device_id:
            params["device_id"] = device_id
        return await self._request("POST", "/me/player/queue", params=params)

    async def get_queue(self) -> dict[str, Any]:
        return await self._request("GET", "/me/player/queue")

    # ---- library (Liked Songs) ----

    async def save_tracks_to_library(self, track_ids: list[str]) -> dict[str, Any]:
        # PUT /v1/me/library is the Feb-2026 consolidated endpoint. The legacy
        # PUT /v1/me/tracks now returns 403 Forbidden with no useful message
        # (NOT 404, NOT a deprecation header — Spotify just slams the door).
        # The new endpoint takes `uris` (plural, prefixed) in query string, NOT `ids`
        # in JSON body. Learned the hard way: probed 6 shapes, only this works.
        if not track_ids:
            return {}
        if len(track_ids) > 50:
            raise ValueError(f"save_tracks_to_library: max 50 ids per call, got {len(track_ids)}")
        uris = ",".join(f"spotify:track:{tid}" for tid in track_ids)
        return await self._request("PUT", "/me/library", params={"uris": uris})
