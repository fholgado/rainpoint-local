#!/usr/bin/env bash
#
# Record a bounded, receive-only RainPoint RF discovery session.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
duration="15m"
frequency_hz="433700000"
sample_rate="2000000"
save_signals="known"
output_root="${repo_root}/captures/rf"
dry_run=false

usage() {
  echo "Usage: $0 [--duration 15m] [--frequency 434000000] [--sample-rate 1024000] [--save-signals known|all] [--output DIR] [--dry-run]"
}

while (($#)); do
  case "$1" in
    --duration)
      duration="${2:?--duration requires a value}"
      shift 2
      ;;
    --frequency)
      frequency_hz="${2:?--frequency requires a value}"
      shift 2
      ;;
    --sample-rate)
      sample_rate="${2:?--sample-rate requires a value}"
      shift 2
      ;;
    --save-signals)
      save_signals="${2:?--save-signals requires known or all}"
      if [[ "${save_signals}" != "known" && "${save_signals}" != "all" ]]; then
        echo "--save-signals must be known or all" >&2
        exit 2
      fi
      shift 2
      ;;
    --output)
      output_root="${2:?--output requires a directory}"
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v rtl_433 >/dev/null 2>&1; then
  echo "rtl_433 is not installed. On macOS: brew install rtl_433" >&2
  exit 1
fi

session_name="$(date +%Y%m%d-%H%M%S)"
session_dir="${output_root}/${session_name}"

command_args=(
  rtl_433
  -f "${frequency_hz}"
  -s "${sample_rate}"
  -R 0
  -S "${save_signals}"
  -M time:iso:usec
  -M level
  -M bits
  -M protocol
  -X "n=RainPoint,m=FSK_PCM,s=50,l=50,r=50000,bits>=620,match={40}79f4882f28"
  -F json:events.jsonl
  -F log:rtl_433.log
  -T "${duration}"
)

if "${dry_run}"; then
  printf 'Session directory: %s\nCommand: ' "${session_dir}"
  printf '%q ' "${command_args[@]}"
  printf '\n'
  exit 0
fi

mkdir -p "${session_dir}"
ln -sfn "${session_name}" "${output_root}/latest"

{
  printf 'started_utc\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'started_local\t%s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)"
  printf 'frequency_hz\t%s\n' "${frequency_hz}"
  printf 'sample_rate\t%s\n' "${sample_rate}"
  printf 'save_signals\t%s\n' "${save_signals}"
  printf 'duration\t%s\n' "${duration}"
  printf 'rtl_433\t%s\n' "$(rtl_433 -V 2>&1 | head -n 1)"
} >"${session_dir}/session.tsv"
printf 'timestamp_utc\ttimestamp_local\taction\n' >"${session_dir}/actions.tsv"

echo "Receive-only capture directory: ${session_dir}"
echo "Frequency: ${frequency_hz} Hz; sample rate: ${sample_rate}; duration: ${duration}"
echo "Raw I/Q signals, decoded JSON, and logs will be kept together."
echo "To timestamp an action from another terminal:"
echo "  ./tools/mark_rainpoint_rf_action.sh \"description\""

(
  cd "${session_dir}"
  exec "${command_args[@]}"
)

printf 'finished_utc\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  >>"${session_dir}/session.tsv"
echo "Capture complete: ${session_dir}"
