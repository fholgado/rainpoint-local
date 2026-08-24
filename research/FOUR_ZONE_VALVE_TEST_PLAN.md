# Four-zone valve evidence plan

This plan records the evidence gates used for the isolated, unpressurized
four-zone test valve. Active trials remain confined to explicitly gated
research firmware; no command builder is connected to production firmware.

## Before powering the valve

1. Photograph the valve label and record the exact model, FCC ID, battery type,
   hardware revision, and any printed device identifier.
2. Keep every outlet unpressurized and visibly confirm all four zones are
   closed.
3. Put the stock RainPoint gateway and the SDR where both sides of the exchange
   can be received. Keep the custom radio nodes online but disarmed.
4. Verify at least 2 GiB of free capture storage. Run the trial workflow on the
   same host that has the RTL-SDR attached.
5. Do not operate unrelated 433 MHz equipment during the capture.

The wrapper performs the gateway, node, transmitter, pairing-state,
`rtl_433`, and disk-space preflight; snapshots the gateway and event cursor;
records every detected RF signal rather than only already-recognized RainPoint
frames; and produces the final report:

```sh
./tools/run_valve_trial.sh \
  --trial-id htv405-stock-enrollment-01 \
  --gateway-url http://homeassistant.local:8787 \
  --duration 45m \
  --stock-gateway-state on
```

The command prints the trial directory. Use that exact directory for every
marker below.

## Passive enrollment sequence

1. Capture two minutes with the valve powered off.
2. Insert the batteries and mark `valve_powered`.
3. Wait two minutes without opening the stock app's pairing UI. This preserves
   unsolicited boot/announcement behavior.
4. Open stock-gateway pairing and mark `stock_pairing_armed`.
5. Perform the documented valve pairing action and mark
   `valve_pairing_action` with the exact button behavior in `--detail`.
6. Mark `stock_pairing_complete` only after the app confirms enrollment.
7. Wait two minutes for post-enrollment telemetry.

Example:

```sh
python3 tools/rf_trial.py mark captures/trials/htv405-stock-enrollment-01 \
  valve_pairing_action --detail "held valve button for 5 seconds"
```

The report labels the first direction, first reverse direction, and first
post-reply frame as structural phase candidates. Those names are evidence aids,
not claims about protocol semantics.

## Zone and duration matrix

Use the stock app only. Mark immediately before each app action. For zones 1
through 4, request both 60 and 120 seconds. This crossed matrix prevents a zone
byte from being mistaken for a duration byte. After the acknowledgement is
visible, issue and mark a manual close instead of waiting for every timer.

```sh
python3 tools/rf_trial.py mark captures/trials/htv405-stock-enrollment-01 \
  zone_open --zone 1 --duration-seconds 60
python3 tools/rf_trial.py mark captures/trials/htv405-stock-enrollment-01 \
  zone_close --zone 1
```

Repeat open/close for `(zone 1, 120)`, then both durations for zones 2, 3, and
4. Leave at least ten seconds between markers. Finally:

1. request a status refresh if the app exposes one and mark `status_refresh`;
2. leave all zones idle for two minutes;
3. confirm all four zones are physically closed; and
4. let the wrapper finish the capture and analysis.

## Evidence acceptance

The bundle must contain:

- the exact hardware inventory and gateway snapshots;
- raw I/Q signals, decoded rows, logs, and timestamped actions;
- at least one bidirectional exchange with multiple message types;
- frames associated with every structured zone/action marker;
- route-specific changed-byte tables and ranked zone, action, and duration
  candidates; and
- Home Assistant recorder correlation over the generated start/end window.

Do not infer that all four zones have separate RF endpoints merely because the
cloud catalog exposes four logical ports. The capture must distinguish a single
chassis identity with a zone selector from independent zone identities.

## Gate after offline analysis

The receive-only gate ended after endpoint identities, Zone 1 command
selection, acknowledgement, and duration-bounded open/close behavior were
validated on dry hardware. Zones 2--4 subsequently passed one-minute dry-bench
opens with an authenticated port-specific response, matching lower state
report, and automatic idle report. Exact evidence lives in
`research/fixtures/htv405_local_multizone_control_20260823.json`.

Further active work remains research-only. New commands must carry an absolute
local duration limit; startup and missing telemetry are observation-only, and
automatic anomaly close requires positive evidence that watering continued
beyond the expected completion plus grace period.

## Remaining power-cycle and battery validation

- Verify that a locally paired HTV405FRF retains its association across a
  battery removal, rejoins the same custom controller without opening a new
  pairing window, and resumes authenticated idle/control reports. Distinguish
  a retained-association rejoin from a new 18-step enrollment by endpoint,
  counter, and frame sequence; a boot sweep or white flash alone is not proof
  of new enrollment.
- The one-reply retained-rejoin hypothesis transmitted successfully but did
  not restore paired traffic and must not be treated as a successful rejoin.
  The next bounded candidate accepts the battery-boot `0x7f` announcement only
  as an alternate first trigger, then uses the unchanged 18-step request
  matcher, replies, advancement rules, timing, and counter resynchronization.
  Normal `0xff` long-press enrollment remains isolated from that mode. Report
  success only after 18/18 steps and a command-scoped paired HTV405 frame; a
  transmitted reply, boot sweep, or white flash is not terminal evidence.
- The `0x7f`-triggered full-transcript trial also failed on 2026-08-24. Probe
  `.41` received the cold-boot sweep and transmitted the unchanged assignment,
  but stopped at 1/18 because the valve never emitted a paired-endpoint
  continuation. The session was explicitly disarmed and no success was
  recorded. See
  `research/fixtures/htv405_battery_rejoin_full_exchange_20260824.json`.
- Do not make another local rejoin protocol change until a controlled stock
  gateway battery-rejoin capture establishes the actual reply count, carrier,
  timing, payloads, identity transition, and terminal behavior.
- The fresh-battery boundary analysis ruled out ordinary paired startup,
  selector-`0x07`, and known zone/countdown fields. A changing diagnostic
  family was also ruled out because it changed again after watering with the
  same fresh batteries. See
  `research/fixtures/htv405_battery_transition_20260823.json`.
- Decode and validate the remaining HTV405FRF battery-status field with a
  safely controlled low-voltage test. Require the decoded state to agree with
  the valve display/app before exposing it in Home Assistant; until then the
  local battery entity must remain unavailable.
