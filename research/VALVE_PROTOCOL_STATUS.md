# Valve protocol evidence index

The device references define current packet rules:

- [HTV405 four-zone valve](../protocol_documentation/htv405frf.md): shared command
  counter, zone selection, bounded duration, report ACKs, and idle synchronization.
- [HTV145 single-zone valve](../protocol_documentation/htv145frf.md): partial
  association, command phases, report/summary ACKs, and fixed-zero idle recovery.

Association, command acceptance, state, ACK waveform acceptance, and retained
counter reachability are separate claims. A transmitted frame proves none of
those by itself. Controller requests are intent; only matching valve responses
or independent state reports update watering. Historical summaries do not clear
an active run or authenticate a command counter.

## Evidence by question

| Question | Retained evidence |
|---|---|
| HTV405 association-wide counter continuity | [Generated association](fixtures/htv405_generated_identity_counter_continuity_20260901.json) |
| HTV405 apparent overnight counter loss | [Drift with infrastructure confounders](fixtures/htv405_overnight_counter_drift_20260902.json) |
| HTV405 report-triggered morning anchor and direct control | [Morning synchronization](fixtures/htv405_morning_sync_smoke_20260905.json) |
| HTV145 fixed-zero recovery, result 3, and rollover | [Idle recovery](fixtures/htv145_idle_result3_counter_recovery_20260906.json) |
| HTV145 restart without replay and bounded stop | [Restart recovery](fixtures/htv145_restart_recovery_20260906.json) |
| HTV145 standard firmware/HA promotion | [Bounded controls and restored telemetry](fixtures/htv145_standard_firmware_control_20260906.json) |

For physical procedures use the [pairing playbook](PAIRING_REVERSE_ENGINEERING_PLAYBOOK.md)
and [lifecycle procedure](DEVICE_PAIRING_VALIDATION_PLAN.md). Qualification status
is maintained only in the [roadmap](../PROJECT_ROADMAP.md). Trial chronology and
rejected hypotheses remain in capture evidence and Git history.
