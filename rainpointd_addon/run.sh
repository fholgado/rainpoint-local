#!/usr/bin/with-contenv bashio
set -e

replay_interval="$(bashio::config 'replay_interval')"
transport="$(bashio::config 'transport')"
frequency="$(bashio::config 'frequency')"
sample_rate="$(bashio::config 'sample_rate')"
serial_device="$(bashio::config 'serial_device')"
serial_baud="$(bashio::config 'serial_baud')"
research_capture_minutes="$(bashio::config 'research_capture_minutes')"
registry_write_token="$(bashio::config 'registry_write_token')"
node_listen_port="$(bashio::config 'node_listen_port')"
node_tokens="$(bashio::config 'node_tokens')"
if [[ "${research_capture_minutes}" == "null" ]]; then
  research_capture_minutes=0
fi
if [[ "${registry_write_token}" == "null" ]]; then
  registry_write_token=""
fi
if [[ "${node_tokens}" == "null" ]]; then
  node_tokens=""
fi
export RAINPOINT_REGISTRY_TOKEN="${registry_write_token}"
export RAINPOINT_NODE_TOKENS="${node_tokens}"

node_args=(
  --node-listen-host 0.0.0.0
  --node-listen-port "${node_listen_port}"
)

bashio::log.info "API listening on TCP 8787"
if (( node_listen_port > 0 )); then
  bashio::log.info \
    "Authenticated Wi-Fi radio-node listener enabled on TCP ${node_listen_port}"
fi

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
      --interval "${replay_interval}" \
      "${node_args[@]}"
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
      "${node_args[@]}" \
      "${capture_args[@]}"
    ;;
  esp32_serial)
    bashio::log.info \
      "Starting receive-only ESP32 bridge at ${serial_device} / ${serial_baud} baud"
    exec python3 -m rainpointd \
      --host 0.0.0.0 \
      --port 8787 \
      --transport esp32_serial \
      --storage /data/rainpointd.sqlite3 \
      --serial-device "${serial_device}" \
      --serial-baud "${serial_baud}" \
      "${node_args[@]}"
    ;;
  *)
    bashio::exit.nok "Unsupported transport: ${transport}"
    ;;
esac
