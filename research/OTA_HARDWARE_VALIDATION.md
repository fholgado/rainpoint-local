# OTA hardware validation

Status: first successful physical install path; production gates remain.

## 2026-08-13 isolated-candidate trial

- Source version: `0.9.0-test.1`
- Candidate version: `0.9.0-test.2`
- Environment: `esp32dev_ota_candidate`
- Artifact size: 914,896 bytes
- SHA-256: `e584251cf21c3edceef45268d6059b3d07200e05e54ab8887ae8eab0019dfaea`
- Transport: authenticated protocol-v2 gateway command and HTTP artifact from
  the configured gateway host

Observed sequence:

1. The gateway accepted the request only for a connected node advertising
   `firmware_update_trial` with RF transmission disarmed.
2. The node downloaded the exact declared byte count.
3. The calculated SHA-256 matched before the inactive partition was selected.
4. The node reported `ready_to_reboot` and `verified_sha256`.
5. It rebooted into `0.9.0-test.2`, rejoined Wi-Fi, and authenticated to the
   gateway.
6. With the CC1101 configuration healthy after 60 seconds, it reported
   `confirmed` and `gateway_and_radio_healthy`.
7. Persistent state reported no pending candidate and zero boot attempts.

This validates the successful install path only. It does not validate
asymmetric release authenticity or deliberately failed recovery paths.

## Remaining physical gates

- Reject an artifact with the wrong SHA-256 without changing boot partition.
- Recover from an interrupted download and retain the running image.
- Remove power during download and during the first candidate boot.
- Force three unhealthy candidate boots and verify selection of the previous
  partition.
- Verify USB recovery after an intentionally unusable candidate.
- Replace the temporary artifact location with managed gateway hosting and
  cleanup.
- Add asymmetric signed release metadata before enabling OTA in normal
  firmware.
