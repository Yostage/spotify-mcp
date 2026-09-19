"""MCP server: tool registration, dispatch, error envelope, stdio loop.

The handlers themselves are module-level async functions so tests can hit
them without spinning up the SDK plumbing. `build_server()` wires them into
a Server instance and `run()` is the stdio entry point invoked by `main()`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from spotify_mcp.auth import AuthorizationError, PKCEFlow
from spotify_mcp.client import AuthenticationError, RateLimitError, SpotifyClient
from spotify_mcp.storage import NoRefreshTokenError
from spotify_mcp.tools import TOOL_DESCRIPTIONS, TOOLS

SERVER_NAME = "spotify-mcp"
SERVER_VERSION = "0.1.0"

ClientProvider = Callable[[], SpotifyClient]


async def handle_list_tools() -> list[types.Tool]:
    """Return the 27 MCP tool descriptors with their pydantic-derived schemas."""
    return [
        types.Tool(
            name=name,
            description=TOOL_DESCRIPTIONS[name],
            inputSchema=schema_cls.model_json_schema(),
        )
        for name, (schema_cls, _handler) in TOOLS.items()
    ]


async def handle_call_tool(
    client: SpotifyClient,
    name: str,
    args: dict[str, Any] | None,
) -> list[types.TextContent]:
    """Dispatch a single tool call. All exceptions become structured error envelopes."""
    args = args or {}
    entry = TOOLS.get(name)
    if entry is None:
        return _error("unknown_tool", f"unknown tool: {name!r}")

    schema_cls, handler = entry
    try:
        inp = schema_cls(**args)
        return await handler(client, inp)
    except NoRefreshTokenError as e:
        return _error(
            "no_refresh_token",
            str(e),
            remediation="Run the auth flow once locally to populate the OS keychain.",
        )
    except AuthenticationError as e:
        return _error("auth", str(e))
    except RateLimitError as e:
        return _error("rate_limited", str(e))
    except AuthorizationError as e:
        return _error("authorization", str(e))
    except Exception as e:
        # Top-level envelope: stdio MCP has no other way to report errors back
        # to Claude Desktop than via TextContent. Catch-all is intentional here.
        return _error(type(e).__name__, str(e))


def _error(code: str, message: str, **extra: str) -> list[types.TextContent]:
    payload: dict[str, Any] = {"error": code, "message": message}
    payload.update(extra)
    return [types.TextContent(type="text", text=json.dumps(payload))]


def build_server(client_provider: ClientProvider) -> Server:
    """Build a Server instance with the list/call handlers wired up."""
    server: Server = Server(SERVER_NAME)

    async def list_handler() -> list[types.Tool]:
        return await handle_list_tools()

    async def call_handler(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        return await handle_call_tool(client_provider(), name, arguments)

    # Explicit decoration form — registers handlers without leaving inner
    # functions appearing unused to static analysis.
    server.list_tools()(list_handler)
    server.call_tool()(call_handler)

    return server


def default_client_provider() -> ClientProvider:
    """Lazy provider: instantiates a SpotifyClient on first request using env vars."""
    holder: dict[str, SpotifyClient] = {}

    def provide() -> SpotifyClient:
        if "client" not in holder:
            client_id = os.environ.get("SPOTIFY_CLIENT_ID")
            if not client_id:
                raise RuntimeError(
                    "SPOTIFY_CLIENT_ID environment variable must be set."
                )
            port = int(os.environ.get("SPOTIFY_CALLBACK_PORT", "8888"))
            holder["client"] = SpotifyClient(
                client_id,
                auth=PKCEFlow(client_id, callback_port=port),
            )
        return holder["client"]

    return provide


async def run() -> None:
    """Stdio entry point — invoked by `spotify_mcp.main()`."""
    server = build_server(default_client_provider())
    init_options = InitializationOptions(
        server_name=SERVER_NAME,
        server_version=SERVER_VERSION,
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options)
