# Workspace consolidation, 2026-09-05

This records the disposition of older local work, not a second project plan.
Current qualification gates remain in [the roadmap](../PROJECT_ROADMAP.md).

GitHub `main` at `3008799` already contained sensor-rejoin branch `e4841f2`
and valve-bench branch `ea9963f`. The single-zone branch at `5988573` contained
all 14 commits from the older roadmap clone (`3bb086e`) plus the subsequent
17 commits, including morning synchronization and the local HTV145 control
acceptance evidence. Those histories form one fast-forwardable line from main.

The original checkout was still at `e4363a5` with 11 modified files and two
untracked research files. Its exact files and binary patch were retained in a
local-only archive before reconciliation; raw captures and installation
configuration are not part of this consolidation.

| Pending work | Disposition |
|---|---|
| `api_models.py`, pairing strings, translations, `gateway.py`, and their Python tests | Keep the later model-specific device flow and session-scoped paired evidence. The old `valve_pairing_authorizing_controller` stage required exactly 18 rows; later physical trials establish that this is not a universal completion requirement. Naming already allows the bounded radio exchange to finish. |
| `main.cpp` USB-only open/close harness | Superseded by authenticated, durable, association-specific HTV405 control. Do not restore retired flags, report-derived command counters, or hardcoded bench calibration. |
| `main.cpp` redundant RX recovery fix | Retained for HTV405 pairing. `transmitAsync()` returns success only after restoring reception; a second FIFO flush after status reporting can discard the valve's next request. Failed/no-reply handling remains, and the HTV145 receive sequence is unchanged. Firmware 0.15.13 distinguishes this change from the prior image. |
| `rainpoint_valve_control.h` and native protocol tests | Keep current gateway-envelope builders, explicit profile calibration, command-response counter authentication, and duration/early-stop coverage. The old additions modeled state-report frames as outbound controls; the actual command envelope was established later. |
| Firmware README | Keep the current single environment and isolated HTV145 qualification option; retire the old USB harness instructions. |
| Device pairing validation plan | Its generated-controller-identity and staged migration proposal is already developed in the current identity section, implementation, and roadmap. Do not restore the old TODO list or installation endpoint. |
| HA radio-frequency research | Retained as a dated upstream snapshot, linked to the canonical roadmap, with the obsolete claim that firmware has no valve commands corrected. No new upstream compatibility claim or generic transmit path is introduced. |
| August 19 stock selector-6 capture | Retained with synthetic endpoints and recalculated CRC trailers. Later crossed command/state captures identify these as active/idle reports, not gateway commands. The original active frame actually has residue `4f03`, correcting the old `c713` metadata. A regression verifies both reports and residues. |

The retained report fixture is
[`fixtures/htv405_stock_selector6_control.json`](fixtures/htv405_stock_selector6_control.json).
The later wire definition is
[`../protocol_documentation/htv405frf.md`](../protocol_documentation/htv405frf.md).
The upstream snapshot is
[`HA_RADIO_FREQUENCY_INTEGRATION.md`](HA_RADIO_FREQUENCY_INTEGRATION.md).

Software validation does not establish live FIFO timing or HTV145 ACK
qualification. Merging this source does not deploy a radio or arm pairing.
