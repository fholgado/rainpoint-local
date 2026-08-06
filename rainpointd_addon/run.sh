#!/usr/bin/with-contenv bashio
set -e

replay_interval="$(bashio::config 'replay_interval')"
transport="$(bashio::config 'transport')"
frequency="$(bashio::config 'frequency')"
sample_rate="$(bashio::config 'sample_rate')"

bashio::log.info "API listening on TCP 8787"

cd /opt/rainpoint

case "${transport}" in
  replay)
    bashio::log.warning \
      "Starting read-only replay mode; live RainPoint hardware is not used"
    bashio::log.info "Replay interval: ${replay_interval}s"
    exec python3 -m rainpointd \
      --host 0.0.0.0 \
      --port 8787 \
      --transport replay \
      --interval "${replay_interval}"
    ;;
  rtl433)
    bashio::log.info \
      "Starting receive-only RTL-SDR mode at ${frequency} Hz / ${sample_rate} sps"
    exec python3 -m rainpointd \
      --host 0.0.0.0 \
      --port 8787 \
      --transport rtl433 \
      --frequency "${frequency}" \
      --sample-rate "${sample_rate}"
    ;;
  *)
    bashio::exit.nok "Unsupported transport: ${transport}"
    ;;
esac
