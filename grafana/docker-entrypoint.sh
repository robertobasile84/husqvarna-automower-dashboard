#!/bin/sh
# Stamp the Position-map center into the provisioned dashboard, then hand off to
# Grafana's normal entrypoint. MAP_* default to the demo location (Zürich); set
# them in the environment (.env) to center the map on your own mower/home.
#
# The sed only touches the map view's "lat"/"lon"/"zoom" keys; the layer's
# "latitude"/"longitude" field mappings don't match and are left untouched.
set -e

mkdir -p /var/lib/grafana/dashboards-live
for f in /etc/grafana/dashboards-src/*.json; do
  sed -E "s/(\"lat\": )[-0-9.]+/\1${MAP_LAT:-47.377}/; s/(\"lon\": )[-0-9.]+/\1${MAP_LON:-8.5417}/; s/(\"zoom\": )[0-9.]+/\1${MAP_ZOOM:-17}/" \
    "$f" > "/var/lib/grafana/dashboards-live/$(basename "$f")"
done

# Anonymous read-only access. GRAFANA_ANONYMOUS, if set, always wins (true/false).
# When it's unset we AUTO-decide using the same demo signal the collector uses
# (demo = DEMO_MODE flag OR no Husqvarna credentials): anonymous stays ON for the
# public demo, but a REAL mower (credentials present) defaults to login-required
# so a personal dashboard — GPS map centered on your home — is never exposed
# anonymously by accident.
if [ -n "${GRAFANA_ANONYMOUS:-}" ]; then
  GF_AUTH_ANONYMOUS_ENABLED="${GRAFANA_ANONYMOUS}"
else
  case "$(printf '%s' "${DEMO_MODE:-}" | tr '[:upper:]' '[:lower:]')" in
    1 | true | yes)
      demo=1 ;;
    *)
      if [ -n "${HUSQVARNA_CLIENT_ID:-}" ] && [ -n "${HUSQVARNA_CLIENT_SECRET:-}" ]; then
        demo=0
      else
        demo=1
      fi ;;
  esac
  if [ "$demo" = 1 ]; then
    GF_AUTH_ANONYMOUS_ENABLED=true
  else
    GF_AUTH_ANONYMOUS_ENABLED=false
  fi
fi
export GF_AUTH_ANONYMOUS_ENABLED
echo "automower: anonymous access GF_AUTH_ANONYMOUS_ENABLED=${GF_AUTH_ANONYMOUS_ENABLED}" >&2

exec /run.sh
