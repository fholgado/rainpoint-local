# Bounded valve command-phase trial

The optional `phase-trial` signing profile builds firmware
`0.19.0-phase-trial.3` for the installed HTV145FRF and HTV405FRF experiment.
It uses the existing RF waveform, association, body and trailer builders with
the complete six-bit command phase supplied separately from the action.
Ordinary production builds omit its commands and capability.
The build retains correlated ACK-ownership confirmations, saved sensor rejoin
channels, and full-phase response matching used by the current garden radios.

The authenticated radio accepts two adjacent, 60-second opens on one reserved
outlet per authorization (HTV145: port 1; HTV405: ports 1–4). It persists each attempted command before transmission, rejects
duplicates and phase jumps, and blocks ordinary valve commands while locked.
Each run requires a matching positive `a1` response and independent active then
idle port-1 reports. Missing or negative confirmation stops the trial. A reboot
retains a failed lock; it cannot restart the allowance. This trial excludes
phase zero and counter-boundary experiments.

After two confirmed runs, an explicit release updates the radio to the existing
production counter recipe. The gateway must atomically persist that projection
before requesting release, keep its lock until the radio acknowledges, and
provide an association-specific positive command/result baseline for admission.
The firmware alone does not provide those gateway controls. Installing or
signing an image does not establish physical acceptance.

## Building and signing

Use the single `rainpoint_bridge` environment. A local validation build uses
`RAINPOINT_VALVE_PHASE_EXPERIMENT=1` and
`RAINPOINT_FIRMWARE_VERSION=0.19.0-phase-trial.3`; check the binary with
`tools/check_firmware_boundaries.py --phase-trial FIRMWARE_BIN`.
The default checker rejects trial commands in production images.

In GitHub, run **Prepare signed firmware (no publication)** on `main` with
profile **phase-trial**. Validation and compilation complete before the
`firmware-signing` environment requests human approval. The signing job verifies
the clean source commit and the reviewed public key, then produces the private
workflow artifact `signed-firmware-unpublished`. It does not publish a release
or deploy a radio. The production profile remains the default.

See [the project roadmap](../PROJECT_ROADMAP.md) for gateway readiness and the
separate live-test qualification gate.

## September 30 installed trial result

Gateway 0.39.10 and signed firmware `0.19.0-phase-trial.1` were deployed to the
front HTV145 owner only. One 60-second port-1 OPEN at native phase 2 was sent,
without retry. Authenticated radio RX recorded a positive phase-2 `a1` at
23:47:10 UTC, active/countdown telemetry at 23:47:16, idle at 23:48:12 and a
summary at 23:48:14. This establishes acceptance of that even-phase OPEN and
automatic closure, not completion of the two-run experiment or general phase
qualification. The veggie node was not flashed or exercised.

The trial monitor timed out despite the positive RF result. Its field-reader
lambda was named `word`; ESP32 Arduino.h defines `word(...)` as
`makeWord(__VA_ARGS__)`. Thus `word(23)` compiled as a conversion of the number
23 rather than a read of the two-byte duration. The duration check could never
pass. Macro-free native tests missed this hardware-build difference.

Renaming the helper to `readLe16` fixes the source. The regression compiles the
real guard both with and without Arduino's macro, including replay of the
[redacted actual RX](../research/fixtures/htv145_phase2_trial_20260930.json).
The macro-enabled test failed before the fix and passes afterward. Neither the
RF command builder nor its duration, timing, power or association changed.

The capture is evidence, not permission to rewrite the failed trial as passed.
The initial deployed guard remained locked because its existing release command
requires two completed runs. The separately approved no-watering recovery below
preserves that failure history; do not erase the journal/NVS, retry the open, or
infer a counter from a report's independent phase.

Private evidence is retained under `captures/installed-phase-20260930/`.
The five-minute IQ file is 1,200,000,000 bytes, SHA-256
`9ae7938c092accf994c3a71a0baa9f3c9156bb44bf160dbf064f777ff99ee518`.
The initial 40-second scan yielded no valid decoded frames; this is a coverage
limitation, not radio silence. The result above rests on authenticated node RX,
not independently decoded SDR IQ. The baseline request was reconstructed from
retained command parameters and the received ACK, not captured over the air.

## Explicit no-watering incident recovery

Version `phase-trial.2` corrects the Arduino macro collision and adds
`valve_phase_trial_recovery`. The authenticated gateway recovery operation is
limited to the first failed HTV145 phase-2 run. It accepts three existing event
IDs, not caller-invented packet bytes. Positive owner ACK, matching active
report and owner idle must have valid CRCs, the reserved route/phase/port and
60-second duration, and ordered timestamps within the original attempt. A later
command response or new watering report invalidates the anchor. Current idle,
unchanged ownership, unchanged last production transmission and no pending
command remain prerequisites.

The gateway atomically stores the evidence and the existing odd-open counter
projection before requesting radio recovery. The radio independently replays
the supplied frames against its preserved NVS authorization, attempted command
ID, phase and selector. It persists a distinct **Recovered** terminal state
before releasing its lock. The gateway waits for that state with the exact
recovery ID. Neither side rewrites the failed attempt as a successful trial.

The recovery command cannot transmit RF. Duplicate requests retain the same
recovery ID, do not reapply the radio counter, and cannot reopen the trial.
No NVS/database deletion, speculative close, counter search or pairing is
involved. Its firmware must be signed through the protected approval workflow;
source/build validation is not deployment or live recovery confirmation.

### October 1 recovery verification

After a verified backup of HA configuration and the current gateway journal,
gateway `0.39.11` was deployed from the tested recovery-only package. Protected
signing run `36796917397` produced front firmware `0.19.0-phase-trial.2` from
commit `390ab69a2426a9df7bdd286e02aef003dee9fa8e`; its publisher signature and
SHA-256 `2d66f6abab607335735157f590d277d2a5c174a047fdbfcd92c2eaed170e05bd`
were independently verified. Only the front node was updated, and it reported
`confirmed` / `gateway_and_radio_healthy` with no pending OTA candidate.

One recovery request used the retained original ACK, active and owner-idle
event IDs. The gateway entered `recovering`, then received the matching radio
stage-7 acknowledgment and recorded `recovered`. The production counter handoff
is 129 (legacy odd-open encoding); the original one-run failure remains in the
journal rather than becoming a completed experiment. Normal front command
availability is restored. Both installed valves reported idle, and the veggie
node remained on `0.19.0`. No open, close, sync, pairing or second trial command
was sent. This verifies recovery, not a subsequent watering run or the remaining
adjacent-phase qualification. Private OTA/recovery receipts are retained beside
the original evidence in `captures/installed-phase-20260930/`.

### Normal-control confirmation after recovery

Later on Oct 1 the user authorized front-garden watering tests. Two normal
public-control port-1 requests each specified 60 seconds, with no application
retry, counter probe, manual stop, re-pairing or additional flash. The second
request followed RF-confirmed automatic closure of the first.

| Run | Native command/ACK phase | Positive ACK | Active report | Automatic idle | Retained counter |
| --- | --- | --- | --- | --- | --- |
| 1 | 3 | 0.67 s | 6.77 s | 62.72 s | 129 → 130 |
| 2 | 5 | ~0.7 s | ~6.7 s | ~62.8 s | 130 → 131 |

Times are observation offsets from request dispatch, not measured mechanical
opening durations. CRC-valid, accepted matching-route RF packets establish
acknowledgment, active port-1 state and return to idle; API acceptance alone
was not counted as success. Status-report phases are independent and were not
used to infer the next command phase. Both transactions completed normally.
This validates the recovered legacy control path and sequential counter advance,
not the still-pending adjacent even/odd trial or long-idle qualification.
Total requested watering was 120 seconds; the vegetable garden was untouched.

Private receipts and RF events are in
`captures/installed-phase-20260930/normal-controls-after-recovery-20261001/`.
The user also requested deletion of existing local backups. Managed HA backups,
inventoried manual recovery copies and identified Mac HA database/archive copies
were removed; the live gateway journal and original RF/firmware research remain.
Consequently the pre-recovery backup referenced above is no longer retained.

### Dry-outlet selection (source only)

The user identified HTV405 outlets 2–4 as dry. Gateway `0.39.12` and trial
firmware `.3` add an explicit `port` to admission, durable reservations and
radio commands. A non-default port requires `valve_phase_trial_ports` at both
admission and authenticated transport; an older radio cannot silently run port 1.
The selected outlet cannot change for the second run. The positive `a1` still
reports control/work mode, not outlet identity; acceptance also requires matching
outlet-specific active and idle `02` reports. The baseline request must identify
that same outlet, so use an authorized normal dry-outlet baseline first if none
is available. Do not reuse a Zone 1 baseline for Zone 2.

The radio record remains 88 bytes with `port` in former padding. Its new magic
version distinguishes valid outlet records from legacy padding: old records
migrate explicitly to port 1, and malformed new outlets fail closed. No pairing
prefix, ordinary production control builder or RF waveform changes. This version
has not been deployed or physically qualified; the front remains on signed `.2`.
