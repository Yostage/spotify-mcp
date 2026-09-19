---
name: spotify-playlist
description: "Use when the user wants to MANAGE their Spotify playlists: create a new one, list theirs, view its tracks, rename, change description or visibility, add tracks, remove tracks, reorder, or trim. Covers requests like 'add this song to my Outlaw Country Gothic playlist', 'create a new playlist called Late Night Drives', 'show me my playlists', 'rename X to Y', 'remove the last 5 tracks from Z', 'put the slow songs at the end of W'. Requires the spotify-mcp server (mcp__spotify__*)."
allowed-tools:
  - mcp__spotify__*
---

# Spotify Playlist Curation

You're modifying persistent, user-visible state. Confirm intent before destructive operations.

## Common requests

### "Add track X to playlist Y"
1. `mcp__spotify__list_my_playlists(limit=50)` — find Y by name (case-insensitive). If multiple matches, ASK which one.
2. `mcp__spotify__search_tracks(query=X, limit=3)` — pick the best match.
3. `mcp__spotify__add_tracks_to_playlist(playlist_id=Y.id, uris=[X.uri])`.
4. Confirm: "Added '<track>' to <playlist> (snapshot <snapshot_id>)."

### "Create a playlist called X"
1. `mcp__spotify__create_playlist(name=X)`.
2. **Important default**: `public=False` (private). If the user wants it public, pass `public=True` explicitly. This default deliberately diverges from Spotify's API (which defaults to public) — an AI tool shouldn't accidentally publish to a user's profile.
3. Confirm: "Created '<name>' (private). URI: <uri>."

### "Show my playlists"
- `mcp__spotify__list_my_playlists(limit=50)`. Render as a clean list:
  ```
  - <name> (<total_tracks> tracks, <public|private>)
  ```
- The `limit` caps at 50. If the user clearly has more, raise the limit (max 50 per call) and note the cap.

### "What's in playlist Y?"
- `mcp__spotify__get_playlist(playlist_id=...)` — name, description, total_tracks, owner (no tracks).
- `mcp__spotify__get_playlist_items(playlist_id=..., limit=100, offset=0)` — the tracks, in order, each with a 0-based `position`. Loop on `offset` while `has_more` is true. Render as `<position+1>. <name> — <artists> (<m:ss>)`.

### "Reorder / trim playlist Y" (e.g. "move the Irish songs to the end", "cut it to 40 tracks")
1. `get_playlist_items` — read the current order (paginate if > 100).
2. Work out the target list of URIs.
3. If the target is ≤ 100 tracks: `mcp__spotify__replace_playlist_items(playlist_id, uris=[...])` — ONE atomic PUT replaces the entire contents in that order. Show the user the before/after summary first; this is the one call that can wipe a playlist (an empty `uris` clears it).
4. If the target is > 100 tracks or the change is a single block move: `mcp__spotify__reorder_playlist_items(playlist_id, range_start, insert_before, range_length)` — moves `range_length` items starting at `range_start` to sit before `insert_before` (both 0-based, positions as they are BEFORE the move). Pass the `snapshot_id` from a preceding call if you're doing several moves in a row.
5. Re-read with `get_playlist_items` and confirm the new order to the user.

### "Remove track X from playlist Y"
1. Find Y's id via `list_my_playlists`.
2. Search for X's URI via `search_tracks`.
3. `mcp__spotify__remove_tracks_from_playlist(playlist_id=Y.id, uris=[X.uri])`.
4. **Caveat**: this removes ALL occurrences of that URI. If the user wants to remove ONE specific position-based occurrence (e.g., "the second time I added it"), the current tool doesn't support that — say so plainly.

### "Rename / update playlist Y"
- `mcp__spotify__change_playlist_details(playlist_id, name=..., description=..., public=...)` — pass ONLY the fields that change.

## Failure modes

- **Playlist not found** in `list_my_playlists` — limit=50 by default; if their library is larger, paginate or note the cap.
- **`error: no_refresh_token`** — user needs to run `spotify-mcp auth`.

## Style

When you add or remove tracks, name BOTH the track AND the playlist AND the new count in one line:
> "Added 'Pancho and Lefty' to Outlaw Country Gothic (now 12 tracks)."

Don't paste the snapshot_id at the user unless they asked for it.
