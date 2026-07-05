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

exec /run.sh
