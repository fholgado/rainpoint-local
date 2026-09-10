# OTA hardware validation

This file preserves OTA trial evidence and recovery procedures. The live gate
status is tracked only in `../PROJECT_ROADMAP.md`.

Status: successful physical install plus managed local release path; production
gates remain.

## 2026-09-09 late-download interruption diagnosis

The affected production node repeatedly retained its healthy 0.16.2 image after
truncated downloads of the same 963,120-byte unified 0.17.0 artifact that two
other nodes installed. Moving it beside an AP improved RSSI but did not fix OTA.
Two further bounded reproductions failed at 904,407 and 908,715 bytes after
about 12.2 seconds, without a Wi-Fi reconnect. Instrumenting only the firmware
HTTP response showed the server's whole-image `sendall` raising `TimeoutError`
after **10.001 seconds**, with its socket timeout set to ten seconds.

That timeout is a total budget for one write, not a reset-on-progress deadline.
The old server assigned the same deadline to small JSON replies and an entire
firmware image. ESP32 receive/flash backpressure could exhaust that budget even
while data continued moving. This establishes the cause of the instrumented
failure; earlier interruptions without matching server evidence need not all
have the same cause.

The regression uses real HTTP sockets with constrained buffers and a reader
that deliberately consumes data slowly. Before the fix, the scaled 250 ms
whole-write budget truncated a 1,048,576-byte response to 589,221 bytes; after
the fix it received the exact image and digest. Run:

```bash
python3 -m unittest tests.test_firmware_catalog -v
```

Gateway 0.37.1 writes 16 KiB chunks with a ten-second per-write limit and a
120-second overall limit, restoring the ordinary socket timeout afterward.
Two firmware download slots preserve API worker capacity. Tests cover slow
progress, stalled and disconnected writers, the overall deadline, exact byte
content, and capacity release. Temporary diagnostic logging is removed;
interrupted-transfer warnings retain release, queued-byte count, elapsed time
and reason. Queued bytes do not prove delivery. Firmware hash verification,
rollback, RF behavior and association persistence are unchanged.

After deploying only gateway 0.37.1, the next managed update of the same image
booted the previously failing node into 0.17.0 by approximately 18 seconds.
At approximately 75 seconds it reported `confirmed` /
`gateway_and_radio_healthy`, cleared its pending-candidate flag, and retained
two sensor ACK assignments and authenticated single-zone counter state. Fresh
RF frames continued, ACK failures were zero and Wi-Fi was approximately
-51 to -53 dBm with zero reconnects after boot. The other two nodes remained
connected on 0.17.0; all eight registered devices were available and both
valves idle. No pairing or extra watering was performed. This is one successful
post-fix physical update plus a red/green regression, not a long-term soak claim.
The temporary observation script matched the request ID before reboot, but
that ID clears on candidate boot; final confirmation was checked directly from
version, authenticated reconnect, candidate state and restored ownership.

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

## Unvalidated recovery scenarios

- Reject an artifact with the wrong SHA-256 without changing boot partition.
- Recover from an interrupted download and retain the running image.
- Remove power during download and during the first candidate boot.
- Force three unhealthy candidate boots and verify selection of the previous
  partition.
- Verify USB recovery after an intentionally unusable candidate.
- Replace the temporary artifact location with managed gateway hosting and
  cleanup. (Managed hosting is implemented; retention cleanup remains.)
- Add asymmetric signed release metadata before enabling OTA in normal
  firmware.

## Managed Home Assistant path

Gateway 0.21.0 adds a strict local release catalog, immutable artifact serving,
hardware/channel/variant compatibility checks, and install-by-release-ID. The
Home Assistant integration adds native firmware Update entities with release
notes and byte progress. Gateway 0.23.0 and firmware `0.10.0-test.5` consolidate
generalized pairing, routine acknowledgements, and OTA into one experimental
image. ACK authorization remains RAM-only on the node, while the gateway
persists exactly one owner per sensor and restores the bounded configuration
after reconnect or OTA boot. UI-triggered unified installation and physical
post-reboot ACK restoration remain to be exercised before this path is fully
validated. During the first `0.9.0-test.2` to `0.10.0-test.1` managed trial,
the artifact downloaded and verified but the immediate restart remained in the
network-command context until a controlled USB reset. `0.10.0-test.2` introduced
the deferred top-level restart; `0.10.0-test.3` is the version-only successor
used to validate that corrected updater path while test.2 is running.
The test.2 to test.3 trial proved that the deferred reboot ran automatically,
but also exposed the gateway retaining the pre-reboot TCP session. Gateway
0.23.0 admits a replacement only after it proves the same managed credential;
the managed test.3 to test.4 trial then passed without USB or a gateway
restart. Test.4 downloaded 918,720 bytes, matched SHA-256, rebooted itself,
replaced the stale authenticated session, reported `candidate_boot`, and
cleared its rollback marker after 60 seconds of authenticated gateway plus
CC1101 health. A subsequent USB migration of the live Sensor A ACK owner to
test.4 exposed that the authenticated firmware command allowlist omitted the
gateway's bounded ACK configure/revoke messages. Test.5 corrected that boundary
and passed the physical recovery check: after reboot and again after a gateway
restart, the node reported `configured_by_gateway`, endpoint `9bce0024`, channel
4, one assigned sensor, one authorized sensor, and zero ACK failures. The
remaining consolidated-path gate is initiating an update through Home
Assistant's native Update entity.
