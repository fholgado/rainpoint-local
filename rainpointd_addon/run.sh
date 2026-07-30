#!/usr/bin/with-contenv bashio
set -e

replay_interval="$(bashio::config 'replay_interval')"

bashio::log.warning \
  "Starting read-only replay mode; no live RainPoint hardware is connected"
bashio::log.info "Replay interval: ${replay_interval}s"
bashio::log.info "API listening on TCP 8787"

cd /opt/rainpoint
exec python3 -m rainpointd \
  --host 0.0.0.0 \
  --port 8787 \
  --interval "${replay_interval}"
