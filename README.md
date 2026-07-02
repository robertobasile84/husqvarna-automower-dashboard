# Automower Dashboard

Self-hosted **historic + real-time dashboard** for a Husqvarna Automower, built
on the official [Automower Connect API](https://developer.husqvarnagroup.cloud/apis).
No Home Assistant, no third-party Husqvarna SDK — just a small Python collector,
InfluxDB, and Grafana in one Docker Compose stack.

All three images are multi-arch (amd64 / arm64) and the collector is pure
Python, so **this runs anywhere `docker compose` runs** — a Raspberry Pi, a NAS,
or a homelab server.

```
┌────────────┐   WebSocket (real-time)     ┌──────────┐        ┌─────────┐
│  Husqvarna │   + REST poll (statistics)  │ collector│  write │ InfluxDB│
│ Connect API│ ──────────────────────────► │ (Python) │ ─────► │  (TSDB) │
└────────────┘                             └──────────┘        └────┬────┘
                                                                    │ Flux
                                                               ┌────▼────┐
                                                               │ Grafana │
                                                               └─────────┘
```

## What you get

- **Real-time** battery %, activity, state, mode, cutting height, online status,
  and last error (as readable text, not just a code) — pushed over the WebSocket.
- **GPS position** map (the Connect API returns the last 50 positions for
  GPS-assisted models; the collector stores each update to build a track).
- **Historic** statistics: total cutting / running / charging / searching time,
  blade usage, charging cycles, collisions, drive distance — with trend charts.
- A provisioned Grafana dashboard (as code) and InfluxDB datasource — nothing to
  click to set up; it appears on first boot.

## Requirements

Just **Docker + Docker Compose v2** on the host — nothing else. Works the same on:

- **Windows** — Docker Desktop
- **macOS** — Docker Desktop or OrbStack
- **Linux** — Docker Engine + the `docker compose` plugin

The container is Linux regardless of host OS, and the image is multi-arch, so an
Apple-silicon Mac, an x86 PC, and an ARM box all run the identical stack.

## Try it in 30 seconds (demo mode)

No Husqvarna account, no mower, no config needed — see the dashboard populated
with realistic synthetic data:

```bash
git clone https://github.com/robertobasile84/husqvarna-automower-dashboard
cd husqvarna-automower-dashboard
docker compose up -d --build
```

Open **http://localhost:3005** → log in `admin` / `admin` → the **Automower**
dashboard is pre-loaded and filling in. (Those default credentials come from the
compose file and are for local testing only.)

## Run it for real

1. A Husqvarna Automower with a **Connect** module, already paired to your
   account in the Automower Connect mobile app.
2. An **Application** on the [Husqvarna Developer Portal](https://developer.husqvarnagroup.cloud/apis)
   with **both** the *Authentication API* and the *Automower Connect API*
   connected. From it you need the **Application key** (`client_id`) and the
   **Application secret** (`client_secret`, under *Show more*).

   > The collector uses the OAuth2 **client-credentials** grant, tied to your own
   > account — so no interactive login/redirect is needed. An existing
   > application (e.g. one you already use for Home Assistant) works fine.

```bash
cp .env.example .env
# edit .env: paste your Application key + secret.
# For anything beyond local testing, also set your own INFLUXDB_TOKEN,
# INFLUXDB_PASSWORD and GRAFANA_PASSWORD (a random token: openssl rand -hex 32).

docker compose up -d --build
```

With credentials present the collector connects to the real API instead of the
simulator. Open Grafana at **http://localhost:3005**; InfluxDB's own UI is at
**http://localhost:8086** for poking at raw data.

Data accumulates from the moment the collector starts; the statistics counters
are cumulative lifetime totals reported by the mower, so the trend panels get
more useful over days and weeks.

> **Windows note:** the commands above are shell-agnostic. In PowerShell, use
> `Copy-Item .env.example .env` instead of `cp`.

## Configuration

Everything is environment variables (see [`.env.example`](.env.example)). The
ones you'll actually touch:

| Variable | Default | Notes |
|---|---|---|
| `HUSQVARNA_CLIENT_ID` / `HUSQVARNA_CLIENT_SECRET` | — | Application key / secret. Leave empty for demo mode |
| `DEMO_MODE` | — | `true` forces synthetic data even if credentials are set |
| `INFLUXDB_TOKEN` | — | Shared by InfluxDB, collector, Grafana (required) |
| `GRAFANA_PORT` | `3005` | Grafana host port |
| `INFLUXDB_PORT` | `8086` | InfluxDB host port |
| `INFLUXDB_RETENTION` | `0s` | `0s` = keep forever; or e.g. `730d` |
| `REST_POLL_INTERVAL` | `3600` | Seconds between REST polls (statistics refresh) |
| `WRITE_POSITIONS` | `true` | Set `false` to skip storing GPS positions |
| `LOG_LEVEL` | `INFO` | `DEBUG` to see every event and write |

## How it works

The Python project is managed with [uv](https://docs.astral.sh/uv/): dependencies
are declared in `collector/pyproject.toml` and pinned in `collector/uv.lock`, and
the Docker image builds from that lockfile for reproducible, multi-arch builds.

- **`collector/husqvarna.py`** — a ~250-line async client: OAuth2 token handling
  (auto-refresh), `GET /mowers` for the full snapshot, and a resilient WebSocket
  listener with app-level keep-alives, token-aware reconnects before the ~2h
  server cap, and exponential backoff.
- **`collector/collector.py`** — keeps an in-memory copy of each mower's
  attributes (seeded from REST, updated by WebSocket `*-event-v2` deltas) and
  writes an InfluxDB point on every change. Statistics come from the REST poll;
  everything else is real-time.
- Real-time state costs no REST quota (it's the WebSocket's job); the REST poll
  runs hourly by default, far inside the API's free quota.

### Measurements

| Measurement | Key fields |
|---|---|
| `automower_status` | `battery_percent`, `activity`, `state`, `mode`, `error_code`, `error_text`, `is_online`, `is_mowing`, `is_charging`, `cutting_height`, `next_start_epoch` |
| `automower_statistics` | `total_cutting_time`, `total_running_time`, `total_charging_time`, `cutting_blade_usage_time`, `number_of_charging_cycles`, `number_of_collisions`, `total_drive_distance`, … (seconds / counts / meters) |
| `automower_position` | `latitude`, `longitude` |

All are tagged with `mower`, `mower_id`, and `model`.

## Operations

```bash
docker compose logs -f collector     # watch it connect + write
docker compose up -d --build         # rebuild after a code change
docker compose down                  # stop (data persists in named volumes)
```

The stack keeps state in named volumes (`influxdb-data`, `grafana-data`). Back up
`influxdb-data` to preserve history.

## Working on the collector (uv)

You don't need a local Python at all — Docker handles everything. But if you want
to iterate on the collector outside Docker:

```bash
cd collector
uv sync                 # create .venv from the lockfile
uv run python collector.py    # needs INFLUXDB_* env + a reachable InfluxDB
```

Change dependencies in `pyproject.toml`, then `uv lock` to refresh `uv.lock`
(commit both). The Docker image installs strictly from `uv.lock`, so a build is
reproducible and matches your local env.

## Deploying to a homelab

This is a standalone stack, but it drops straight into a per-service Compose
homelab (like `srv-basement`): copy the directory in, add a catalog row, and — if
you want a cert'd name for the Grafana UI — front it with your usual Tailscale
Serve sidecar. Only the collector's outbound HTTPS/WSS to Husqvarna is required;
nothing needs to be exposed publicly.
```
