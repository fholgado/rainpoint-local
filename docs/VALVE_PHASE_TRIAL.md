# Bounded valve command-phase trial

The optional `phase-trial` signing profile builds firmware
`0.19.0-phase-trial.2` for the installed HTV145FRF and HTV405FRF experiment.
It uses the existing RF waveform, association, body and trailer builders with
the complete six-bit command phase supplied separately from the action.
Ordinary production builds omit its commands and capability.
The build retains correlated ACK-ownership confirmations, saved sensor rejoin
channels, and full-phase response matching used by the current garden radios.

The authenticated radio accepts two adjacent, 60-second port-1 opens per
authorization. It persists each attempted command before transmission, rejects
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
`RAINPOINT_FIRMWARE_VERSION=0.19.0-phase-trial.2`; check the binary with
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
The deployed guard remains locked and its existing release command requires
two completed runs. Recovery needs a separately approved, signed no-watering
handoff with preserved failure history; do not erase the journal/NVS, retry the
open, or infer a counter from a report's independent phase.

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
