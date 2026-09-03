# RainPoint RF protocol documentation

This directory is the human-readable specification for the latest supported
RainPoint RF behavior. It describes the protocol as currently understood; it
does not preserve the order in which that understanding was discovered.

Read [common.md](common.md) first, then the file for the device family:

| Device | Protocol definition | Local status |
|---|---|---|
| Stock RainPoint gateway (`HWG023WBRF-V2`) | [hwg023wbrf-v2.md](hwg023wbrf-v2.md) | Reference implementation and coexistence constraint |
| Soil-moisture sensors (`HCS02x`, validated as `HCS026FRF`) | [hcs026frf.md](hcs026frf.md) | Pair, receive, acknowledge, and recover |
| Single-zone valve (`HTV145FRF`) | [htv145frf.md](htv145frf.md) | Receive/decode; local pairing has accepted assignment and stage 1, later stages remain research-only |
| Four-zone valve (`HTV405FRF`) | [htv405frf.md](htv405frf.md) | Pair, receive, acknowledge, and control |

Exact frames and experiment chronology live under [`research/`](../research/).
The executable specification lives in `rainpointd_addon/rainpointd/`, with
regression coverage in `rainpointd_addon/tests/`.

## Interpretation rules

- **Confirmed** means reproduced from valid RF evidence or accepted by the
  physical device.
- **Profile-specific** means valid for the recorded association profile and
  not yet proven universal across all devices or firmware revisions.
- **Unknown** means the integration must report the field as unavailable; it
  must not guess.
- A transmitted command is not proof that the device acted. Only an
  authenticated response or independent state report confirms state.

Open work and release gates belong only in
[`PROJECT_ROADMAP.md`](../PROJECT_ROADMAP.md). Capture procedures and the
chronological research record belong in
[`research/RF_CAPTURE_NOTES.md`](../research/RF_CAPTURE_NOTES.md).

The reusable process for investigating another device family is
[`research/PAIRING_REVERSE_ENGINEERING_PLAYBOOK.md`](../research/PAIRING_REVERSE_ENGINEERING_PLAYBOOK.md).
