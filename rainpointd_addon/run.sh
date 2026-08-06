#!/usr/bin/with-contenv bashio
set -e

replay_interval="$(bashio::config 'replay_interval')"
transport="$(bashio::config 'transport')"
frequency="$(bashio::config 'frequency')"
sample_rate="$(bashio::config 'sample_rate')"
research_capture_minutes="$(bashio::config 'research_capture_minutes')"
if [[ "${research_capture_minutes}" == "null" ]]; then
  research_capture_minutes=0
fi

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
    capture_args=()
    if (( research_capture_minutes > 0 )); then
      capture_dir="/share/rainpoint-captures/$(date +%Y%m%d-%H%M%S)"
      mkdir -p "${capture_dir}"
      capture_seconds=$((research_capture_minutes * 60))
      capture_args=(
        --signal-capture-seconds "${capture_seconds}"
        --signal-directory "${capture_dir}"
      )
      bashio::log.warning \
        "Saving all detected RF signals for ${research_capture_minutes} minutes"
      bashio::log.info "Raw capture directory: ${capture_dir}"
    fi
    bashio::log.info \
      "Starting receive-only RTL-SDR mode at ${frequency} Hz / ${sample_rate} sps"
    exec python3 -m rainpointd \
      --host 0.0.0.0 \
      --port 8787 \
      --transport rtl433 \
      --storage /data/rainpointd.sqlite3 \
      --frequency "${frequency}" \
      --sample-rate "${sample_rate}" \
      "${capture_args[@]}"
    ;;
  *)
    bashio::exit.nok "Unsupported transport: ${transport}"
    ;;
esac
