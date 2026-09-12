# Implementation evidence index — September 12, 2026

This is a historical evidence record, not another live checklist. Current status
belongs in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md). The former verbose roadmap
is preserved verbatim in [the September 12 Git snapshot](https://github.com/fholgado/rainpoint-local/blob/37f9efedb2a3ef40911e08a48c26308d43f39640/PROJECT_ROADMAP.md).
That snapshot includes intermediate failures and later corrections; its older
“not published,” deployment and hardware-availability statements are not current.

## Published baseline

[Alpha 1](https://github.com/fholgado/rainpoint-local/releases/tag/v0.18.0-alpha.1)
was published September 12 from stack commit
37f9efedb2a3ef40911e08a48c26308d43f39640: gateway 0.39.0, HA integration 0.18.0,
firmware 0.19.0. Documentation PR #21 passed all six required CI jobs. The
source archive, downloaded GitHub assets and checksums were verified before
publication. No runtime or live-device changes were needed for the release label.

The separate [firmware release](https://github.com/fholgado/rainpoint-local/releases/tag/firmware-v0.19.0)
retains the approved signed image from source
5dc0c5fc8886ffa49c7cccccd3c50beb93dd46d6 and signing run
[34585252074](https://github.com/fholgado/rainpoint-local/actions/runs/34585252074).
Application SHA-256 is
22d57e428c4b0285710d831ff40b763f74fc322595f66124436bacf6664d4b53
(1,097,648 bytes). All four USB-part hashes match the clean build receipt; the
archive includes offsets and a signed OTA catalog. Private keys, household
databases and capture directories were not distributed.

## Network, OTA and production promotion

The September 10 coordinated TLS rollout preserved eight device identities,
six sensor ACK assignments, valve routes and command counters. Copied-database
validation migrated schema 23 to 25 without losing values across 18 tables;
integrity and backup/copy hashes passed. Config version 3 migration preserves
HA identity/options and consolidates credentials. These migrations are needed
by retained installations/backups, not speculative compatibility code.

September 11 promotion installed the same signed 0.19.0 image on all three
reference radios. Each reported publisher/signature verification, authenticated
TLS reconnect and healthy-boot confirmation. Gateway 0.39.0 rejected raw-URL OTA
without dispatch. Twenty-six host-linked invalid signature cases were rejected
before download/flash; a tampered image was aborted before activation. These
host tests do not replace destructive physical rollback tests.

The authorized post-update HTV405 request was 600 seconds at 12:38:48 UTC,
observed closed at 12:49:00. The later HTV145 request was 60 seconds at 12:49:15,
observed closed at 12:50:20. Fresh reports decoded the requested durations;
counters advanced 0→1 and 129→130. There were no repeated opens, manual closes
or resynchronizations. Observation timestamps are not exact mechanical timing.

Front Yard's earlier interrupted downloads persisted after moving it near an
AP (-54 dBm). Instrumentation then isolated a ten-second whole-image server-write
timeout. Gateway 0.37.1 introduced bounded streaming; the same affected radio
subsequently passed download, healthy boot and ownership restoration.
See [OTA hardware evidence](OTA_HARDWARE_VALIDATION.md).

The September 12 Pi move also produced a recovery observation: radios retained
uptime and local ownership, reauthenticated after the gateway returned, and
fresh reports resumed. Offline telemetry is not buffered; successful reconnect
does not establish complete report retention or power-loss qualification.

## Device protocol and control evidence

Current wire-format definitions are in [protocol_documentation](../protocol_documentation/).
Historical experiments remain in [RF capture notes](RF_CAPTURE_NOTES.md).

| Finding | Retained evidence |
|---|---|
| HCS026 direct reports without SDR: 208 observations over about 11 hours, max gap 469.581 seconds | [Sensor recovery](fixtures/hcs026_direct_reporting_recovery_20260906.json) |
| HTV405 idle counter assignment, bounded recovery and morning synchronization | [Sync design](HTV405_MORNING_SYNC_DESIGN.md) |
| HTV145 first custom-ID idle-anchor rejection; re-pair alone did not prove authority | [Rejected anchor](fixtures/htv145_custom_identity_idle_anchor_20260907.json) |
| HTV145 first custom-ID open 81/90, then 82/90 open and 83/10 early close, with independent idle | [First-open qualification](fixtures/htv145_custom_identity_first_open_20260908.json) |
| HTV145 non-watering fixed-zero recovery | [Recovery exchange](fixtures/htv145_idle_result3_counter_recovery_20260906.json) |
| HTV145 counter persistence and stop after radio/gateway restart without replay | [Restart recovery](fixtures/htv145_restart_recovery_20260906.json) |
| Standard firmware/control promotion, including automatic and early stop | [Promotion exchange](fixtures/htv145_standard_firmware_control_20260906.json) |
| First scheduled front-garden local run: September 9 07:00:01 through 07:35:03, 35 minutes | [Scheduled run](fixtures/htv145_scheduled_watering_20260909.json) |

HTV145 association was operational at partial terminal completion; that is not
proof of full six-stage enrollment or arbitrary command-order semantics. Later
firmware restored the full receive configuration after TX, and the gateway
preserved nonzero usage bytes in the narrow result-3 matcher. Fresh pairing now
initializes the first counter once without automatically watering; mandatory
two-run unlocks were removed, while response/owner/readiness checks remain.

## HA and independent-install evidence

September 8 rendered native-flow checks covered categories, sensor/HTV405 menus,
friendly radio labels, preserved radio/timeout selections, review Back and
pre-arm cancellation. No pairing or watering was started. “Add with setup code”
was removed; native menu actions are not footer Back buttons on every screen.
Later generic single-zone onboarding still needs separate physical/UI acceptance.

The default-notification audit and optional blueprints are complete. See
[notification semantics](../docs/ALPHA_NOTIFICATIONS.md). Snapshot regressions
cover duration, deduplication, failures and unknown state. Physical phone delivery
and rendered new-user setup are distinct from implementation/deployment.

Real HA Core 2026.7.0 and 2026.9.1 qualification exercised an empty TLS gateway,
Supervisor-style discovery, duplicate suppression, model menus, no-radio
feedback, reload and removal. Source-package smoke checked empty fresh/restart
storage without household credentials or RF calls. HACS and hassfest passed.
See [installation evidence](../docs/ALPHA_INSTALL_VALIDATION.md). The disposable
Mac test VM/containers were removed after qualification; the CI harness remains.

## Observation collection versus final soak

The completed 72-hour window contained 874 snapshots and 66,569 events, no
collector gaps/errors, six fresh sensors at every sample, stable configured ACK
owners and eight device identities. Copy hashes and SQLite integrity passed.
Right Bed's maximum observed gap was 520.254 seconds.

There were multiple firmware versions, 83 connected events, two disconnects,
11 reboot observations and a single-zone reporting gap overlapping handoff work.
It is recovery/observation evidence, not an unchanged-release qualification.
See [the full collection review](RELIABILITY_COLLECTION_REVIEW_20260910.md).

## Cleanup decisions

Post-alpha source work (integration 0.18.1) fixes manual TLS setup's missing
credential field and uncaught credential validation error. A focused regression
went red before the change and green afterward. Real HA Core CI run
[34718676952](https://github.com/fholgado/rainpoint-local/actions/runs/34718676952)
passed manual setup, failed authentication, reload/removal and actual backend
notification delivery/deduplication/dismissal on both qualified Core versions.
The observations are synthetic; no RF or mobile service was called. Rendered
frontend and physical qualification remain separate. Alpha 1 artifacts and
the live household installation were not changed by this pass.

The roadmap audit separates implementation from physical acceptance. Metadata,
issue templates, notification audit, migrations, unified builds and Alpha 1
publication are complete. Fresh install, battery rejoin, repeated pairing,
coexistence, on-air ACK timing and final soak remain open. Invariants such as
authentication and at-most-once opens are continuing constraints, not one-time
checkboxes. No capture was deleted to shorten the roadmap.
