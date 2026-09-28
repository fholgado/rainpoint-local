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

- [Stock firmware reference](STOCK_HUB_FIRMWARE_REFERENCE.md): consolidated
  1.1.1040 subsystem documentation with explicit evidence levels and unknowns.
- [Stock hub firmware analysis](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md): private
  dump inventory, instruction-backed timing findings, and unresolved RF leads.
- [Stock/local implementation comparison](STOCK_HUB_IMPLEMENTATION_COMPARISON_20260927.md):
  reproduced ACK handoff defect, recovery consistency checks, and prioritized research leads.
- [Stock-hub replacement firmware](STOCK_HUB_CUSTOM_FIRMWARE_FEASIBILITY.md):
  reuse, hardware-port requirements, alternatives and qualification boundaries.
- [Stock pairing clues](STOCK_HUB_PAIRING_CLUES_20260927.md): connection-time
  channel allocation, reconnect headers and comparison with proven pairing stages.
- [Native pairing comparison](PAIRING_NATIVE_COMPARISON.md): 42 captured rows
  across sensor/valve profiles; shared commands, distinct model data and native replay tests.
- [Pairing configuration builders](STOCK_HUB_PAIRING_CONFIGURATION_TRACE.md):
  per-port parameter/plan reads and versioned configuration notifications.
- [Stock firmware update discovery](STOCK_HUB_UPDATE_DISCOVERY.md): recovered
  discovery path and approved lookup; no newer image offered for this hub.
- [Stock HTTP update trace](STOCK_HUB_HTTP_UPDATE_TRACE.md): instruction-backed
  request contract and private configuration mapping.
- [Stock decoder qualification](STOCK_HUB_DECODER_TOOLING.md): synthetic crash
  reproduction, isolated official S3 decoder and bounded instruction checks.
- [Stock Ghidra decompilation](STOCK_HUB_DECOMPILATION.md): verified six-segment
  import, 215 unique function exports and selected assembly/capture checks; private project retained.
- [Stock boot state](STOCK_HUB_BOOT_STATE_REFERENCE.md): recovered boot clear
  covers the shared sequence byte; later restoration and overnight causality remain open.
- [Post-boot/model descriptors](STOCK_HUB_POSTBOOT_TRACE.md): startup sequence
  consumers and retained HTV145 descriptor qualifying its empty terminal array.
- [Report-mode consumers](STOCK_HUB_REPORT_MODE_CONSUMERS.md): incoming class-0x50
  reply extension excludes captured HCS026; no soil wake command established.
- [Offline/known-device recovery](STOCK_HUB_OFFLINE_RECOVERY_STATE.md): HCS026
  expiry callbacks, retained-association announcements and model-qualified timing.
- [Short canary validation](../docs/STOCK_INFORMED_VALIDATION.md): approved
  source changes staged for a low-burden, separately authorized hardware session.
- [Stock radio framing](STOCK_HUB_RADIO_PATH_TRACE.md): native sync/CRC, one-bit
  normalized offset, modem profiles and FIFO/channel boundaries.
- [Stock valve command state](STOCK_HUB_VALVE_STATE_TRACE.md): six-bit sequence,
  retries, response matching, native seconds and remaining-time precision.
- [ACK/retry lifecycle](STOCK_HUB_ACK_RETRY_LIFECYCLE.md): bounded retained-packet
  retries, timeout versus RF rejection, duplicate boundaries and hidden phase consumption.
- [Retained-version comparison](STOCK_HUB_VERSION_COMPARISON.md): unchanged
  counter-generator body and six-bit ACK matching in 1.1.1032/1.1.1040.
- [Sequence consumer audit](STOCK_HUB_SEQUENCE_MATCH_AUDIT.md): wrong-phase
  negative replies and a node/gateway positive-response mismatch; offline repros.
- [Terminal pairing trace](STOCK_HUB_TERMINAL_PAIRING_TRACE.md): parameter reads
  and the preceding repeated-stage recovery gap; initial rejection unresolved.
- [Channel-change trace](STOCK_HUB_CHANNEL_CHANGE_TRACE.md): exact `ReciCH` and
  startup serializers; neither is yet capture-qualified for device acceptance.
- [Stock sensor recovery](STOCK_HUB_SENSOR_RECOVERY_TRACE.md): report-mode limits,
  heartbeat property indirection and cross-version compact-state grammar.
- [Expanded local regressions](STOCK_HUB_LOCAL_REGRESSION_AUDIT.md): reproduced
  retained-selector/HTV405 defects, passing soil freshness and HTV145 lifecycle tests.
- [Fixtures](fixtures/): exact redacted exchanges and measured trial outcomes.
- [Capture journal](RF_CAPTURE_NOTES.md): chronological observations.
- [Valve evidence index](VALVE_PROTOCOL_STATUS.md): evidence interpretation.
- [One-zone counter experiment](HTV145_COUNTER_ANCHOR_EXPERIMENT.md): supported recovery procedure and evidence; the device reference defines current rules.
- [Workspace consolidation](WORKSPACE_CONSOLIDATION_20260905.md): retained/superseded work.

## Designs and external research

- [Stock-informed improvement plan](STOCK_FIRMWARE_IMPROVEMENT_PLAN.md):
  ownership fixes, retained-channel consistency and evidence-gated protocol work;
  approved subset implemented/tested in source only; no deployment authorization.
- [Four-zone morning sync](HTV405_MORNING_SYNC_DESIGN.md): scheduling rationale and evidence.
- [Radio integration design](HA_RADIO_FREQUENCY_INTEGRATION.md): interface background.
- [Manufacturer/lifecycle research](HTV145_PAIRING_EXTERNAL_RESEARCH_20260901.md).
- [Cloud research](cloud/README.md): correlation only, never a runtime dependency.

Raw RF/IQ and private operational evidence stay untracked until the smallest
useful exchanges have been promoted to redacted fixtures. Preserve original
captures; do not replace them with screenshots or inferred decoder annotations.
