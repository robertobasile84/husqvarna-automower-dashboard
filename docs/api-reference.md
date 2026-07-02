# Automower Connect API — reference notes

Distilled from the official OpenAPI spec (**Automower® Connect API, v1.0.0**) on
the [Husqvarna Developer Portal](https://developer.husqvarnagroup.cloud/apis/automower-connect-api).
This captures exactly what the collector relies on and the blueprint for the
(optional, not-yet-built) control feature. The portal spec is the source of
truth; this file is a convenience copy and may drift over time.

## Auth & headers

- **Token:** `POST https://api.authentication.husqvarnagroup.dev/v1/oauth2/token`
  with `grant_type=client_credentials&client_id=<key>&client_secret=<secret>`.
- **REST base:** `https://api.amc.husqvarna.dev/v1`
- **WebSocket:** `wss://ws.openapi.husqvarna.dev/v1`
- **Required REST headers:** `Authorization: Bearer <token>`,
  `X-Api-Key: <application key / client_id>`, `Authorization-Provider: husqvarna`.
- **WebSocket handshake:** `Authorization: Bearer <token>` only.

> The application must have **both** the *Authentication API* and the *Automower
> Connect API* connected on the portal. If only the former is connected, REST may
> still work but the **WebSocket handshake returns 403** — connect the Automower
> Connect API to fix it.

## Data model (`GET /mowers` → `data[].attributes`)

Fields the collector reads, with the InfluxDB field they map to:

| API path | Type | InfluxDB field |
|---|---|---|
| `system.name` / `system.model` | string | tags `mower` / `model` |
| `battery.batteryPercent` | int 0–100 | `battery_percent` |
| `battery.remainingChargingTime` | int seconds (0 if not charging / unsupported) | — (available, not stored) |
| `mower.activity` | enum | `activity`, `is_mowing`, `is_charging` |
| `mower.state` | enum | `state`, `is_error` |
| `mower.mode` | enum | `mode` |
| `mower.errorCode` | int | `error_code` (+ `error_text` via lookup) |
| `mower.errorCodeTimestamp` | int ms, **mower local time** | — |
| `planner.nextStartTimestamp` | int ms, **mower local time** (0 = start now) | `next_start_epoch` |
| `planner.restrictedReason` | enum (incl. `WORK_AREA_ABANDONED`) | `restricted_reason` |
| `metadata.connected` | bool | `connected`, `is_online` |
| `metadata.statusTimestamp` | int ms, **UTC** | — |
| `settings.cuttingHeight` | int 1–9 | `cutting_height` |
| `positions[]` | array of `{latitude, longitude}`, newest first, max 50 | `automower_position` |
| `statistics.*` | see below | `automower_statistics` |
| `capabilities.position` | bool — whether the model has GPS | — |

**Statistics** (all seconds unless noted): `cuttingBladeUsageTime`, `downTime`,
`numberOfChargingCycles` (count), `numberOfCollisions` (count), `totalChargingTime`,
`totalCuttingTime`, `totalDriveDistance` (meters), `totalRunningTime`,
`totalSearchingTime`, `upTime`. Missing field ⇒ model doesn't support it.

> **Timestamp caveat:** `nextStartTimestamp` / `errorCodeTimestamp` are in the
> mower's **local** time (encoded as ms-since-epoch), not UTC. Treating them as a
> true Unix epoch can be off by the local UTC offset — acceptable for the current
> "next start" panel, but keep it in mind before doing precise time math.

## WebSocket events

Documented in the official **Automower® Connect Websocket API (AsyncAPI 1.0.0)**,
separate from the REST OpenAPI spec. Each message is `{"id", "type",
"attributes": {...}}` carrying the changed slice of a mower's attributes. The
documented events and their triggers:

| Message ID | Triggered when |
|---|---|
| `connection-event` | the connection is created (the "ready"/connectionId banner) |
| `battery-event-v2` | battery percent is updated |
| `mower-event-v2` | mower status (activity/state/mode/error) is updated |
| `planner-event-v2` | the planner is updated |
| `position-event-v2` | a new position is added |
| `cuttingHeight-event-v2` | cutting height is updated |
| `headlights-event-v2` | headlight mode is updated |
| `calendar-event-v2` | the calendar / a task is updated |
| `message-event-v2` | a new message is added |

**Documented constraints & behavior (from the WebSocket README):**

- **Events are throttled to ~every 15 minutes.** The mower has a 10-minute
  timeout to save battery/data, so updates are *not* real-time/continuous — even
  while active, expect a push roughly every 15 minutes. A short listen may see
  nothing; this is normal.
- **No API key** is needed for the WebSocket — only `Authorization: Bearer`.
- **2-hour hard limit** per connection; reconnect before it (the collector cycles
  at ~110 min). Max **10 connections/user**, max **1 new connection/second**.
- **Keep-alive:** sending `ping` keeps the socket alive but returns no pong;
  send an **empty message** to get an empty message back. The collector uses the
  empty-message approach plus aiohttp protocol heartbeats.
- **403 on the WebSocket while REST works** = wrong OAuth scope. The token needs
  scope `iam:read amc:api`; if it's missing, **connect the application to the
  Automower Connect API** on the portal (renewing the application also helps).

## Control API (blueprint — not implemented yet)

`POST /mowers/{id}/actions` with a JSON:API body `{"data": {"type": ..., "attributes": {...}}}`:

| Action `type` | Attributes | Effect |
|---|---|---|
| `Start` | `{duration}` (minutes) | Mow for N minutes |
| `StartInWorkArea` | `{duration, workAreaId}` | Mow a work area for N minutes |
| `Pause` | — | Pause |
| `ResumeSchedule` | — | Clear override, resume calendar |
| `Park` | `{duration}` or `{externalReason}` | Park for N minutes |
| `ParkUntilNextSchedule` | — | Park until next scheduled task |
| `ParkUntilFurtherNotice` | — | Park indefinitely (mode → HOME) |

Other action endpoints: `POST /mowers/{id}/settings` (cutting height / headlight),
`POST /mowers/{id}/errors/confirm` (confirmable errors only),
`POST /mowers/{id}/statistics/resetCuttingBladeUsageTime`,
`PATCH /mowers/{id}/stayOutZones/{zoneId}` (enable/disable),
`PATCH /mowers/{id}/workAreas/{workAreaId}` (cutting height).

## Other read endpoints (unused)

`GET /mowers/{id}` (single), `/messages` (last 50, with positions),
`/workAreas`, `/stayOutZones`, `/profiles`, and `/maps/{generated,site,zone}`
(SVG map of the lawn — a possible future overlay for the position map).
