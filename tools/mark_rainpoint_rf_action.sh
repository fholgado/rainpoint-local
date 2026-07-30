#!/usr/bin/env bash
#
# Add a timestamped action to the latest RainPoint RF capture.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
session_dir="${repo_root}/captures/rf/latest"

if (($# == 0)); then
  echo "Usage: $0 \"action description\" [session-directory]" >&2
  exit 2
fi

description="$1"
if (($# >= 2)); then
  session_dir="$2"
fi

action_file="${session_dir}/actions.tsv"
if [[ ! -f "${action_file}" ]]; then
  echo "No active or saved capture found at: ${session_dir}" >&2
  exit 1
fi

description="${description//$'\t'/ }"
description="${description//$'\n'/ }"
printf '%s\t%s\t%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" \
  "$(date +%Y-%m-%dT%H:%M:%S%z)" \
  "${description}" >>"${action_file}"

echo "Marked: ${description}"
