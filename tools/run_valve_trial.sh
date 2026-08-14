#!/usr/bin/env bash
# Run a receive-only, evidence-complete RainPoint valve trial.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
gateway_url=""
trial_id=""
duration="30m"
selected_node=""
stock_gateway_state="on"
output_root="${repo_root}/captures/trials"

usage() {
  echo "Usage: $0 --trial-id ID --gateway-url URL [--duration 30m] [--selected-node ID] [--stock-gateway-state on|off_unverified|off_verified] [--output DIR]"
}

while (($#)); do
  case "$1" in
    --trial-id) trial_id="${2:?--trial-id requires a value}"; shift 2 ;;
    --gateway-url) gateway_url="${2:?--gateway-url requires a value}"; shift 2 ;;
    --duration) duration="${2:?--duration requires a value}"; shift 2 ;;
    --selected-node) selected_node="${2:?--selected-node requires a value}"; shift 2 ;;
    --stock-gateway-state) stock_gateway_state="${2:?--stock-gateway-state requires a value}"; shift 2 ;;
    --output) output_root="${2:?--output requires a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${trial_id}" || -z "${gateway_url}" ]]; then
  usage >&2
  exit 2
fi

mkdir -p "${output_root}"
trial_dir="${output_root}/${trial_id}"
preflight_file="${output_root}/.${trial_id}-preflight.json"
preflight_args=(
  preflight
  --gateway-url "${gateway_url}"
  --output "${output_root}"
  --save "${preflight_file}"
)
prepare_args=(
  prepare
  --trial-id "${trial_id}"
  --kind valve_pairing
  --gateway-url "${gateway_url}"
  --stock-gateway-state "${stock_gateway_state}"
  --output "${output_root}"
)
if [[ -n "${selected_node}" ]]; then
  preflight_args+=(--selected-node "${selected_node}")
  prepare_args+=(--selected-node "${selected_node}")
fi

python3 "${repo_root}/tools/rf_trial.py" "${preflight_args[@]}"
python3 "${repo_root}/tools/rf_trial.py" "${prepare_args[@]}"
mv "${preflight_file}" "${trial_dir}/preflight.json"

finished=false
finish_on_exit() {
  if [[ "${finished}" != "true" && -f "${trial_dir}/manifest.json" ]]; then
    echo "Capture ended before normal completion; preserving the partial report." >&2
    python3 "${repo_root}/tools/rf_trial.py" finish "${trial_dir}" || true
  fi
}
trap finish_on_exit EXIT

echo
echo "Capture is starting. Mark each physical action from another terminal, for example:"
echo "  python3 tools/rf_trial.py mark '${trial_dir}' zone_open --zone 1 --duration-seconds 60"
echo "  python3 tools/rf_trial.py mark '${trial_dir}' zone_close --zone 1"
echo

"${repo_root}/tools/capture_rainpoint_rf.sh" \
  --duration "${duration}" \
  --save-signals all \
  --output "${trial_dir}/rf"

set +e
python3 "${repo_root}/tools/rf_trial.py" finish "${trial_dir}"
finish_status=$?
set -e
finished=true
trap - EXIT
exit "${finish_status}"
