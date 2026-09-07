# Isolated pairing verification

Use the [device lifecycle procedure](DEVICE_PAIRING_VALIDATION_PLAN.md) for one
physical operation and the [pairing playbook](PAIRING_REVERSE_ENGINEERING_PLAYBOOK.md)
for packet analysis. Build the sole `rainpoint_bridge` firmware environment.

Select the model and radio in Home Assistant, review the selection, then start
pairing. Wait for valve-owned acceptance and the radio to finish before declaring
readiness. Preserve the full exchange and independent LED/state outcome.

Fixed Sensor A/B identities, serial reply probes, and identity-specific firmware
are retired. Their captured frames remain regression fixtures; they are not
installation instructions or runtime defaults. Current qualification status is
in the [roadmap](../PROJECT_ROADMAP.md).
