# Security Policy

## Reporting a vulnerability

Please **do not** report security issues through public GitHub issues.

Instead, use GitHub's private vulnerability reporting:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe the issue and, if possible, steps to reproduce.

You'll get a private thread with the maintainer to coordinate a fix and
disclosure. I'll acknowledge reports as promptly as I can.

## Scope & good practices

This project ships **local-development defaults** (InfluxDB token, Grafana and
InfluxDB passwords) in `compose.yaml` and `.env.example` purely so the demo runs
out of the box. They are **not secrets** and must be changed for any deployment
beyond your own machine:

- Set a strong random `INFLUXDB_TOKEN` (e.g. `openssl rand -hex 32`).
- Set your own `GRAFANA_PASSWORD` and `INFLUXDB_PASSWORD`.
- Do not expose the InfluxDB (`8086`) or Grafana (`3005`) ports to the public
  internet without authentication and TLS in front.

Your Husqvarna Application key/secret live only in your gitignored `.env` — never
commit them.
