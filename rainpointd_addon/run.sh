#!/usr/bin/with-contenv bashio
set -e

transport="$(bashio::config 'transport')"
frequency="$(bashio::config 'frequency')"
sample_rate="$(bashio::config 'sample_rate')"
serial_device="$(bashio::config 'serial_device')"
serial_baud="$(bashio::config 'serial_baud')"
registry_write_token="$(bashio::config 'registry_write_token')"
node_listen_port="$(bashio::config 'node_listen_port')"
node_tokens="$(bashio::config 'node_tokens')"
device_catalog_path="$(bashio::config 'device_catalog_path')"
event_retention_limit="$(bashio::config 'event_retention_limit')"
if [[ "${registry_write_token}" == "null" ]]; then
  registry_write_token=""
fi
registry_token_path="/data/registry-write-token"
if [[ -n "${registry_write_token}" ]]; then
  umask 077
  printf '%s' "${registry_write_token}" > "${registry_token_path}"
elif [[ -s "${registry_token_path}" ]]; then
  registry_write_token="$(<"${registry_token_path}")"
else
  umask 077
  registry_write_token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  printf '%s' "${registry_write_token}" > "${registry_token_path}"
  bashio::log.info "Generated a persistent gateway management credential"
fi
if [[ "${node_listen_port}" == "null" ]]; then
  node_listen_port=8790
fi
if [[ "${node_tokens}" == "null" ]]; then
  node_tokens=""
fi
if [[ "${device_catalog_path}" == "null" ]]; then
  device_catalog_path=""
fi
if [[ "${event_retention_limit}" == "null" ]]; then
  event_retention_limit=100000
fi
export RAINPOINT_REGISTRY_TOKEN="${registry_write_token}"
export RAINPOINT_NODE_TOKENS="${node_tokens}"

gateway_id_path="/data/gateway-id"
if [[ -s "${gateway_id_path}" ]]; then
  gateway_id="$(<"${gateway_id_path}")"
elif [[ -s "/data/rainpointd.sqlite3" ]]; then
  # Preserve the identity already used by pre-0.9.0 config entries.
  gateway_id="rainpoint-${transport}"
  printf '%s' "${gateway_id}" > "${gateway_id_path}"
  bashio::log.info "Preserved legacy gateway identity during migration"
else
  gateway_id="rainpoint-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
  printf '%s' "${gateway_id}" > "${gateway_id_path}"
  bashio::log.info "Generated a persistent local gateway identity"
fi

discovery_config="$(
  bashio::var.json \
    host "$(hostname)" \
    port "^8787" \
    gateway_id "${gateway_id}" \
    registry_write_token "${registry_write_token}"
)"
if bashio::discovery "rainpoint_local" "${discovery_config}" > /dev/null; then
  bashio::log.info "Published RainPoint Local discovery to Home Assistant"
else
  bashio::log.warning "Could not publish RainPoint Local discovery"
fi

node_args=(
  --node-listen-host 0.0.0.0
  --node-listen-port "${node_listen_port}"
)
gateway_args=(
  --gateway-id "${gateway_id}"
  --event-retention-limit "${event_retention_limit}"
  --registry-token-file "${registry_token_path}"
)
firmware_catalog_path="/data/firmware/catalog.json"
if [[ -f "${firmware_catalog_path}" ]]; then
  gateway_args+=(
    --firmware-catalog "${firmware_catalog_path}"
    --firmware-public-port 8787
  )
  bashio::log.info "Loaded staged experimental radio-node firmware catalog"
fi
if [[ -n "${device_catalog_path}" ]]; then
  gateway_args+=(--device-catalog "${device_catalog_path}")
fi

bashio::log.info "API listening on TCP 8787"
if (( node_listen_port > 0 )); then
  bashio::log.info \
    "Authenticated Wi-Fi radio-node listener enabled on TCP ${node_listen_port}"
fi

cd /opt/rainpoint

case "${transport}" in
  network)
    bashio::log.info "Starting network-only gateway for Wi-Fi radio nodes"
    exec python3 -m rainpointd \
      --host 0.0.0.0 \
      --port 8787 \
      --transport network \
      --storage /data/rainpointd.sqlite3 \
      "${gateway_args[@]}" \
      "${node_args[@]}"
    ;;
  rtl433)
    bashio::log.info \
      "Starting receive-only RTL-SDR mode at ${frequency} Hz / ${sample_rate} sps"
    exec python3 -m rainpointd \
      --host 0.0.0.0 \
      --port 8787 \
      --transport rtl433 \
      --storage /data/rainpointd.sqlite3 \
      --frequency "${frequency}" \
      --sample-rate "${sample_rate}" \
      "${gateway_args[@]}" \
      "${node_args[@]}"
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
      "${gateway_args[@]}" \
      "${node_args[@]}"
    ;;
  *)
    bashio::exit.nok "Unsupported transport: ${transport}"
    ;;
esac
