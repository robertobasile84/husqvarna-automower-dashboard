"""Minimal async client for the Husqvarna Automower Connect API.

Implements only what a dashboard collector needs, with no third-party Husqvarna
SDK:

* OAuth2 *client-credentials* token handling, with automatic refresh.
* A REST snapshot of every mower (``GET /mowers``).
* A resilient WebSocket subscription for real-time events, with app-level
  keep-alives, token-aware reconnects before the server's ~2h cap, and
  exponential backoff on failure.

Endpoints, headers and the ``*-event-v2`` WebSocket message names come from
Husqvarna's developer portal (https://developer.husqvarnagroup.cloud/apis).
The API is a JSON:API service: ``GET /mowers`` returns ``{"data": [ {"id", "type",
"attributes": {...}}, ... ]}`` and each WebSocket event is ``{"id", "type",
"attributes": {...}}`` carrying only the changed slice of a mower's attributes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
from aiohttp import WSServerHandshakeError

_LOGGER = logging.getLogger("husqvarna")

TOKEN_URL = "https://api.authentication.husqvarnagroup.dev/v1/oauth2/token"
API_BASE = "https://api.amc.husqvarna.dev/v1"
WS_URL = "wss://ws.openapi.husqvarna.dev/v1"

# WebSocket event names (v2) that carry mower attribute changes.
EVENT_TYPES = frozenset(
    {
        "battery-event-v2",
        "mower-event-v2",
        "planner-event-v2",
        "cuttingHeight-event-v2",
        "headlights-event-v2",
        "position-event-v2",
        "calendar-event-v2",
        "message-event-v2",
    }
)

# Placeholder id the API uses for a mower slot with no real device behind it.
INVALID_MOWER_ID = "0-0"

# Cycle the socket well before the server-side ~2h cap.
WS_MAX_LIFETIME = 110 * 60
KEEPALIVE_INTERVAL = 60
TOKEN_SKEW = 60

# Callback signatures. Both are async so handlers can write to InfluxDB inline.
SnapshotCb = Callable[[list[dict[str, Any]]], Awaitable[None]]
EventCb = Callable[[str, dict[str, Any]], Awaitable[None]]


class AutomowerClient:
    """Talks to the Automower Connect API and drives two async callbacks.

    * ``on_snapshot(mowers)`` fires with the full REST ``data`` list on connect
      and on every periodic poll.
    * ``on_event(mower_id, event)`` fires for each real-time WebSocket event.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        rest_poll_interval: int = 3600,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._rest_poll_interval = rest_poll_interval
        self._session: aiohttp.ClientSession | None = None
        self._token: dict[str, Any] = {}
        self.on_snapshot: SnapshotCb | None = None
        self.on_event: EventCb | None = None

    # -- OAuth2 ------------------------------------------------------------
    async def _get_token(self) -> str:
        """Return a cached access token, fetching a fresh one when near expiry."""
        if self._token and self._token["expires_at"] > time.time() + TOKEN_SKEW:
            return self._token["access_token"]
        assert self._session is not None
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        async with self._session.post(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            body = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"token request failed ({resp.status}): {body}")
        body["expires_at"] = time.time() + int(body.get("expires_in", 3600))
        self._token = body
        _LOGGER.info("Obtained access token (valid %ss)", body.get("expires_in"))
        return body["access_token"]

    async def _rest_headers(self) -> dict[str, str]:
        token = await self._get_token()
        # X-Api-Key is the application key, i.e. the OAuth2 client id.
        return {
            "Authorization": f"Bearer {token}",
            "Authorization-Provider": "husqvarna",
            "X-Api-Key": self._client_id,
            "Content-Type": "application/vnd.api+json",
        }

    # -- REST --------------------------------------------------------------
    async def get_mowers(self) -> list[dict[str, Any]]:
        """Return the ``data`` array from ``GET /mowers``."""
        assert self._session is not None
        headers = await self._rest_headers()
        async with self._session.get(f"{API_BASE}/mowers", headers=headers) as resp:
            body = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"GET /mowers failed ({resp.status}): {body}")
        return [m for m in body.get("data", []) if m.get("id") != INVALID_MOWER_ID]

    # -- Run loop ----------------------------------------------------------
    async def run(self) -> None:
        """Run forever. REST polling and the WebSocket run independently, so a
        WebSocket that refuses to connect never stops REST data from flowing."""
        async with aiohttp.ClientSession() as session:
            self._session = session
            await self._snapshot()  # initial state; surfaces bad credentials early
            await asyncio.gather(self._rest_forever(), self._ws_forever())

    async def _rest_forever(self) -> None:
        """Poll REST at the configured interval, forever."""
        while True:
            await asyncio.sleep(self._rest_poll_interval)
            try:
                await self._snapshot()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Periodic REST poll failed")

    async def _ws_forever(self) -> None:
        """Maintain the real-time WebSocket, reconnecting with backoff. Best
        effort: if it never connects, REST polling still carries the data."""
        backoff = 5
        while True:
            try:
                await self._ws_session()
                backoff = 5  # a clean lifecycle resets the backoff
            except asyncio.CancelledError:
                raise
            except WSServerHandshakeError as err:
                _LOGGER.warning(
                    "WebSocket handshake refused (HTTP %s). Real-time updates are "
                    "off; REST polling continues. This is usually an application-"
                    "key/WebSocket-compatibility issue on the Husqvarna portal, not "
                    "a bad credential. Retrying in %ss.",
                    err.status,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("WebSocket error; reconnecting in %ss", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

    async def _ws_session(self) -> None:
        """One WebSocket lifecycle: connect and listen until it needs cycling."""
        token = await self._get_token()
        assert self._session is not None
        async with self._session.ws_connect(
            WS_URL,
            headers={"Authorization": f"Bearer {token}"},
            heartbeat=KEEPALIVE_INTERVAL,
        ) as ws:
            _LOGGER.info("WebSocket connected")
            keepalive = asyncio.create_task(self._keepalive(ws))
            deadline = time.time() + WS_MAX_LIFETIME
            try:
                while True:
                    timeout = max(1.0, deadline - time.time())
                    try:
                        msg = await ws.receive(timeout=timeout)
                    except TimeoutError:
                        _LOGGER.info("WebSocket lifetime reached; cycling connection")
                        return
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_ws_text(msg.data)
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        _LOGGER.warning("WebSocket closed (%s); reconnecting", msg.type)
                        return
            finally:
                keepalive.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await keepalive

    async def _handle_ws_text(self, raw: str) -> None:
        """Dispatch a text frame: event, keep-alive pong, or connection banner."""
        if not raw or not raw.strip():
            return  # empty frame == keep-alive pong
        try:
            msg = _json_loads(raw)
        except ValueError:
            _LOGGER.debug("Ignoring non-JSON WebSocket frame: %r", raw[:200])
            return
        event_type = msg.get("type")
        if event_type not in EVENT_TYPES:
            # "ready"/"connectionId" banner or an unknown event; nothing to store.
            return
        mower_id = msg.get("id")
        if not mower_id or mower_id == INVALID_MOWER_ID:
            return
        if self.on_event is not None:
            await self.on_event(mower_id, msg)

    async def _keepalive(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Send an empty text frame periodically to keep the socket alive."""
        while not ws.closed:
            await asyncio.sleep(KEEPALIVE_INTERVAL)
            try:
                await ws.send_str("")
            except (ConnectionError, aiohttp.ClientError):
                return

    async def _snapshot(self) -> None:
        mowers = await self.get_mowers()
        _LOGGER.debug("REST snapshot: %d mower(s)", len(mowers))
        if self.on_snapshot is not None:
            await self.on_snapshot(mowers)


try:  # orjson is pulled in transitively and is faster; fall back to stdlib.
    import orjson

    def _json_loads(raw: str) -> dict[str, Any]:
        return orjson.loads(raw)

except ImportError:  # pragma: no cover
    import json

    def _json_loads(raw: str) -> dict[str, Any]:
        return json.loads(raw)
