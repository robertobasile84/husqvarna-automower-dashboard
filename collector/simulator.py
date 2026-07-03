"""Demo-mode data simulator.

When no Husqvarna credentials are configured, this drives the same
``Collector.on_snapshot`` path with realistic synthetic data so the dashboard
can be launched and explored end-to-end without an account or a mower.

It models a single mower cycling through mow → return → charge, with a draining
and recharging battery, a wandering GPS position, and ever-growing lifetime
statistics.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from typing import Any

_LOGGER = logging.getLogger("simulator")


class Simulator:
    def __init__(self, collector: Any, *, tick: float = 5.0) -> None:
        self._collector = collector
        self._tick = tick
        self._name = os.getenv("DEMO_MOWER_NAME", "Demo Mower")
        self._model = os.getenv("DEMO_MOWER_MODEL", "Automower 430X (demo)")
        self._center = (
            float(os.getenv("DEMO_LAT", "47.3769")),
            float(os.getenv("DEMO_LON", "8.5417")),
        )
        self._lat, self._lon = self._center
        self._battery = 85.0
        self._activity = "mowing"
        self._state = "in_operation"
        self._charged_this_cycle = False
        self._stats = {
            "cuttingBladeUsageTime": 320_000,
            "numberOfChargingCycles": 240,
            "numberOfCollisions": 1_500,
            "totalChargingTime": 900_000,
            "totalCuttingTime": 1_200_000,
            "totalDriveDistance": 480_000,
            "totalRunningTime": 1_400_000,
            "totalSearchingTime": 120_000,
        }

    async def run(self) -> None:
        _LOGGER.warning(
            "DEMO MODE: emitting synthetic data (no Husqvarna connection). "
            "Set HUSQVARNA_CLIENT_ID/SECRET for real data."
        )
        while True:
            self._step()
            await self._collector.on_snapshot(
                [{"id": "demo-0", "attributes": self._attributes()}]
            )
            await asyncio.sleep(self._tick)

    def _step(self) -> None:
        t = int(self._tick)
        if self._activity in ("mowing", "leaving"):
            self._battery -= random.uniform(0.3, 0.7)
            self._wander(0.00004)
            self._stats["totalRunningTime"] += t
            self._stats["totalCuttingTime"] += t
            self._stats["totalDriveDistance"] += max(1, int(t * 0.3))
            if random.random() < 0.02:
                self._stats["numberOfCollisions"] += 1
            self._activity = "mowing"
            if self._battery <= 20:
                self._activity, self._state = "going_home", "in_operation"
        elif self._activity == "going_home":
            # Ease back toward the charging station.
            self._lat += (self._center[0] - self._lat) * 0.3
            self._lon += (self._center[1] - self._lon) * 0.3
            self._stats["totalRunningTime"] += t
            self._stats["totalSearchingTime"] += t
            self._stats["totalDriveDistance"] += max(1, int(t * 0.3))
            if self._near_center():
                self._lat, self._lon = self._center
                self._activity, self._state = "charging", "charging"
                self._charged_this_cycle = False
        elif self._activity == "charging":
            if not self._charged_this_cycle:
                self._stats["numberOfChargingCycles"] += 1
                self._charged_this_cycle = True
            self._battery += random.uniform(1.5, 2.5)
            self._stats["totalChargingTime"] += t
            if self._battery >= 100:
                self._battery = 100.0
                self._activity, self._state = "leaving", "in_operation"
        self._battery = max(0.0, min(100.0, self._battery))

    def _wander(self, span: float) -> None:
        self._lat += random.uniform(-1, 1) * span
        self._lon += random.uniform(-1, 1) * span
        # Keep it roughly within the working area around the station.
        self._lat = max(
            self._center[0] - 0.0004, min(self._center[0] + 0.0004, self._lat)
        )
        self._lon = max(
            self._center[1] - 0.0004, min(self._center[1] + 0.0004, self._lon)
        )

    def _near_center(self) -> bool:
        return (
            abs(self._lat - self._center[0]) < 0.00005
            and abs(self._lon - self._center[1]) < 0.00005
        )

    def _attributes(self) -> dict[str, Any]:
        return {
            "system": {
                "name": self._name,
                "model": self._model,
                "serialNumber": "000000000",
            },
            "battery": {"batteryPercent": int(round(self._battery))},
            "mower": {
                "mode": "main_area",
                "activity": self._activity,
                "state": self._state,
                "errorCode": 0,
                "inactiveReason": "none",
            },
            "planner": {
                "nextStartTimestamp": int((time.time() + 3600) * 1000),
                "restrictedReason": "week_schedule",
            },
            "metadata": {"connected": True, "statusTimestamp": int(time.time() * 1000)},
            "settings": {"cuttingHeight": 5, "headlight": {"mode": "evening_only"}},
            "statistics": dict(self._stats),
            "positions": [{"latitude": self._lat, "longitude": self._lon}],
        }
