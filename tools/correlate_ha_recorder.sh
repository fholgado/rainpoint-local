#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: correlate_ha_recorder.sh --start 'YYYY-MM-DD HH:MM:SS' \
  --end 'YYYY-MM-DD HH:MM:SS' [--host home-assistant] \
  [--timezone America/New_York]

Print valve, watering, and soil-moisture state changes from the Home Assistant
recorder over a local-time capture window. The remote Terminal add-on must have
the sqlite3 command available.
EOF
}

capture_start=""
capture_end=""
ha_host="home-assistant"
capture_timezone="America/New_York"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start)
      capture_start="${2:-}"
      shift 2
      ;;
    --end)
      capture_end="${2:-}"
      shift 2
      ;;
    --host)
      ha_host="${2:-}"
      shift 2
      ;;
    --timezone)
      capture_timezone="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

timestamp_pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'
if [[ ! "$capture_start" =~ $timestamp_pattern ]] || \
   [[ ! "$capture_end" =~ $timestamp_pattern ]]; then
  usage >&2
  exit 2
fi

to_epoch() {
  local timestamp="$1"
  local epoch
  if epoch=$(TZ="$capture_timezone" date -j -f '%Y-%m-%d %H:%M:%S' \
    "$timestamp" +%s 2>/dev/null); then
    printf '%s\n' "$epoch"
    return
  fi
  TZ="$capture_timezone" date -d "$timestamp" +%s
}

start_epoch=$(to_epoch "$capture_start")
end_epoch=$(to_epoch "$capture_end")
if (( start_epoch >= end_epoch )); then
  echo "--start must be earlier than --end" >&2
  exit 2
fi

ssh "$ha_host" "command -v sqlite3 >/dev/null || {
  echo 'sqlite3 is not installed in the Terminal add-on' >&2
  exit 1
}; sqlite3 -readonly -header -separator '|' \
  /homeassistant/home-assistant_v2.db \"SELECT
    strftime('%Y-%m-%d %H:%M:%f', s.last_updated_ts,
      'unixepoch', 'localtime') AS local_time,
    sm.entity_id,
    s.state
  FROM states s
  JOIN states_meta sm ON sm.metadata_id = s.metadata_id
  WHERE s.last_updated_ts BETWEEN $start_epoch AND $end_epoch
    AND (
      sm.entity_id LIKE 'valve.%'
      OR sm.entity_id LIKE 'switch.%valve%'
      OR sm.entity_id LIKE 'sensor.%soil_moisture%'
      OR sm.entity_id LIKE 'sensor.%valve_session_duration%'
      OR sm.entity_id LIKE 'sensor.%valve_last_session_volume%'
      OR sm.entity_id LIKE 'number.%valve%duration%'
      OR sm.entity_id LIKE 'script.%watering%'
    )
  ORDER BY s.last_updated_ts;\""
