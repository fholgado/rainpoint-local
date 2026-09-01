# RainPoint Local contributor guide

## Working copy

- Work from a persistent Git clone, never treat `/private/tmp` as canonical.
- Keep `PROJECT_DEVELOPMENT_TIMELINE.local.md`, `captures/`, copied databases,
  firmware build output, and downloaded upstream snapshots untracked.
- Preserve raw RF/IQ captures until their smallest useful exchanges have been
  promoted to redacted regression fixtures and documented.

## Planning and status

- `PROJECT_ROADMAP.md` is the only live project-status checklist. Update it in
  the same commit that completes, adds, removes, or reorders a project gate.
- Architecture files describe intended boundaries, protocol/research files
  preserve evidence and procedures, and hardware checklists govern one physical
  operation. Do not create another roadmap, backlog, or "remaining work" list
  in those files; link to the canonical roadmap instead.
- A newly discovered task interrupts the active phase only when it blocks the
  phase exit criteria, invalidates evidence, or protects irrigation safety or
  reliability. Otherwise add it to the roadmap backlog with the evidence that
  would promote it.

## Validation

Permission preflight: the Python suite opens localhost listeners, so run
`python3 -m unittest` with localhost-binding permission from the first attempt.
In Codex, request the required escalation for that command. Treat a bind/listen
`PermissionError` as an invalid test environment and rerun with the proper
permission before diagnosing code. PlatformIO builds also need access to the
configured `~/.platformio` package cache; the native C++ protocol test does not
need elevated permission.

Run the complete Python suite used by CI:

```bash
python3 -m unittest -v \
  test_rainpoint_protocol.py \
  test_rainpoint_pairing.py \
  test_rainpoint_pairing_protocol.py \
  test_esp32_network.py \
  test_rainpoint_network_transport.py \
  test_integration_migration.py \
  test_api_models.py \
  test_addon_boundaries.py \
  test_firmware_manifest.py \
  test_firmware_catalog.py \
  test_rainpointd.py \
  test_rainpoint_rf.py \
  test_rainpoint_analysis.py \
  test_rainpoint_safety.py \
  test_pairing_profile_analysis.py \
  test_radio_node_acceptance.py \
  test_rf_trial.py \
  test_pairing_waveform_analysis.py \
  test_sensor_soak.py \
  test_valve_trial_analysis.py
```

Also compile and run the hardware-independent firmware protocol test:

```bash
c++ -std=c++17 -Ifirmware/rainpoint_bridge/include \
  firmware/rainpoint_bridge/tests/protocol_test.cpp \
  -o /tmp/rainpoint-protocol-test
/tmp/rainpoint-protocol-test
```

Use the single supported PlatformIO environment, `rainpoint_bridge`. Do not
restore retired bench, receive-only, dual-radio, or identity-specific firmware
variants.

## Protocol and safety boundaries

- Treat captured frames and tests as evidence, not disposable debug code.
- Keep cloud research under `research/cloud`; runtime code must not require it.
- Never give a valve builder installation-default RF endpoints. Controller,
  valve, and port identities must come from the association under test.
- Valve association and valve control are separate gates. Do not add a live
  valve transmit path until isolated pairing, duration-bounded open,
  acknowledgement, early-stop, and overdue-run anomaly tests pass on dry test
  hardware. Restart and missing telemetry are observation-only; never transmit
  a speculative startup close.
- Keep sensor ACK ownership single-node and persistent. Any reassignment must
  revoke the old owner before the new owner can transmit.
- Keep experimental RF probes compiled out of production firmware.

## Live-system changes

- Read-only health and evidence collection are safe defaults.
- Validate add-on or integration changes locally before deployment.
- Back up live HA configuration before changing it; never commit credentials,
  management tokens, Wi-Fi secrets, databases, or installation-specific IDs.
- Repository examples that intentionally describe one installation belong
  under `examples/` and must be clearly labelled as examples.
