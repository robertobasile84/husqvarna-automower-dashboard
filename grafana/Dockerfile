# Automower Grafana — the stock Grafana image with this project's dashboard,
# datasource, and provisioning baked in, plus a tiny entrypoint that stamps the
# Position-map center (MAP_LAT/MAP_LON/MAP_ZOOM) into the dashboard at startup.
#
# Consumers run this image directly: no grafana/ folder to mount, and dashboard
# updates arrive as a new image tag — just like every other service image.
FROM grafana/grafana:11.4.0

# Provisioning (InfluxDB datasource + dashboard provider) and the dashboard
# sources. The entrypoint renders the sources into /var/lib/grafana/dashboards-live.
COPY provisioning /etc/grafana/provisioning
COPY dashboards /etc/grafana/dashboards-src
COPY docker-entrypoint.sh /automower-entrypoint.sh

ENTRYPOINT ["/automower-entrypoint.sh"]
