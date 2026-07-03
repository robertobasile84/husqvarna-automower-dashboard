"""Husqvarna Automower → InfluxDB collector.

Keeps an in-memory copy of every mower's ``attributes`` (seeded from REST,
updated live from WebSocket events) and writes a time-series point on every
change. Real-time state (battery, activity, position, cutting height) arrives
over the WebSocket; cumulative statistics are refreshed on the periodic REST
poll.

Configuration is entirely via environment variables (see ``.env.example``).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import signal
from typing import Any

from influxdb_client import Point
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

from errorcodes import error_text
from husqvarna import AutomowerClient

_LOGGER = logging.getLogger("collector")

# Measurement names.
M_STATUS = "automower_status"
M_STATS = "automower_statistics"
M_POSITION = "automower_position"

# Which activity values count as "mowing" / "charging" for the boolean helper
# fields that make Grafana state panels trivial.
MOWING_ACTIVITIES = {"mowing", "leaving"}


def _env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or ""


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> None:
    """Recursively merge ``updates`` into ``base`` in place."""
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


class Collector:
    """Owns the per-mower attribute cache and turns it into InfluxDB points."""

    def __init__(self, write_api, bucket: str, *, write_positions: bool) -> None:
        self._write_api = write_api
        self._bucket = bucket
        self._write_positions = write_positions
        self._state: dict[str, dict[str, Any]] = {}

    # -- Callbacks from AutomowerClient -----------------------------------
    async def on_snapshot(self, mowers: list[dict[str, Any]]) -> None:
        for mower in mowers:
            mower_id = mower["id"]
            self._state[mower_id] = copy.deepcopy(mower.get("attributes", {}))
            await self._write(mower_id)

    async def on_event(self, mower_id: str, event: dict[str, Any]) -> None:
        attrs = self._state.get(mower_id)
        if attrs is None:
            # Event for a mower we have not seen via REST yet; skip until snapshot.
            _LOGGER.debug("Event for unknown mower %s; awaiting snapshot", mower_id)
            return
        self._apply_event(attrs, event)
        await self._write(mower_id)

    # -- Event merge -------------------------------------------------------
    @staticmethod
    def _apply_event(attrs: dict[str, Any], event: dict[str, Any]) -> None:
        """Fold a single WebSocket event into the cached attributes."""
        etype = event.get("type", "")
        payload = event.get("attributes", {})
        if etype == "cuttingHeight-event-v2":
            attrs.setdefault("settings", {})["cuttingHeight"] = payload[
                "cuttingHeight"
            ]["height"]
        elif etype == "headlights-event-v2":
            attrs.setdefault("settings", {}).setdefault("headlight", {})["mode"] = (
                payload["headlights"]["mode"]
            )
        elif etype == "position-event-v2":
            positions = attrs.setdefault("positions", [])
            positions.insert(0, payload["position"])
            del positions[50:]  # API keeps at most the 50 most recent
        else:
            _deep_merge(attrs, payload)

    # -- Point building ----------------------------------------------------
    async def _write(self, mower_id: str) -> None:
        attrs = self._state[mower_id]
        points: list[Point] = []

        system = attrs.get("system", {})
        name = system.get("name") or mower_id
        model = system.get("model", "unknown")

        def tag(point: Point) -> Point:
            return (
                point.tag("mower", name).tag("mower_id", mower_id).tag("model", model)
            )

        # --- status ---
        mower = attrs.get("mower", {})
        battery = attrs.get("battery", {})
        planner = attrs.get("planner", {})
        settings = attrs.get("settings", {})
        metadata = attrs.get("metadata", {})

        activity = str(mower.get("activity", "unknown")).lower()
        state = str(mower.get("state", "unknown")).lower()
        error_code = int(mower.get("errorCode", 0) or 0)
        connected = bool(metadata.get("connected", False))

        status = tag(Point(M_STATUS))
        status.field("battery_percent", int(battery.get("batteryPercent", 0) or 0))
        status.field("activity", activity)
        status.field("state", state)
        status.field("mode", str(mower.get("mode", "unknown")).lower())
        status.field("error_code", error_code)
        status.field("error_text", error_text(error_code))
        status.field("restricted_reason", str(planner.get("restrictedReason", "")))
        status.field("connected", int(connected))
        status.field("is_online", int(connected))
        status.field("is_mowing", int(activity in MOWING_ACTIVITIES))
        status.field("is_charging", int(activity == "charging"))
        status.field(
            "is_error", int(state in {"error", "fatal_error", "error_at_power_up"})
        )
        if settings.get("cuttingHeight") is not None:
            status.field("cutting_height", int(settings["cuttingHeight"]))
        next_start = planner.get("nextStartTimestamp")
        if next_start:  # epoch milliseconds; 0 means "no scheduled start"
            status.field("next_start_epoch", int(next_start) // 1000)
        points.append(status)

        # --- statistics (present on REST snapshots) ---
        stats = attrs.get("statistics", {})
        if stats:
            sp = tag(Point(M_STATS))
            for src, dst in _STATISTIC_FIELDS.items():
                value = stats.get(src)
                if value is not None:
                    sp.field(dst, int(value))
            points.append(sp)

        # --- position ---
        if self._write_positions:
            positions = attrs.get("positions") or []
            if positions:
                latest = positions[0]
                lat, lon = latest.get("latitude"), latest.get("longitude")
                if lat is not None and lon is not None:
                    pp = tag(Point(M_POSITION))
                    pp.field("latitude", float(lat))
                    pp.field("longitude", float(lon))
                    points.append(pp)

        try:
            await self._write_api.write(bucket=self._bucket, record=points)
            _LOGGER.debug("Wrote %d point(s) for %s", len(points), name)
        except Exception:  # noqa: BLE001 - never let a write kill the collector
            _LOGGER.exception("Failed writing points for %s", name)


_STATISTIC_FIELDS = {
    "cuttingBladeUsageTime": "cutting_blade_usage_time",
    "numberOfChargingCycles": "number_of_charging_cycles",
    "numberOfCollisions": "number_of_collisions",
    "totalChargingTime": "total_charging_time",
    "totalCuttingTime": "total_cutting_time",
    "totalDriveDistance": "total_drive_distance",
    "totalRunningTime": "total_running_time",
    "totalSearchingTime": "total_searching_time",
    "downTime": "downtime",
    "upTime": "uptime",
}


async def _wait_for_influx(client: InfluxDBClientAsync) -> None:
    """Block until InfluxDB answers a ping (it may still be initialising)."""
    for attempt in range(1, 31):
        try:
            if await client.ping():
                return
        except Exception as err:  # noqa: BLE001
            _LOGGER.info("Waiting for InfluxDB (%d/30): %s", attempt, err)
        await asyncio.sleep(2)
    raise SystemExit("InfluxDB did not become ready in time")


async def main() -> None:
    logging.basicConfig(
        level=getattr(logging, _env("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    client_id = _env("HUSQVARNA_CLIENT_ID")
    client_secret = _env("HUSQVARNA_CLIENT_SECRET")
    demo_flag = _env("DEMO_MODE").lower() in ("1", "true", "yes")
    demo = demo_flag or not (client_id and client_secret)
    influx_url = _env("INFLUXDB_URL", "http://influxdb:8086")
    influx_token = _env("INFLUXDB_TOKEN", required=True)
    influx_org = _env("INFLUXDB_ORG", "automower")
    influx_bucket = _env("INFLUXDB_BUCKET", "automower")
    poll_interval = int(_env("REST_POLL_INTERVAL", "3600"))
    write_positions = _env("WRITE_POSITIONS", "true").lower() != "false"

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - Windows dev
            pass

    async with InfluxDBClientAsync(
        url=influx_url, token=influx_token, org=influx_org
    ) as influx:
        await _wait_for_influx(influx)
        collector = Collector(
            influx.write_api(), influx_bucket, write_positions=write_positions
        )

        if demo:
            if demo_flag:
                _LOGGER.warning("DEMO_MODE enabled — using synthetic data")
            else:
                _LOGGER.warning(
                    "No HUSQVARNA_CLIENT_ID/SECRET set — falling back to DEMO mode"
                )
            from simulator import Simulator

            run_task = asyncio.create_task(Simulator(collector).run())
        else:
            mower = AutomowerClient(
                client_id, client_secret, rest_poll_interval=poll_interval
            )
            mower.on_snapshot = collector.on_snapshot
            mower.on_event = collector.on_event
            run_task = asyncio.create_task(mower.run())

        _LOGGER.info(
            "Collector started (bucket=%s, poll=%ss, demo=%s)",
            influx_bucket,
            poll_interval,
            demo,
        )

        await asyncio.wait(
            {run_task, asyncio.create_task(stop.wait())},
            return_when=asyncio.FIRST_COMPLETED,
        )
        _LOGGER.info("Shutting down")
        run_task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
