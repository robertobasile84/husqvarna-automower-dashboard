"""Standalone connectivity probe for the Automower Connect client.

Exercises just the client library — no InfluxDB, no Docker. Use it to confirm
your Application key/secret work and to see the raw data your mower reports.

    # from the collector/ directory, with uv:
    HUSQVARNA_CLIENT_ID=...  HUSQVARNA_CLIENT_SECRET=...  uv run python probe.py

Options:
    --rest-only         Fetch one REST snapshot and exit (fastest check).
    --seconds N         Listen for N seconds of WebSocket events (default 120).
                        Use 0 to listen until Ctrl-C.

You can also pass credentials as flags instead of env vars:
    uv run python probe.py --client-id XXX --client-secret YYY
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timezone

from husqvarna import AutomowerClient


def _fmt_epoch_ms(ms: int | None) -> str:
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def _print_snapshot(mowers: list[dict]) -> None:
    print(f"\n=== REST snapshot: {len(mowers)} mower(s) @ {datetime.now():%H:%M:%S} ===")
    for m in mowers:
        a = m.get("attributes", {})
        system = a.get("system", {})
        mower = a.get("mower", {})
        battery = a.get("battery", {})
        planner = a.get("planner", {})
        positions = a.get("positions", []) or []
        stats = a.get("statistics", {})
        connected = a.get("metadata", {}).get("connected")
        print(f"  {system.get('name', m.get('id'))}  ({system.get('model', '?')})")
        print(f"    id           {m.get('id')}")
        print(f"    connected    {connected}")
        print(f"    battery      {battery.get('batteryPercent')}%")
        print(f"    activity     {mower.get('activity')}")
        print(f"    state        {mower.get('state')}   mode={mower.get('mode')}")
        print(f"    errorCode    {mower.get('errorCode')}")
        print(f"    next start   {_fmt_epoch_ms(planner.get('nextStartTimestamp'))}")
        print(f"    positions    {len(positions)} point(s)"
              + (f"  latest={positions[0]}" if positions else ""))
        if stats:
            hours = lambda s: f"{(s or 0) / 3600:.1f}h"
            print(f"    stats        cutting={hours(stats.get('totalCuttingTime'))}"
                  f"  running={hours(stats.get('totalRunningTime'))}"
                  f"  charges={stats.get('numberOfChargingCycles')}"
                  f"  collisions={stats.get('numberOfCollisions')}")


def _print_event(mower_id: str, event: dict) -> None:
    etype = event.get("type")
    attrs = event.get("attributes", {})
    print(f"  [event] {datetime.now():%H:%M:%S}  {etype:22} {mower_id}  {attrs}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", default=os.getenv("HUSQVARNA_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.getenv("HUSQVARNA_CLIENT_SECRET"))
    parser.add_argument("--rest-only", action="store_true")
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()

    # Surface the client's own INFO logs (e.g. "WebSocket connected") so a
    # successful handshake is visible, not just failures.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.client_id or not args.client_secret:
        parser.error(
            "Provide credentials via HUSQVARNA_CLIENT_ID/HUSQVARNA_CLIENT_SECRET "
            "env vars or --client-id/--client-secret flags."
        )

    first_snapshot = asyncio.Event()

    async def on_snapshot(mowers: list[dict]) -> None:
        _print_snapshot(mowers)
        first_snapshot.set()

    async def on_event(mower_id: str, event: dict) -> None:
        _print_event(mower_id, event)

    client = AutomowerClient(
        args.client_id, args.client_secret, rest_poll_interval=10**9
    )
    client.on_snapshot = on_snapshot
    client.on_event = on_event

    print("Connecting to Husqvarna Automower Connect API ...")
    run_task = asyncio.create_task(client.run())

    try:
        # Wait for the first REST snapshot (proves auth + REST work).
        await asyncio.wait_for(first_snapshot.wait(), timeout=30)
    except asyncio.TimeoutError:
        print("\n!! No snapshot within 30s — check credentials / API access.")
        run_task.cancel()
        return

    if args.rest_only:
        print("\nREST snapshot OK — exiting (--rest-only).")
        run_task.cancel()
        return

    print(
        f"\nListening for WebSocket events "
        f"({'until Ctrl-C' if args.seconds == 0 else f'{args.seconds}s'}) ...\n"
        "Note: the mower batches events to save battery — they arrive roughly "
        "every 15 minutes, so short listens may see nothing. Use --seconds 0 and "
        "wait, or trigger a change from the app.\n"
    )
    try:
        if args.seconds == 0:
            await run_task
        else:
            await asyncio.sleep(args.seconds)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        run_task.cancel()
        print("\nDone.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
