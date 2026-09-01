#!/usr/bin/env bash
# Run one evidence-complete HTV145 stage-zero physical pairing trial.

set -euo pipefail

ssh_host="home-assistant"
node_id=""
factory_endpoint=""
controller_endpoint=""
companion_endpoint=""
arm_seconds=600
capture_tail_seconds=15

usage() {
  echo "Usage: $0 --node-id ID --factory-endpoint HEX --controller-endpoint HEX --companion-endpoint HEX [--ssh-host HOST]"
}

while (($#)); do
  case "$1" in
    --ssh-host) ssh_host="${2:?--ssh-host requires a value}"; shift 2 ;;
    --node-id) node_id="${2:?--node-id requires a value}"; shift 2 ;;
    --factory-endpoint) factory_endpoint="${2:?--factory-endpoint requires a value}"; shift 2 ;;
    --controller-endpoint) controller_endpoint="${2:?--controller-endpoint requires a value}"; shift 2 ;;
    --companion-endpoint) companion_endpoint="${2:?--companion-endpoint requires a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! "${ssh_host}" =~ ^[A-Za-z0-9._-]+$ ]] ||
   [[ ! "${node_id}" =~ ^rp-[0-9a-f]{12}$ ]] ||
   [[ ! "${factory_endpoint}" =~ ^[0-9a-f]{8}$ ]] ||
   [[ ! "${controller_endpoint}" =~ ^[0-9a-f]{8}$ ]] ||
   [[ ! "${companion_endpoint}" =~ ^[0-9a-f]{8}$ ]]; then
  usage >&2
  exit 2
fi

gateway_stopped=false
capture_started=false

restore_services() {
  if [[ "${capture_started}" == "true" ]]; then
    ssh "${ssh_host}" 'ha addons stop local_rainpoint_capture >/dev/null 2>&1 || true' || true
  fi
  if [[ "${gateway_stopped}" == "true" ]]; then
    ssh "${ssh_host}" 'ha addons start local_rainpointd >/dev/null 2>&1 || true' || true
  fi
}
trap restore_services EXIT INT TERM

echo "Arming ${node_id} before the physical gesture."
ssh "${ssh_host}" bash -s -- \
  "${node_id}" \
  "${factory_endpoint}" \
  "${controller_endpoint}" \
  "${companion_endpoint}" \
  "${arm_seconds}" <<'REMOTE'
set -euo pipefail
node_id="$1"
factory_endpoint="$2"
controller_endpoint="$3"
companion_endpoint="$4"
arm_seconds="$5"
token="$(jq -r '.data.entries[] | select(.domain == "rainpoint_local") | .data.registry_write_token' /homeassistant/.storage/core.config_entries)"
api="http://172.30.33.3:8787/api/v1"
curl --max-time 10 -fsS -X POST \
  -H "Authorization: Bearer ${token}" \
  -H 'Content-Type: application/json' \
  -d '{}' \
  "${api}/pairing/stop" >/dev/null || true
payload="$(jq -nc \
  --arg node_id "${node_id}" \
  --arg factory_endpoint "${factory_endpoint}" \
  --arg controller_endpoint "${controller_endpoint}" \
  --arg companion_endpoint "${companion_endpoint}" \
  --argjson duration_seconds "${arm_seconds}" \
  '{duration_seconds:$duration_seconds,node_id:$node_id,profile_id:"htv145_auto_candidate_v1",factory_endpoint:$factory_endpoint,valve_route:$controller_endpoint,companion_endpoint:$companion_endpoint}')"
curl --max-time 10 -fsS -X POST \
  -H "Authorization: Bearer ${token}" \
  -H 'Content-Type: application/json' \
  -d "${payload}" \
  "${api}/pairing/start" >/dev/null

for attempt in 1 2 3 4 5; do
  sleep 1
  status="$(curl --max-time 10 -fsS "${api}/nodes" | jq -c \
    --arg node_id "${node_id}" \
    '.nodes[] | select(.node_id == $node_id) |
      {connected,firmware_version,pairing_state,pairing_completed_steps,
       pairing_failure_reason,pairing_node_state,pairing_node_failure_reason,
       tx_armed,pairing_detail}')"
  if [[ "$(jq -r '.connected and .pairing_state == "armed" and .tx_armed' <<<"${status}")" == "true" ]]; then
    echo "${status}"
    exit 0
  fi
done

echo "Node did not reach a proven armed state: ${status}" >&2
exit 1
REMOTE

echo "Switching the shared SDR from telemetry to a bounded IQ capture."
previous_capture_dir="$(
  ssh "${ssh_host}" \
    "ls -td /share/rainpoint-local/htv145-stock-pairing-* 2>/dev/null | head -1" \
    || true
)"
ssh "${ssh_host}" 'ha addons stop local_rainpointd >/dev/null'
gateway_stopped=true
ssh "${ssh_host}" 'ha addons start local_rainpoint_capture >/dev/null'
capture_started=true
capture_dir=""
for _ in $(seq 1 10); do
  sleep 1
  candidate="$(
    ssh "${ssh_host}" \
      "ls -td /share/rainpoint-local/htv145-stock-pairing-* 2>/dev/null | head -1" \
      || true
  )"
  if [[ -n "${candidate}" && "${candidate}" != "${previous_capture_dir}" ]]; then
    capture_dir="${candidate}"
    break
  fi
done
if [[ -z "${capture_dir}" ]]; then
  echo "Capture app did not create an output directory." >&2
  exit 1
fi
echo "Capture active: ${capture_dir}"
echo
read -r -p ">>> Start the valve pairing gesture now; press Enter here immediately afterward. " _

echo "Recording the complete factory fallback window for ${capture_tail_seconds}s."
sleep "${capture_tail_seconds}"
ssh "${ssh_host}" 'ha addons stop local_rainpoint_capture >/dev/null'
capture_started=false
ssh "${ssh_host}" "sha256sum '${capture_dir}'/*.cu8"

echo "Restoring the RainPoint gateway and collecting the node verdict."
ssh "${ssh_host}" 'ha addons start local_rainpointd >/dev/null'
gateway_stopped=false

status=""
for _ in $(seq 1 20); do
  sleep 1
  status="$(ssh "${ssh_host}" \
    "curl -fsS http://172.30.33.3:8787/api/v1/nodes | jq -c '.nodes[] | select(.node_id == \"${node_id}\") | {firmware_version,pairing_state,pairing_completed_steps,pairing_failure_reason,pairing_htv145_assignment_locked,pairing_htv145_accepted_factory_counter,pairing_htv145_stage0_accepted,pairing_htv145_stage0_rejected}'" 2>/dev/null || true)"
  if [[ -n "${status}" ]]; then
    accepted="$(jq -r '.pairing_htv145_stage0_accepted // false' <<<"${status}")"
    rejected="$(jq -r '.pairing_htv145_stage0_rejected // false' <<<"${status}")"
    if [[ "${accepted}" == "true" || "${rejected}" == "true" ]]; then
      break
    fi
  fi
done

echo "${status}" | jq -c .
if [[ "$(jq -r '.pairing_htv145_stage0_accepted // false' <<<"${status}")" == "true" ]]; then
  echo "VERDICT=GREEN_STAGE0_ACCEPTED"
  trap - EXIT INT TERM
  exit 0
fi

echo "VERDICT=RED_STAGE0_REJECTED"
trap - EXIT INT TERM
exit 1
