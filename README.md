# spotify-mcp

An MCP server for Spotify — **27 flat tools**, **OAuth 2.0 PKCE** (no `client_secret`), OS-keychain token storage, targeting the **post-February-2026 Spotify Web API surface**.

Built with `httpx` + `mcp` + `pydantic` + `keyring`. No `spotipy`. No `.cache` files in your CWD.

## Status

🚧 **Pre-release.** APIs and tool names may change before v1.

## Features

- **27 flat MCP tools** — one verb per tool (`search_tracks`, `start_playback`, `add_to_queue`, ...). No action-dispatched mega-tools.
- **OAuth 2.0 Authorization Code + PKCE** (RFC 7636). No `client_secret` needed — public clients shouldn't ship secrets.
- **Refresh tokens in the OS keychain** via `keyring`. No plaintext on disk, no `.cache` files next to the script.
- **Auto-refresh on 401**, single retry. **Single retry on 429** honoring `Retry-After`. Never an unbounded loop.
- **Post-Feb-2026 endpoints only**: `/me/playlists`, `/playlists/{id}/items`. No deprecated `audio-features`, `recommendations`, `related-artists`.

## Install

### Via `uvx` (recommended)

```bash
uvx --from git+https://github.com/e01n0/spotify-mcp spotify-mcp --help
```

### Local development

```bash
git clone https://github.com/e01n0/spotify-mcp.git
cd spotify-mcp
uv sync --dev
uv run spotify-mcp --help
```

## Spotify App Setup

1. Go to <https://developer.spotify.com/dashboard> and create a new app.
2. Choose **"Web API"** as the platform. PKCE flows do not require a client secret.
3. Under **Redirect URIs**, add: `http://127.0.0.1:8888/callback`
   (Spotify requires the literal `127.0.0.1` — `localhost` will be rejected.)
   If you set `SPOTIFY_CALLBACK_PORT` to a different port, register that port instead.
4. Copy the **Client ID**. You'll set it as `SPOTIFY_CLIENT_ID`.

## First-run Auth

Before Claude Desktop can use the server, run the one-shot auth flow once:

```bash
export SPOTIFY_CLIENT_ID="your-client-id-here"
uvx --from git+https://github.com/e01n0/spotify-mcp spotify-mcp auth
```

This opens your browser, you approve the consent screen, the redirect lands on the local loopback server, and the refresh token gets stored in your OS keychain. You only do this once per `(machine, client_id)` pair — subsequent MCP tool calls auto-refresh from the stored token.

## Claude Desktop Config

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or the equivalent on your platform.

### Via `uvx`

```json
{
  "mcpServers": {
    "spotify": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/e01n0/spotify-mcp", "spotify-mcp"],
      "env": {
        "SPOTIFY_CLIENT_ID": "your-client-id-here"
      }
    }
  }
}
```

### Via local checkout

```json
{
  "mcpServers": {
    "spotify": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/spotify-mcp", "run", "spotify-mcp"],
      "env": {
        "SPOTIFY_CLIENT_ID": "your-client-id-here"
      }
    }
  }
}
```

Restart Claude Desktop after editing.

## Environment Variables

| Variable                | Required | Default | Purpose                                              |
|-------------------------|----------|---------|------------------------------------------------------|
| `SPOTIFY_CLIENT_ID`     | yes      | —       | Your Spotify app client ID                           |
| `SPOTIFY_CALLBACK_PORT` | no       | `8888`  | Local loopback port for PKCE redirect — must match the port in your Spotify app's redirect URI |

## OAuth Scopes Requested

The auth flow requests these scopes on the consent screen:

- `user-read-playback-state` · `user-modify-playback-state` · `user-read-currently-playing`
- `playlist-read-private` · `playlist-read-collaborative`
- `playlist-modify-private` · `playlist-modify-public`
- `user-library-read` *(future-proofing — no v1 tool requires it yet)*

`user-library-modify` is **not** requested — out of scope for v1.

## Available Tools (27)

**Search (4):** `search_tracks`, `search_albums`, `search_artists`, `search_playlists`

**Get info (4):** `get_track`, `get_album`, `get_artist` *(also returns the artist's albums; top-tracks endpoint removed Feb-2026)*, `get_playlist`

**Playlist (8):** `create_playlist` *(defaults to `public=false`)*, `add_tracks_to_playlist`, `remove_tracks_from_playlist`, `list_my_playlists`, `change_playlist_details`, `get_playlist_items` *(ordered, paginated, 0-based positions)*, `replace_playlist_items` *(atomic reorder/trim: PUT the full URI list, max 100)*, `reorder_playlist_items` *(move a contiguous block; optional `snapshot_id` guard)*

**Playback (10):** `get_current_playback`, `start_playback` *(routes track URIs to `uris`, album/playlist/artist URIs to `context_uri`)*, `pause_playback`, `next_track`, `previous_track`, `seek`, `set_volume`, `list_devices`, `add_to_queue`, `get_queue`

**Library (1):** `save_tracks_to_library` *(saves up to 50 tracks to Liked Songs per call; requires `user-library-modify` scope)*

## Troubleshooting

**`No refresh token stored for client_id=...`** — You haven't run `spotify-mcp auth` yet, or you ran it with a different `SPOTIFY_CLIENT_ID`. Run the auth flow again with the matching client ID.

**Browser doesn't open / hangs on the callback** — Confirm the redirect URI in your Spotify dashboard matches **exactly** `http://127.0.0.1:8888/callback` (not `localhost`, not `https`). If you changed `SPOTIFY_CALLBACK_PORT`, the dashboard must reflect the new port too.

**`Address already in use` on port 8888** — Another process is bound to the port. Set `SPOTIFY_CALLBACK_PORT=8889` (and update the redirect URI to match), or kill the other process.

**`Still 401 after refresh`** — The stored refresh token was invalidated server-side (revoked in the Spotify dashboard, or rotated past its grace window). Re-run `spotify-mcp auth`.

**Tool fails with `rate_limited`** — Spotify's `Retry-After` window has already been honored once. The tool gives up after one retry to avoid freezing the MCP session. Retry the tool call shortly.

**Keyring backend missing on headless Linux** — Install a backend (e.g. `python-keyring/keyrings.alt`) or use the Secret Service via `gnome-keyring-daemon --start --components=secrets`. The server intentionally refuses to fall back to plaintext-on-disk.

## Skills

The repo ships three workflow skills under [`skills/`](skills/) that drive these tools from natural-language requests in Claude:

- **`spotify-playback`** — play/pause/skip/queue/volume/seek/devices
- **`spotify-playlist`** — create, list, add/remove tracks, rename
- **`spotify-mood-mix`** — generate playlists from a vibe description

Install with:

```bash
cp -r skills/spotify-* ~/.claude/skills/
```

See [`skills/README.md`](skills/README.md) for details.

## Architecture

Seven modules, no cycles:

```
server.py  ->  tools.py  ->  client.py  ->  auth.py     ->  storage.py
                          ->  models.py
tools.py   ->  models.py
```

- **`auth.py`** — PKCE primitives + loopback callback HTTP server
- **`storage.py`** — keyring wrapper, keyed by client_id
- **`client.py`** — httpx wrapper with refresh-on-401, Retry-After-on-429
- **`models.py`** — 23 pydantic input schemas + 5 response DTOs
- **`tools.py`** — 23 tool functions over `SpotifyClient`, return `list[TextContent]`
- **`server.py`** — MCP `Server`, tool registration, error envelope, stdio loop
- **`__init__.py`** — `main()` dispatching `spotify-mcp` and `spotify-mcp auth`

## Acknowledgments

Inspired by [varunneal/spotify-mcp](https://github.com/varunneal/spotify-mcp). This is a from-scratch rewrite for the post-Feb-2026 API and `uvx`-friendly auth storage — no shared code, but the original made the design space clear.

## License

[MIT](LICENSE)
