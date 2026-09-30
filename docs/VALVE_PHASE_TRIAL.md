# Bounded valve command-phase trial

The optional `phase-trial` signing profile builds firmware
`0.19.0-phase-trial.1` for the installed HTV145FRF and HTV405FRF experiment.
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
`RAINPOINT_FIRMWARE_VERSION=0.19.0-phase-trial.1`; check the binary with
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
