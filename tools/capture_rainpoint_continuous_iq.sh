#!/usr/bin/env bash
# Record bounded continuous RTL-SDR IQ locally without touching Home Assistant.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
duration_seconds=300
frequency_hz=433700000
sample_rate=2000000
device=0
gain_db=0.9
output_root="${repo_root}/captures/continuous"
dry_run=false

usage() {
  echo "Usage: $0 [--duration-seconds 300] [--frequency 433700000] [--sample-rate 2000000] [--device 0] [--gain 0.9] [--output DIR] [--dry-run]"
}

while (($#)); do
  case "$1" in
    --duration-seconds)
      duration_seconds="${2:?--duration-seconds requires a value}"
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
    --device)
      device="${2:?--device requires a value}"
      shift 2
      ;;
    --gain)
      gain_db="${2:?--gain requires a value}"
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

if [[ ! "${duration_seconds}" =~ ^[1-9][0-9]*$ ]] ||
   [[ ! "${frequency_hz}" =~ ^[1-9][0-9]*$ ]] ||
   [[ ! "${sample_rate}" =~ ^[1-9][0-9]*$ ]] ||
   [[ ! "${device}" =~ ^[A-Za-z0-9._-]+$ ]] ||
   [[ ! "${gain_db}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  usage >&2
  exit 2
fi

sample_count=$((duration_seconds * sample_rate))
expected_bytes=$((sample_count * 2))
session_name="$(date +%Y%m%d-%H%M%S)"
session_dir="${output_root}/${session_name}"
capture_path="${session_dir}/continuous.cu8"
command_args=(
  rtl_sdr
  -d "${device}"
  -f "${frequency_hz}"
  -s "${sample_rate}"
  -g "${gain_db}"
  -n "${sample_count}"
  -S
  "${capture_path}"
)

if "${dry_run}"; then
  printf 'Session directory: %s\nExpected bytes: %s\nCommand: ' \
    "${session_dir}" "${expected_bytes}"
  printf '%s ' "${command_args[@]}"
  printf '\n'
  exit 0
fi

if ! command -v rtl_sdr >/dev/null 2>&1; then
  echo "rtl_sdr is not installed. On macOS: brew install rtl-sdr" >&2
  exit 1
fi

mkdir -p "${session_dir}"
ln -sfn "${session_name}" "${output_root}/latest"
{
  printf 'started_utc\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'started_local\t%s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)"
  printf 'frequency_hz\t%s\n' "${frequency_hz}"
  printf 'sample_rate_sps\t%s\n' "${sample_rate}"
  printf 'duration_seconds\t%s\n' "${duration_seconds}"
  printf 'sample_count\t%s\n' "${sample_count}"
  printf 'expected_bytes\t%s\n' "${expected_bytes}"
  printf 'device\t%s\n' "${device}"
  printf 'gain_db\t%s\n' "${gain_db}"
} >"${session_dir}/session.tsv"

echo "Local receive-only IQ capture: ${capture_path}"
echo "Duration: ${duration_seconds}s; expected size: ${expected_bytes} bytes"
"${command_args[@]}" 2>"${session_dir}/rtl_sdr.log"

actual_bytes="$(wc -c <"${capture_path}" | tr -d ' ')"
if [[ "${actual_bytes}" != "${expected_bytes}" ]]; then
  echo "Capture is incomplete: expected ${expected_bytes}, got ${actual_bytes}" >&2
  exit 1
fi
shasum -a 256 "${capture_path}" >"${session_dir}/sha256.txt"
printf 'finished_utc\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  >>"${session_dir}/session.tsv"
echo "Capture complete: ${session_dir}"
