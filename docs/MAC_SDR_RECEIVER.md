# Optional Mac SDR receiver

The ESP32 nodes remain responsible for pairing, ACKs and valve control. This
research receiver only listens; HA does not depend on it.

`tools/mac_sdr_receiver.py` manages `rtl_433`, journals decoded events, restarts
the decoder after USB failure, and can forward **new** frames over authenticated
TLS. It cannot transmit RF, become an ACK owner, or replay old journal entries.
Unlike continuous IQ capture, it does not consume gigabytes per minute.

## Local listening

Use Python 3.13+ and an installed `rtl_433`. Create a private, dedicated output
directory (mode 0700) and a JSON configuration using absolute paths:

```json
{
  "rtl433_path": "/opt/homebrew/bin/rtl_433",
  "device": "0",
  "frequency_hz": 433700000,
  "sample_rate": 2000000,
  "output_directory": "/absolute/private/rainpoint-sdr",
  "max_journal_bytes": 134217728
}
```

Run `python3 tools/mac_sdr_receiver.py --config /absolute/receiver.json`.
Only one process may own that output directory. Stop other processes using the
same USB SDR first. Ctrl-C/SIGTERM stops the child decoder cleanly.

- `events.jsonl`: original decoder events, normalized frame bytes, verbatim
  source timestamps and explicit UTC receipt timestamps. The live decoder runs
  with `TZ=UTC`; this does **not** reinterpret timestamps in older recordings.
- `status.json`: listening/disconnected/stopped/failed/storage-full state,
  current-run counts, decoder exits and optional forwarding counts.
- The journal stops at its byte budget. It never deletes existing recordings.
  Stop the service and archive/move the journal before resuming with an empty
  one. Counters in `status.json` restart per process, not per journal.

## Optional forwarding

Leave `forward` absent for local-only collection. To enable it, provision a
**dedicated receive-only identity and credential**, never an existing ESP32's
identity, through the gateway's advanced `node_tokens` configuration. This is
research setup, not the normal HA radio-adoption flow. Keep the random 64-hex
credential in a separate private regular file (0600), then add:

```json
"forward": {
  "host": "homeassistant.local",
  "port": 8790,
  "node_id": "rp-112233445566",
  "token_file": "/absolute/private/receiver.key"
}
```

The example ID is illustrative; generate a unique one for your receiver.
TLS-PSK authenticates/encrypts the connection; the receive-only node protocol
advertises only `rx`. No management credential or transmit permission is needed.
Connection failure backs off for 30 seconds and drops forwarding attempts while
preserving local events. Never replay those events to fill a gap: the gateway
currently dates node frames at ingestion, not historical RF receipt time.
`forwarded` counts socket sends, not gateway acknowledgements; check gateway
receiver counters to verify delivery. No channel number is guessed from the
wide-band SDR's center frequency.

## macOS service

`--print-launch-agent` emits a plist with absolute paths and no secrets. Save it
as `~/Library/LaunchAgents/org.rainpoint.local.sdr.plist`, inspect it, then use
`launchctl bootstrap gui/$(id -u) <absolute-plist-path>` to load it. Use
`launchctl bootout gui/$(id -u)/org.rainpoint.local.sdr` to stop/unload it.
It starts at login; decoder reconnection is internal. It deliberately does not
auto-restart after a full journal or configuration error. Inspect `status.json`
and use `launchctl kickstart gui/$(id -u)/org.rainpoint.local.sdr` after correction.

Automated tests use real child processes and a disposable TLS gateway. Physical
USB recovery, sustained reception and launchd installation remain operational
qualification in the [roadmap](../PROJECT_ROADMAP.md). This work does not install
a background job or alter the live gateway on its own.
