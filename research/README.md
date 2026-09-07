# Research procedures and evidence

For current packet rules, use [the device references](../protocol_documentation/).
For open work, use [the roadmap](../PROJECT_ROADMAP.md). Research observations are
not runtime defaults or proof that a pending physical gate has passed.

## Procedures

- [Device lifecycle validation](DEVICE_PAIRING_VALIDATION_PLAN.md): repeatable
  enrollment, restart, rejoin, ownership, and removal checks.

- [Durable reliability collection](../examples/reliability-soak/README.md):
  independent 72-hour snapshots/events, restart-safe cursor, and explicit gap records.

- [Pairing playbook](PAIRING_REVERSE_ENGINEERING_PLAYBOOK.md): lifecycle isolation,
  transcript reconstruction, waveform comparison, and evidence requirements.
- [RF capture](RF_CAPTURE_PLAN.md): capture setup and retention.
- [Pairing bench](PAIRING_BENCH_TEST.md): one isolated pairing operation.
- [OTA qualification](OTA_HARDWARE_VALIDATION.md): physical update/rollback checks.
- [Four-zone capture](FOUR_ZONE_VALVE_TEST_PLAN.md): crossed zone/duration trials.

## Evidence records

- [Fixtures](fixtures/): exact redacted exchanges and measured trial outcomes.
- [Capture journal](RF_CAPTURE_NOTES.md): chronological observations.
- [Valve evidence ledger](VALVE_PROTOCOL_STATUS.md): evidence interpretation.
- [One-zone counter experiment](HTV145_COUNTER_ANCHOR_EXPERIMENT.md): hypothesis
  tests and accepted recovery evidence; the device reference defines current rules.
- [Workspace consolidation](WORKSPACE_CONSOLIDATION_20260905.md): retained/superseded work.

## Designs and external research

- [Four-zone morning sync](HTV405_MORNING_SYNC_DESIGN.md): scheduling rationale and evidence.
- [Radio integration design](HA_RADIO_FREQUENCY_INTEGRATION.md): interface background.
- [Manufacturer/lifecycle research](HTV145_PAIRING_EXTERNAL_RESEARCH_20260901.md).
- [Cloud research](cloud/README.md): correlation only, never a runtime dependency.

Raw RF/IQ and private operational evidence stay untracked until the smallest
useful exchanges have been promoted to redacted fixtures. Preserve original
captures; do not replace them with screenshots or inferred decoder annotations.
