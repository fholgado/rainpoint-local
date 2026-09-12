# RainPoint Local project roadmap

Last reviewed: 2026-09-11

This is the only live project-status checklist. Device references describe
current protocol facts; research records and fixtures preserve experimental
evidence. A transmitted frame alone never closes a physical acceptance gate.

## Current work order

### Scheduled garden duration correction

- [x] Reproduce and remove the installation's obsolete `[1, 2, 20]` scheduled
  duration filter: selecting 21 previously submitted 20 to both watering and
  notification paths. The tested adapter preserves all whole minutes 1–60 and
  fails invalid settings through the existing valve-duration guard. Manual-run
  scripts, RF encoding, schedules and moisture/rain decisions are unchanged.
- [x] Activate the corrected automation. HA configuration validation passed,
  then the September 10 coordinated rollout restarted Core successfully and
  reloaded the on-device 1–60 whole-minute adapter. The SSH app is not permitted
  to proxy Core API calls (the earlier HTTP 401), so no permission expansion was
  made. Check the next authorized run's notification against its duration;
  no extra irrigation was triggered for this template change.

### Alpha cohort preparation

- [x] Implement per-association single-zone storage and eight-owner radio slots.
  Schema 25 migrates the old shared-route key without discarding counters,
  reservations, diagnostics or qualification. Each association retains its own
  command/ACK state; overlapping transmissions are rejected. Temporary-database
  isolation/migration and native slot-selection tests pass. Deployed September
  10 with the coordinated release below; multiple physical single-zone valves
  on one node still require qualification.
- [x] Implement TLS-PSK for radio sessions, HA management and OTA downloads.
  Existing credentials are retained, invalid credentials/plaintext are rejected,
  and current HA client tests exercise encrypted reads, writes and token rotation.
  Python 3.13+ is required; CI and the container runtime assertion are updated.
  Deployed in the coordinated production rollout below.
  Local validation: 582 Python tests passed (two skipped), native C++ protocol
  tests passed, and the unified ESP32 firmware built successfully. The container
  image passed CI and the HA aarch64 build; physical TLS/OTA results follow below.
- [x] Qualify operational TLS and HTTPS OTA on the spare radio. September 10:
  the unified candidate authenticated with its existing node credential using
  `PSK-AES128-GCM-SHA256`, received real RF telemetry and retained roughly
  193–196 KB free heap (observed minimum about 185 KB). An actual HTTPS OTA
  from `0.18.0-alpha.1` to `0.18.0-alpha.2` verified all 1,090,784 bytes,
  passed healthy-boot confirmation and reconnected encrypted after a separate
  remote reboot in 18.1 seconds. This used an isolated Mac gateway/new database,
  without pairing, valve commands or ACK-owner imports; both garden radios
  stayed healthy. Receive-only maintenance intentionally blocks OTA, so the
  spare was returned to ownerless normal mode for the download. With the user's
  explicit approval, its complete saved flash was then restored and verified;
  it reconnected authenticated to production HA on `0.17.0`, with no ACK owners
  and no armed pairing window. The temporary Mac gateway was stopped. Recovery
  backups and qualification evidence are preserved in the private, Git-ignored
  `captures/tls-bench-20260910-private/` directory.
- [ ] Complete longer-soak and physical multi-valve-per-node isolation checks.
  Authorized post-update actuation passed for both valve families September 11
  (600/60 seconds; evidence below). Initial ACK/report continuity and those runs
  do not prove longer-term stability
  or concurrent ownership of multiple physical single-zone valves on one radio.
  See `docs/ALPHA_BUNDLE.md`; never mix plaintext/TLS operational versions.
- [x] Qualify the copied production database before coordinated cutover. The
  September 10 backup actually uses schema 23; migration to 25 preserves all
  existing values across 18 tables, including counters, ownership, credentials
  and transactions. Only intended association keys and the explicit RF endpoint
  column change; SQLite integrity passes. The rollback archive is SHA-256
  verified on the Mac and retained on HA. Eight superseded local deployment
  backups were removed, recovering 12.8 GB (14 GB free).
- [x] Resolve release preflight failures without changing RF pairing. A test's
  unlocked private-store read raced the authenticated peer on one SQLite
  connection; applying the gateway lock passed 20 amplified repetitions. The
  582-test suite passed with two optional skips, plus the added watchdog
  regression and native protocol tests. Correct version metadata and use a
  Supervisor TCP watchdog because its HTTP probe cannot authenticate TLS-PSK.
  All five CI jobs passed for release revision `7a3529e`.
- [x] Deploy gateway `0.38.0`, integration `0.18.0`, and unified firmware
  `0.18.0` to all three radios (September 10, 21:52 EDT). All three verified
  the 1,090,768-byte image, reconnected with existing credentials over
  `PSK-AES128-GCM-SHA256`, and confirmed healthy boots. HA's persisted firmware
  entities show installed/latest `0.18.0`. All eight device IDs and six sensor
  ACK assignments are unchanged. Fresh post-cutover reports arrived from all
  six sensors and both valves; sensor/four-zone ACK failures remain zero, and
  the retained single-zone counter 129 and four-zone next counter 1 survived.
  Plaintext and invalid-PSK management connections are rejected. Both valves
  remain idle; no pairing or watering commands were sent. Source/config/image
  recovery material remains private on HA and in the verified Mac backup.
  A second OTA on the ownerless test node used HTTPS through the live gateway,
  rebooted successfully, and reached `confirmed / gateway_and_radio_healthy`;
  garden ACK ownership remained unchanged throughout that test.

The user now prioritizes an independent alpha for builders of their own radios,
covering **HCS02x sensors, HTV145 single-zone and HTV405 four-zone valves**.
This is a separate `rainpoint_local` installation, not a cloud-integration merge.
Do not drop valve coverage to a sensor-only alpha. Dry valve verification comes
before supervised live irrigation; the alpha is not yet a broad stable release.
These launch tasks complement, rather than mark complete, the physical gates below.

- [x] Merge the CI-green OTA fix and completed collection review into main
  (PR #11). Gateway 0.37.1 was already deployed; merging changes no live RF state.
- [x] Add `GETTING_STARTED.md` for independent builders: exact hardware/wiring,
  separate app/HACS installs, Wi-Fi adoption, all supported pairing paths,
  valve verification, updates, recovery and redacted feedback. Refresh README
  entry points and clarify the unused GDO2 wire. The guide describes current
  source installation and explicitly flags unverified distribution/UI paths.
- [x] Merge alpha setup, packaging and optional-alert preparation (PR #12).
  All Python, firmware and container CI checks passed; no release or live deploy.
- [x] Review the shorter agent-assisted README/getting-started draft: the agent
  handles repository installs and radio flashing/adoption, then hands device
  pairing to the user in HA. Gateway installation uses the HA app repository,
  not HACS; clean-install qualification remains separate. User approved the
  direction, with the follow-up changes below; not published yet.
- [ ] Complete and qualify the revised single-zone onboarding without mandatory
  two-run experiments. Draft separates ACK-owner provisioning from physical
  verification and retains real counter/radio/response gates. Fresh accepted
  pairing now initializes counter 1 (`0x81`) once, atomically with consumption of
  its pairing evidence. Provenance stays pairing-derived until a matching positive
  response. Regression coverage checks first open/advance, replay, restart, old
  onboarding records, expiry, owner transfer and failed-first-command behavior.
  Deployed September 10; fresh end-to-end HA pairing/physical acceptance remains
  outstanding and was not exercised against the installed irrigation valves.
- [x] Implement one-shot HTV145 fresh-pairing counter initialization and expose
  pairing-derived versus response-confirmed provenance to HA. Preserve the RF
  waveform and normal duration path; never water automatically during setup.
  Local validation: full Python suite ran 574 tests successfully (two optional
  skips); native C++ protocol regressions passed. The authenticated onboarding
  HTTP tests also passed after adding the first-counter assertions. Deployed in
  the September 10 coordinated rollout; fresh physical acceptance remains above.
- [ ] Validate default HA watering notifications on a clean HA instance. The integration
  emits confirmed start/stop, failed request and overdue notices automatically;
  mobile forwarding remains optional. Snapshot tests cover dynamic durations,
  duplicate reports and unknown state. Deployed in the September 10 coordinated
  rollout; clean-instance delivery and physical/UI acceptance remain outstanding.
- [x] Establish an isolated ARM64 HA Container qualification environment on the
  Mac (September 11), without production data, host mounts or radio listeners.
  Existing real-Core qualification passed on HA 2026.7.0 and 2026.9.1 from
  `d31b516`: authenticated TLS setup via supplied Supervisor-style discovery,
  duplicate discovery, both valve model menus, no-radio feedback, reload and
  removal. Extracted-source fresh/restart smoke also passed. CI now runs that
  existing qualification against both versions. This is not real Supervisor,
  HACS installation, rendered-flow acceptance or physical commissioning.
  A separate fresh frontend reaches its onboarding page via Mac loopback only;
  the test network has no default route. See `docs/ISOLATED_HA_TESTING.md` and
  `docs/ALPHA_INSTALL_VALIDATION.md` for isolation and evidence boundaries.
  The full local Python suite passed: 596 tests, two optional skips.
- [ ] Qualify manual standalone TLS setup before advertising HA Container as
  an installation path. Source inspection found that the manual form accepts
  host/port but not the gateway credential; the successful automated test
  supplies it through Supervisor-style discovery. Reproduce the public form,
  then fix and regression-test authenticated setup without adding credential
  entry to normal Supervisor discovery or weakening TLS. This does not block
  existing HA OS installations, but does block standalone fresh-install claims.
- [ ] Validate the guide on a clean HA OS installation without household
  databases, catalogs or tokens: custom app repository and HACS installation,
  discovery, new radio adoption and generated gateway identity. Confirm declared
  HA minimum and both advertised app architectures, or narrow the alpha matrix.
- [ ] Finish rendered native HA onboarding and physical acceptance for **both
  valve families and sensors** on the unified image. Keep paired versus
  control-qualified outcomes explicit. Check removal/re-enrollment, cancellation,
  no-radio/offline-radio feedback and unsupported-model rejection. Record any
  remaining battery-rejoin limits in alpha notes instead of promising recovery.
- [ ] Prepare an immutable alpha tag and version compatibility table, source
  bundle, first-USB-flash artifacts with offsets/tool instructions, OTA artifact
  and installable local catalog, checksums and rollback notes. The stale CI
  manifest label is fixed: version and actual flash inputs now come from the
  unified build. No release/tag has been published.
  Unattended preparation now implements a single source firmware version,
  PlatformIO-generated receipt of actual flash parts/offsets, and a local alpha
  bundle with source, USB/OTA images, catalog, compatibility metadata, checksums
  and recovery instructions. Dirty/stale/mixed builds are rejected; previews are
  explicitly marked dirty. Production boundary and extracted-source smoke checks
  run before packaging; CI checks repeat-package byte identity without uploading
  the bundle. This is packaging infrastructure, not publication or physical
  first-flash qualification. External binary uploads require explicit approval.
  Validation: unified PlatformIO build and real receipt succeeded; local preview
  archive/source smoke passed and repeated archive bytes matched; 542 Python
  tests passed (two optional skips). No radio was flashed and no release created.
- [ ] Validate HACS metadata/distribution and app repository discovery; select
  codeowners/contact, add a redacted issue template and test the support workflow.
  Decide the supported update channel so testers do not unknowingly install main.
  Offline checks now enforce one separately named integration, required manifest
  fields, owner/contact and consistent HA minimum; an alpha issue form covers
  all three device families and redaction. Full HACS acceptance is not proven.
  September 10: original integration-local 256/512 PNG icons and editable source
  are added, with HACS and hassfest CI jobs (no ignored validation checks).
  Official validation and clean-install acceptance must be recorded separately;
  see `docs/HACS_DISTRIBUTION_REQUIREMENTS.md` for the distribution contract.
  Initial official HACS checks passed. Hassfest caught an existing undeclared
  `network` dependency in radio adoption; the manifest now declares it and a
  source/manifest regression reproduces the omission. A subsequent validator
  pass caught legacy manifest key ordering; that is corrected and tested too.
  Both official HACS and hassfest checks passed on `6541df2` after those fixes.
  Full PR checks must pass before merge; a clean HA OS installation, support
  workflow and intentionally selected release/update channel remain open.
- [ ] Audit what a fresh tester actually gets for failed irrigation, stale
  moisture, counter synchronization and offline alerts. Provide generic optional
  setup/examples where needed; the household dashboards/watchdogs are not
  automatically installed safeguards. Require visible valve-owned start/stop
  evidence before asking testers to depend on scheduled watering.
  Audit complete: `docs/ALPHA_NOTIFICATIONS.md` distinguishes what exists from
  household-only safeguards. Optional observation-only blueprints provide stale
  report and exposed valve-problem alerts, with persistent HA records before
  optional mobile actions. Template regressions cover age/timezone/unknown values,
  duplicate changes and new failures. Clean HA import and actual phone delivery
  remain open. The audit identified an HTV145 persistent-failure gap, addressed
  by the implementation below. No alert blueprint was deployed to the live house.
  September 10 implementation (gateway 0.37.2/integration 0.17.1): durable
  HTV145 last-command diagnostics now cover runtime preflight refusals, dispatch
  errors, negative responses and confirmation timeouts. IDs/errors survive later
  telemetry and restart; duplicates cannot overwrite pending work. HA exposes
  Control request status and valve attributes and refreshes after API failures.
  Requests rejected inside HA or never reaching the gateway remain service
  errors, not invented gateway transactions. No RF/pairing/counter behavior was
  changed. Clean HA alert delivery and deployment remain unverified.
  Validation: 554 Python tests passed (two optional skips), both native protocol
  binaries passed, and the isolated source-package fresh/restart smoke passed.
  Additional maintenance regression confirms sync leaves watering diagnostics
  unchanged. Gateway rollback from schema 24 requires a pre-upgrade DB backup.
  Validation: the complete Python suite passed 547 tests (two optional skips),
  including the shipped alert-template and distribution-metadata regressions.
- [x] Implement and qualify the alpha security boundary (September 11).
  Operational TLS passed the September 10 coordinated deployment. Initial
  commissioning AP and HTTP adoption remain trusted-network-only by user
  direction; no Internet port forwarding. Publisher signing is enforced by
  gateway 0.39.0 and radio 0.19.0; see `docs/FIRMWARE_SIGNING_DESIGN.md`.
  The private key exists only in the protected GitHub environment. Main requires
  PR/CI checks; signing requires maintainer approval, main-only deployment and
  no admin bypass. User-approved run 34585252074 signed firmware from 5dc0c5fc;
  no GitHub release was published.
  Hardware evidence: the spare received all 1,097,648 bytes of the approved image,
  reported `verified_publisher_and_sha256`, rebooted without USB intervention,
  reauthenticated and reported `confirmed` / `gateway_and_radio_healthy` by
  12:00 UTC. This was a genuine 0.19-to-0.19 signed OTA after a separately verified
  legacy TLS bootstrap. Image SHA-256 starts `22d57e428c4b0285`.
  Gateway 0.39 is deployed; all eight device IDs, six sensor ACK assignments and
  valve endpoint/control-counter fields survived. Both valves were idle and all
  devices available afterward. Deployed raw-URL OTA returned HTTP 400 without
  dispatch. Irrigation-node promotion was completed separately below.
  Host evidence: 596 Python tests passed (two optional skips), all six CI jobs
  passed, and actual OTA code linked to Mbed TLS rejected 26 invalid inputs
  before download/flash and aborted a tampered download before activation.
  Negative signature flash tests are host-instrumented, not hardware injections.
  Trial fixes: install the verifier dependency in isolated firmware-packaging
  CI, and accept `firmware_signed_ota` in the authenticated hello allowlist while
  requiring it for update dispatch (PRs #14/#15). A real socket test reproduced
  `node_rejected` before the fix. USB serial opens reset this ESP; uninterrupted
  capture isolated the successful software reboot from diagnostic resets.
- [x] Coordinate remaining irrigation-node promotion to signed firmware 0.19.
  September 11: Front Yard and Vegetable Garden were upgraded individually with
  the approved image (SHA-256 `22d57e428c4b0285…`); both reported `confirmed` /
  `gateway_and_radio_healthy` before proceeding. A temporary legacy runtime with
  only the signed-capability hello backport kept mixed-version owners connected;
  its 40 isolated socket tests passed. The signed-only 0.39 gateway and catalog
  were then restored; all 41 deployed gateway files match main source.
  At 12:27 UTC all three nodes were authenticated over TLS on 0.19.0, all eight
  device IDs and six sensor ACK assignment objects were preserved and available,
  and both valves were idle with unchanged control counters and start controls
  available. Current gateway data was backed up and its Mac copy hash verified.
  Front Yard Wi-Fi was weak (-83 to -85 dBm) despite a successful update/reconnect.
  No watering was triggered during promotion. Separately authorized post-update
  tests then passed through the normal gateway control API: Vegetable Garden
  zone 1 received one 600-second request at 12:38:48 UTC and was observed closed
  at 12:49:00; only afterward Front Garden received one 60-second request at
  12:49:15 and was observed closed at 12:50:20. Both durations were decoded back
  from fresh valve reports; these are observation times, not exact physical
  actuation timestamps. Counters advanced 0→1 and 129→130 respectively, without
  resynchronization, repeat watering requests, or manual close commands. Both
  valves were idle with no pending commands afterward; all eight devices and
  three radios remained available. This validates the gateway/firmware control
  path, not a separate dashboard-click test. Release publication remains a
  separate explicitly approved action.
- [x] Remove obsolete app-level supervised-control and dry-acceptance switches.
  Normal controls still require an evidenced association and ready owner/counter;
  standalone research probes remain separate. No RF builders or pairing changed.
  September 11: 583 Python tests passed (two skips). The extracted package starts
  its actual TLS CLI with an empty database, rejects plaintext/wrong keys, and
  preserves its generated RF identity across restart. Source only; not redeployed.
- [x] Qualify actual fresh HA Core setup in isolated CI. The new container harness
  covers discovery, duplicate suppression, model menus, missing-radio feedback,
  reload and removal without household credentials or RF transmissions. The real
  HA Core 2026.9.1 job passed on `a1feb43` (run 34580019946), after correcting the
  harness to initialize HA's full bootstrap. It does not replace HA OS/HACS,
  rendered frontend, physical pairing or default-notification delivery checks.
- [x] Classify current capacity and compatibility boundaries for alpha. Fixed
  per-radio pools are resource budgets, not a discovered RF/global gateway limit:
  eight sensor ACK owners, four HTV405 ACK owners, eight HTV145 associations.
  Keep capacities unchanged until higher-load tests justify raising them; document
  the source constants. There are no external installs to support with speculative
  old-version fallbacks. Retain migrations needed by this installation's database
  and backups; new alpha installs should use the matching release stack.
- [ ] Record independent-house results for sensors and both valve families,
  including RF reporting/ACK continuity, actual watering duration/stops and
  overnight counter recovery. Preserve first-house evidence but do not use it
  to close fresh-install or independent-site acceptance.

### Existing qualification sequence

The user prioritized single-zone promotion ahead of the selected hardening work.
The verified association now uses standard firmware and HA controls, preserving
bounded commands, counter recovery and evidence-based state. The user connected
the single-zone valve to the front irrigation on September 8. Its dashboard,
manual run, scheduled decision and watchdog now target the local valve.

September 9: the user confirmed scheduled front-garden watering, and retained
valve observations confirm 07:00:01 open through 07:35:03 idle (35 minutes).
Next: finish rendered HA wizard/UI checks and physical automatic onboarding,
then qualify the consolidated firmware on all production owners.
Firmware qualification must cover persisted association/counter restore without
startup actuation, valve-confirmed bounded controls, ACK/report continuity and
the overnight check. New-ID pairing alone does not qualify control ownership.

The selected unattended implementation/review pass is complete (original list numbers):

- [x] **1.** Audit production defaults: empty fresh installs, accepted identity
  recovery, explicit ACK routes, and a regression guard against household IDs.
- [x] **2.** Move the unused bench coordinator out of the app and remove the
  manual phase-string parser; retain authenticated counter restoration and
  qualification tools still required by open physical gates.
- [x] **4.** Apply known sensor events directly in HA, retain authoritative
  snapshots for valves/topology, handle cursor resets and retry failed snapshots.
- [x] **5.** Keep accepted pairing visibly finalizing until its selected radio is
  disarmed and available; optional-tail failure cannot erase terminal acceptance.
- [x] **6.** Add a pre-transmission review with model/radio Back choices and Cancel;
  preserve selected values and scope cancellation to the flow's own command.
- [x] **7.** Add config version 3 migration with stable identities/user options,
  canonical credential storage and refusal of unsupported future versions.
- [x] **11.** Review retained four-zone staleness evidence: time, reboot/reconnect
  and ACK failures remain confounded. No additional watering was authorized or run.
- [x] **12.** Review auth boundaries; bound HTTP concurrency, reads, event windows
  and setup attempts; persist rotated tokens privately and atomically.
  Encrypted sessions and signed OTA remain publication gates below.
- [x] **15.** Add deterministic source archives, isolated fresh-install/restart
  smoke tests, a digest-pinned base image and a CI production-container build.
- [x] **16.** Remove merged legacy worktrees/branches and archive superseded
  backups/firmware; retain installed images and explicit rollback releases.
- [x] **18.** Recheck command-phase, shared-counter and battery-field evidence.
  Unsupported battery and arbitrary action-order semantics remain unavailable.

- [x] Inspect the deployed wizard in HA with explicitly user-enabled browser
  access. September 8: both categories, HCS02x and HTV405 models, friendly radio
  labels, radio/timeout preservation, category return and pre-arm cancellation
  were exercised in the rendered UI. No pairing or watering was started; all
  three radios remained connected, normal and unarmed. HA's stale browser
  connection recovered with a page refresh, without a server or radio restart.
- [x] Deploy and verify the selected native pairing navigation improvements.
  Integration 0.16.2 renders Next for model and radio forms and Back on review.
  Live September 8 verification covered sensor and valve flows, review Back
  retaining a non-default radio/300-second window, and Change device model
  returning to categories. No Start pairing was clicked. These are native menu
  actions, not footer Back buttons on every screen. The user deferred a dedicated
  wizard; its remaining requirement is recorded in the backlog below.
- [x] Verify removal of "Add with setup code" from the management menu in HA.
  The user requested removal on September 8. New radios use discovery and BOOT
  confirmation; existing registrations/credentials are unchanged. The hidden
  legacy callback remains for an already-open manual registration flow, not as
  a normal sensor/valve pairing option.
  Validation: 524 Python tests passed (two optional skips), native C++ protocol
  test and deterministic package smoke passed, HA configuration check passed,
  and deployed file hashes matched. Only HA was restarted; both valves remained
  idle, all six sensors available and three radios connected/normal/unarmed.
  Record this HA restart as an intervention in the ongoing mixed-version soak,
  not uninterrupted final-release uptime.
- [x] Consolidate root-level Python regression tests and shared fixtures under
  `tests/`. CI and contributor instructions now use automatic discovery; focused
  module runs remain supported. September 8 validation: all 533 Python tests
  passed (two optional skips), with test logic unchanged. Native firmware tests
  remain under `firmware/rainpoint_bridge/tests/`.
- [x] Complete the September 9 standard firmware 0.17.0 fleet installation.
  Superseded by the signed 0.19.0 rollout and post-update watering tests above;
  unchanged-release soak and fresh onboarding remain their own open gates.
  Front Yard's prior 0.16.2 custom-ID open/automatic stop/early-close evidence is
  retained, but does not qualify fresh onboarding or the new fleet version.
  September 9: OTA Test and Vegetable Garden installed the identical verified
  0.17.0 artifact, reconnected, passed gateway/radio health confirmation, and
  received new RF frames. Vegetable Garden restored four sensor ACK assignments
  and one valve ACK assignment. Front Yard's three identical transfers stopped
  at 921639, 915895 and 938871 of 963120 bytes (`download_interrupted`); none
  booted a candidate. It remains connected on 0.16.2 with its two sensor ACK
  assignments and authenticated single-zone counter intact. Do not call the
  fleet consolidated yet; investigate interrupted transfer or use USB recovery.
  A later user-approved retry after moving Front Yard beside an AP also failed:
  Wi-Fi improved from -76 to -59/-54 dBm, but the same artifact stopped at
  852711 of 963120 bytes. No candidate boot occurred; 0.16.2 remained connected.
  Better RSSI did not resolve the interruption; weak signal alone is insufficient
  to explain it. The relocation also power-cycled the node, so this is not an
  isolated signal-strength experiment.
  Resolved later September 9 by gateway 0.37.1: instrumented whole-image HTTP
  writes timed out after 10.001 seconds. Bounded streaming (16 KiB writes,
  ten-second per-write limit, 120-second overall deadline, two download slots)
  fixed the real-socket regression and the next identical Front Yard update.
  Front Yard booted 0.17.0 after approximately 18 seconds and confirmed gateway
  and radio health by 76 seconds, with no pending rollback, two restored sensor
  ACK assignments, zero ACK failures, fresh RF frames and retained authenticated
  single-zone counter. All three radios now run 0.17.0; no post-update watering
  was requested, so this completes fleet installation, not functional soak or
  fresh onboarding qualification. Gateway restart and OTA are soak interventions.
  No pairing or extra watering was triggered during this deployment.
- [x] Diagnose and fix late Front Yard OTA truncation without weakening image
  verification or rollback. Gateway 0.37.1 is deployed; the original affected
  node passed the same-image update after the server fix. Validation: 536 Python
  tests passed (two optional skips), native protocol tests and package smoke
  passed, deployed source hash matched. Evidence and limits:
  `research/OTA_HARDWARE_VALIDATION.md`.
- [ ] Complete normal HTV145 onboarding: discover its factory ID on the selected
  radio, retain the custom gateway identity, persist the accepted pairing owner,
  and expose separate paired/control-verification states in HA. Verification
  must require a user-requested bounded watering; pairing alone must not actuate.
  Fresh-pairing counter initialization is provisional, not response confirmation.
  Keep the frozen counter-2 RF sequence and
  existing qualified associations unchanged; a sixth transcript row is not a
  prerequisite for independently proven controls.
  September 8 implementation: an isolated discovery helper and native regression
  now reject malformed/non-announcement frames and prove every generated reply
  matches the explicit-ID profile byte for byte. Counter-0/1 announcements still
  receive no assignment and counter 2 retains the existing response.
  Validation: both native C++ protocol tests passed; all 524 Python tests passed
  with two optional skips.
  After explicit approval, candidate gateway 0.37.0, integration/firmware 0.17.0
  connect discovery to the unchanged pairing exchange and advertise the model
  only to compatible radios. Accepted pairing records the selected owner; an
  authenticated, session-scoped verification flow confirms old-owner revocation
  before configuring a new owner. That earlier implementation permitted two fixed one-minute runs,
  including at most one captured first-open initialization, with positive valve
  replies and independent automatic/early-stop evidence required for completion.
  The HA flow exposes progress/failure, supports finishing without testing and
  returning later, and prevents duplicate starts or old-dialog cancellation of
  a newer pairing. The September 10 review draft supersedes mandatory tests with
  owner setup and a one-shot pairing-derived counter; see the current alpha gate
  above. Interrupted tests are not replayed. Existing qualified
  installations are not reset on upgrade. The original one-single-valve slot is
  superseded in the September 10 candidate by per-association state and eight
  firmware slots, without displacing a different valve.
  Candidate validation: all 533 Python tests passed (two optional skips), both
  native C++ protocol tests passed, unified firmware 0.17.0 built successfully,
  and the final deterministic package passed isolated fresh-install/restart smoke
  checks. HA callbacks were tested with stubs; the new screens have not yet been
  verified in the live HA frontend. No physical controls were sent by these tests.
  The user separately confirmed successful front-yard watering on the installed
  version; that does not close automatic onboarding acceptance. September 9:
  gateway 0.37.0 and integration 0.17.0 are deployed with a verified partial app
  backup and private source/config-entry rollback copies. Package smoke and HA
  configuration checks passed; deployed implementation hashes match the tested
  archive. Both valves retained idle/readiness and the single-zone counter.
  The pairing API now advertises HCS02x, HTV145 and HTV405 model choices; no
  pairing was armed. The integration's real catalog parser accepted that live
  response with automatic HTV145 discovery enabled. Browser-control tools were
  unavailable in this session,
  so visual wizard acceptance remains open. Physically verify discovery →
  pairing → consent → bounded controls from HA, cancellation/restart, and
  retained owner health before closing this item.

- [x] Correct the installation's obsolete SDR receiver configuration after its
  move to the Mac. With working Wi-Fi nodes, `/health` repeatedly returned 503
  because the absent `rtl_433` receiver exited. Changing only transport to
  `network` and restarting changed that same check to 200/healthy, retaining
  gateway identity, device associations and all three authenticated radios.
  No RF sequence, credential, schedule or control behavior changed.

Latest verified reference deployment (September 11): gateway 0.39.0, integration
0.18.0, and signed unified firmware 0.19.0 on OTA Test, Vegetable Garden and
Front Yard, with healthy-boot confirmation. Both authorized post-upgrade watering
tests passed as recorded above. Fleet soak and physical onboarding gates remain open.
Software/research completion does not resolve the physical or publication gates.

The existing 72-hour collector continues independently. Software completion does
not close physical gates requiring pairing gestures, power changes, SDR, or a
new watering budget. Later phases remain ordered below unless this selected
sequence or irrigation reliability requires otherwise.

## Established baseline

- [x] Preserve one canonical HA identity per physical device and suppress
  forgotten endpoints. Pairing registration now reuses an established valve
  ID; the duplicate single-zone device was removed with working entity IDs,
  history, ACK owner, counter, and schedules preserved.
- [x] Support one canonical checkout and one PlatformIO environment. Both valve
  families use the standard firmware; production controls require an evidenced
  association. Deployment does not replace the remaining physical qualifications.
- [x] Pair and recover independent HCS026 identities, persist a single ACK owner,
  and pre-fill known devices' saved names and HA areas on re-addition.
- [x] Complete three HA-initiated HTV405 generated-identity enrollments and decode
  all four zones with whole-minute durations from 1 through 60.
- [x] Validate HTV405 fixed-zero idle counter assignment, bounded authenticated
  control, rollover, automatic stop, and Zone 1 early stop.
- [x] Validate HTV145 partial-association dry open, automatic stop, early close,
  persistent selector-6 controls, and non-watering fixed-zero counter recovery.
- [x] Expose both valves' morning-sync controls. One-zone retries are bounded to
  three total attempts, each requiring new owner idle evidence after failure.
- [x] Remove unsupported HTV405 usage entities and the one-zone phantom zones.

Current evidence: [sensor fixtures](research/fixtures/),
[HTV405 sync](research/HTV405_MORNING_SYNC_DESIGN.md),
[HTV145 recovery](research/fixtures/htv145_idle_result3_counter_recovery_20260906.json).
Historical trial sequences remain in [RF capture notes](research/RF_CAPTURE_NOTES.md)
and version history, not this checklist.

## Phase 1 — HA device lifecycle

### Shared UI and sensors

- [ ] Return to the integration device list after removal. HA's supported
  removal hook has no frontend-navigation callback; do not emulate this with
  unrelated backend mutations.
- [ ] Complete three consecutive pair → report → remove → re-pair cycles on
  unchanged final firmware, including an installed sensor and both test sensors.
- [ ] Verify physical removal clears entities, suppression/re-enrollment state,
  and ACK assignment; re-pairing must not create a duplicate.

### Four-zone valve

- [ ] Qualify the retained RX/FIFO recovery correction during a fresh pairing.
- [ ] Remove through HA, verify all four controls, durations, association, and
  routing are cleared, then re-pair without duplicate devices.
- [ ] Physically qualify the implemented effective/raw pairing outcome split:
  terminal acceptance remains completed when the optional tail later times out;
  pre-terminal timeout remains failed. Preserve raw diagnostics and do not cancel RF.
- [x] Implement **Finalizing pairing** while the optional tail is armed; preserve
  backend command readiness guards. Rendered/physical qualification remains above.

### Single-zone valve

- [x] Remove the new-controller-ID HA handoff dependency on an existing catalog
  link. Command-scoped captured-report replay now preserves the HA device,
  decodes the first report, retires the old route, and survives gateway restart.
  Invalid/unrelated/session-expired reports and old control authority are rejected.
  The frozen radio pairing sequence is unchanged (gateway 0.36.1).
- [x] Physically verify new-ID handoff and subsequent ACK/control enrollment
  through the chosen node. The September 7/8 partial 5/6 exchanges preserved the
  existing HA device and disarmed normally. September 8 bounded qualification
  and the corrected standard-firmware recovery/control trial below established
  command authority and owner telemetry/ACK operation without further re-pairing.
- [ ] Verify sustained reporting and control on this custom-ID association.
  The successful bounded tests do not qualify overnight persistence, battery
  rejoin, repeated new enrollments or full six-stage terminal completion.
- [x] Bridge fresh local pairing to first-control qualification without a stock
  command or copied counter. Previous dry acceptance required a passive command
  on the same link, and runtime enrollment requires a positive exchange; neither
  could bootstrap a new custom-ID association through that API. Use a
  separately gated, bounded qualification state with explicit old-owner revocation,
  fresh owner idle evidence, close-only counter establishment, and valve-confirmed
  control before enabling public commands. Preserve the proven RF pairing prefix
  and distinguish provisional test ownership from qualified runtime ownership.
  Implementation deployed in gateway 0.36.2: persistent provisional qualification,
  fresh idle anchor, two fixed one-minute runs, response/stop verification,
  public-control blocking and interrupted-test handling. Validation: 510 Python
  tests (two skipped), native protocol tests and isolated release smoke test;
  all radios reconnected and eight device identities remained after deployment.
  Physical qualification remains incomplete; firmware is unchanged. After explicit
  management-token authorization, the old owner confirmed revocation and the new
  owner heard idle telemetry. Its first fixed-zero anchor received result 3 with
  byte 17 `00`, not the qualified `10` layout. Qualification stopped before any
  open, with no authenticated counter. Preserve this rejection boundary; compare
  fresh-association setup and command-phase evidence before proposing an isolated
  bootstrap probe. Do not generalize the anchor decoder from a negative reply.
  [Captured qualification rejection](research/fixtures/htv145_custom_identity_idle_anchor_20260907.json).
  The captured-exchange regression and full 511-test suite pass (two skipped),
  as do native protocol tests. Research controls are disabled again; the selected
  provisional ACK owner remains configured, with public watering blocked.
  September 8 unchanged re-pair follow-up: the same selected node and firmware
  again received a byte-for-byte identical negative anchor reply after fresh idle
  telemetry (one close-only attempt; no opens). Re-pairing alone did not establish
  command authority. Subsequent idle reporting continued. Research access was
  disabled again; all three nodes reconnected and production four-zone controls
  remained available. Compare command acceptance/setup against a proven positive
  exchange next; do not change the frozen pairing prefix or treat this as RF silence.
  Add a separately compiled, explicit dry first-open trial using the captured
  counter-`81` / 60-second command. The earlier positive association opened before
  idle-anchor testing; initialization and recovery are not proven equivalent.
  Candidate reservation must not authenticate a counter, replay after restart,
  retry automatically, or enable public controls.
  September 8, gateway 0.36.3: the isolated first-open trial on unchanged pairing
  accepted `81/90` and completed automatic idle after a requested 60-second run.
  A second confirmed open (`82/90`) and early close (`83/10`, 20 seconds later),
  followed by independent idle, completed public control qualification.
  No stock command, copied counter or additional re-pair was needed. Public
  authority survived an add-on restart; research access is disabled again.
  [Redacted captured exchange](research/fixtures/htv145_custom_identity_first_open_20260908.json)
  now replays through the qualification state machine. This closes this one
  association's bootstrap/control gate, not repeated enrollment, long-term
  stability, full terminal pairing, or battery rejoin. Front Yard returned to
  standard 0.16.0 with OTA health confirmed; retained authority survived radio
  and gateway restarts, and a normal public 60-second open was acknowledged.
  Post-bootstrap idle-anchor recovery exposed two additional boundaries:
  channel selection did not restore the command-retuned base frequency, and
  the result-3 matcher hardcoded zero usage. A receive-only configuration reset
  restored owner reception immediately. Firmware 0.16.2 restores full RX state;
  gateway 0.36.4 and firmware preserve usage bytes in the narrow error matcher.
  Both issues have red/green regressions; unchanged pairing is retained.
  Physical verification passed on September 8: corrected firmware completed OTA
  health, Front Yard received the nonzero-usage anchor and established counter80,
  the public 60-second open was positively acknowledged, and Front Yard itself
  received automatic idle about63seconds after dispatch and resumed report ACKs.
  Final counter81, idle, public controls ready, research disabled. Captured replay
  covers recovery through the subsequent accepted command and independent stop.
  Validation:519 Python tests pass(two optional skips), native C++ protocol and
  actual receive-restoration call-site regression pass; unified firmware build
  and isolated packaged-gateway smoke pass. Production four-zone owner unchanged.
- [ ] Complete the controlled lifecycle matrix with fresh batteries: repeated
  identical stock reset/enrollment, retained long-press re-pair, and battery
  rejoin. Retain full exchanges, ordering, app metadata, and independent outcomes.
- [ ] Complete the terminal stage after the frozen accepted assignment/configuration
  prefix. Each new boundary requires two unchanged accepted repetitions.
- [ ] Complete three fresh local terminal enrollments on unchanged firmware.
- [ ] Verify stable identity after HA removal/re-pair; treat retained re-pair and
  battery rejoin as separate lifecycle paths.
- [ ] Define HA operational enrollment from valve-owned evidence while clearly
  distinguishing it from full six-stage terminal completion.
  The September 8 UI exclusion was replaced by implemented automatic identity
  discovery and separate consented control verification. The September 9 gateway
  catalog advertises HTV145 only with compatible radio capabilities. Existing
  qualified controls still do not prove the new generic onboarding path; its
  physical and rendered-UI acceptance remains in the current work order above.

Exit: every supported family can pair/remove through HA, with repeated physical
acceptance and one stable HA representation. Dry one-zone control does not close
its full-enrollment gate.

## Phase 2 — persistence, recovery, and coexistence

- [x] Verify Right Bed resumed consecutive accepted moisture reports directly
  from ESP32 radios without SDR assistance. The retained recovery window contains
  208 accepted observations over about 11 hours; maximum gap 469.581 seconds.
  Evidence: [direct reporting recovery](research/fixtures/hcs026_direct_reporting_recovery_20260906.json).
  This does not prove every ACK was accepted or complete the 72-hour soak.
- [ ] Complete four-zone liveness qualification across repeated report cycles
  and longer gateway/node restarts, with persistent single-owner ACK evidence.
- [ ] Battery-cycle each supported sensor family and restore the same HA device,
  association, and routine reporting without opening pairing.
- [ ] Record stock battery-rejoin exchanges for both valves, then reproduce local
  retained-association recovery with device-owned terminal/operational proof.
- [ ] Restart HA, gateway, and each assigned node while idle; verify identities,
  counters, ACK owners, availability, and no replay.
- [ ] Reassign one sensor ACK owner and verify revocation precedes replacement TX.
- [ ] Qualify sustained stock/custom coexistence for sensors and valves with
  separate ownership, normal stock operation, and no duplicate HA devices.
- [ ] Document recovery for every destructive association transition.

Exit: ordinary battery changes and infrastructure restarts do not require full
re-pairing; independent stock/custom cohorts operate without conflicting authority.

## Phase 3 — reliable valve control

### Four-zone valve

- [ ] Retain one installed run's RF response, duration, HA notification,
  automation outcome, and watchdog outcome together.
- [ ] Verify explicit early stop on Zones 2–4.
- [ ] Physically re-pair an unchanged association and confirm the already
  authenticated counter is preserved. Software regression coverage exists.
- [ ] Restart gateway/node during an active bounded run without replay or
  speculative close. Idle restart and subsequent control have passed.
- [ ] Qualify late response, RF timeout, duplicate requests, command spacing,
  authenticated recovery, and positively observed overdue anomalies.
- [ ] Complete stable-owner retained-counter checks 1, 4, 8, and 12 hours after
  morning sync, away from report windows. Preserve actual counter continuity,
  latency, automatic idle, and remaining user-authorized watering budget.
  Do not replay missed checkpoints or count an intervening command as a clean hold.
- [ ] Isolate causes of counter staleness: time, owner reboot/reconnect, ACK gaps,
  and stock maintenance traffic. Fixed-anchor recovery does not require this
  causal result, but a single overnight failure cannot establish expiry.
- [ ] Repeat association/control on a second specimen or compatible hardware profile.

Morning scheduling is enabled on the installed valves, and the last observed
status for both is Ready. That deployment state does not complete the controlled
retention matrix. The last-zone idle-reply correction is deployed; see the
[current sync design](research/HTV405_MORNING_SYNC_DESIGN.md).

### Single-zone valve

- [x] Qualify idle radio/gateway restart, valve-owned automatic stop across an
  active gateway restart, and early close after an active owner reboot. Counter
  state survives, no actuator is replayed, and the corrected reconnect trial has
  matching positive RF replies and independent idle. Gateway 0.34.15 also blocks
  commands while a reboot is pending, preserving the counter instead of sending
  through the stale connection. Evidence:
  [restart recovery](research/fixtures/htv145_restart_recovery_20260906.json).
- [ ] Qualify report/summary ACK on-air timing, residue, and suppression of retries
  on the cleaned image. Continued reports and gateway/radio ACK diagnostics do
  not replace independent waveform evidence; SDR access is currently unavailable.
- [ ] Complete the high-marker command-phase model for arbitrary action ordering,
  including consecutive opens. Alternating open/close and rollover are supported;
  fixed action polarity is not a universal model.
- [ ] Repeat operational acceptance on fresh user-assisted associations with
  fresh batteries and independent state evidence.
- [x] Promote the verified single-zone association to standard firmware and HA
  controls at the user's request. Gateway 0.35.0, integration 0.15.0, firmware
  0.16.0 retain one device, its counter, ACK owner and morning schedule. Dry
  public-API tests confirm one-minute automatic stop, a subsequent open and
  early close after 20 seconds; counter progression is 129 → 130 → 131 → 131.
  A final post-restart one-minute run confirms decoded watering and automatic
  idle reports with counter 132.
  [Promotion evidence](research/fixtures/htv145_standard_firmware_control_20260906.json).
- [x] Connect the promoted single-zone valve to the front garden (user confirmed)
  and migrate the live dashboard, Run Now, scheduled decision and watchdog.
  Preserve 07:00 / 30-minute settings, season toggle and local-moisture/weather
  checks. Enable 06:15 America/New_York morning sync (30-minute window). Remove
  obsolete Sonoff meter automations/cards, keeping historical helpers untouched.
  HA configuration validation and restart succeeded; no watering was triggered
  during cutover. The four-zone decision/control path is unchanged.
- [x] Confirm the first front-garden scheduled irrigation and valve-owned stop.
  September 9: the user confirmed completion; accepted decoded RF observations
  show 07:00:01 open, 35-minute duration, and 07:35:03 idle on gateway 0.36.4 /
  owner firmware 0.16.2. No additional watering was triggered for this check.
  [Redacted evidence](research/fixtures/htv145_scheduled_watering_20260909.json).
- [ ] Verify the scheduled run's HA feedback, rendered completion/failure state
  and actual push delivery. The automation trace/UI were not independently
  inspected during the read-only evidence review. Remaining ACK waveform,
  fresh-association and soak gates stay open.
  The existing six-hour reliability-review heartbeat now explicitly checks the
  September 9 07:00 local run after its window, correlating HA decisions with
  valve-owned confirmation. A justified moisture/weather skip is not an irrigation
  failure or a passed watering test. This follow-up must not trigger extra watering.

### HA and irrigation

- [ ] Verify HA watering state changes only from authenticated responses or
  independent valve telemetry, never from outbound command intent.
- [ ] Qualify one-active-zone enforcement, per-zone durations, local schedules,
  completion/failure notifications, and watchdog behavior end to end.
- [ ] Exercise scheduled irrigation with some sensors stale and with all sensors
  stale; verify the configured 6–8-hour bounded fallback cannot suppress watering
  indefinitely. The deployed script handles these branches; scheduled evidence
  remains required.
- [ ] Verify live timestamps/schedules in a non-Eastern timezone in addition to
  existing UTC/offset/DST software tests.

Exit: accepted commands have valve-owned confirmation; failure and restart behavior
are bounded, observable, and recoverable.

## Phase 4 — field decoding

- [x] Decode HCS026 moisture/categorical battery, HTV145 state/duration/usage/
  categorical battery, and HTV405 zones/duration/control counters.
- [ ] Correlate model-supported fields with timestamped cloud or physical state:
  battery, active zone, requested/actual/remaining duration, stop, and HTV145 usage.
- [ ] Validate the HTV405 battery candidate with a controlled normal-to-low
  transition. Byte 17 mask `0x08` remains provisional; routine ACK payloads do
  not establish battery state. Keep HA battery unavailable until validated.
- [ ] Ensure discovery is based on product codes and protocol capabilities,
  not seller names, household endpoints, or friendly names.

Exit: supported fields agree with independent observations; unsupported values
remain explicitly unavailable. See [device references](protocol_documentation/).

## Phase 5 — stability qualification

- [x] Deploy a read-only HA-scheduled snapshot/event collector with a durable
  cursor, fixed window, explicit gap/error records, and automatic completion.
  See [operation](examples/reliability-soak/README.md).
- [x] Complete and review the fixed 72-hour observation collection. The closing
  sample on September 10 contains 874 snapshots and 66,569 events, no recorded
  collector gaps/errors, six fresh sensors at every snapshot, stable configured
  sensor ACK ownership and eight unchanged device identities. Source/copy hashes
  match and SQLite quick_check passes. Right Bed's maximum observed gap was
  520.254 seconds. See [completed review](research/RELIABILITY_COLLECTION_REVIEW_20260910.md).
- [ ] After fleet firmware qualification, collect an unchanged-release production
  baseline. The completed window includes 83 connected events, two disconnected
  events, 11 reboot-observed events and multiple firmware versions. Single-zone
  reporting had a 67-minute gap overlapping pairing/handoff work. This qualifies
  observation/recovery evidence, not uninterrupted final-version stability or
  independent on-air ACK acceptance. Preserve the completed database and captures.
- [ ] Include sustained stock/custom coexistence and three successful scheduled
  irrigation cycles using only local authority.
- [ ] Include HA/gateway restart, node reboot/OTA, and device battery cycle
  without identity loss or command replay.
- [ ] Confirm weak-link placement is adequate; relocate only if evidence requires it.
- [ ] Observe no phantom devices, duplicate ACK owners, false watering states,
  stale-data decisions, or notification reconnect flapping.
- [ ] Test wrong-checksum OTA, interrupted download, candidate-boot power loss,
  unhealthy-boot rollback, and USB recovery.
  September 7: two interrupted 0.16.0 downloads left a node connected on its
  original 0.15.7 image, with no candidate boot. A third unchanged attempt completed
  the download, rebooted into 0.16.0, and confirmed gateway/radio health. Interrupted
  download retry is physically demonstrated; the other OTA fault cases remain open.
  September 8 repeated this behavior on Front Yard: two interrupted downloads
  retained the running image, and a third unchanged transfer passed SHA and OTA
  health confirmation. Root cause of intermittent transfer interruption remains
  unproven; do not weaken artifact checks or infer a timeout fix from the retry.
  September 9: Front Yard retained its verified 0.16.2 image after three failed
  0.17.0 downloads; the same artifact passed first-attempt OTA on the other two
  nodes. Its error combines connection loss and a ten-second no-progress timeout,
  so current diagnostics do not distinguish those causes. Prioritize a bounded
  transfer diagnosis before further repeated production-owner retries.
  The subsequent near-AP retry failed at approximately 89% with -54 dBm signal.
  Preserve that negative result; investigate connection-close versus stalled-read
  behavior rather than assuming that further placement changes will fix OTA.
  The later instrumented trial proved a ten-second whole-image server-write
  timeout. Gateway 0.37.1's bounded streaming fixed the slow-reader regression
  and the next real Front Yard update, including healthy-boot confirmation and
  restored ownership. This establishes the observed transfer cause, not all
  possible OTA failure modes or the remaining rollback fault-injection gates.

Exit: durable evidence meets the complete matrix without unexplained intervention.
Passive monitoring alone cannot qualify battery-cycle or coexistence operations.

## Phase 6 — open-source hardening

- [x] Isolate the intermittent network-test registry race before calling CI
  deterministic. September 8 PR run 34270093265 failed
  `test_htv145_pairing_handoff_rejects_unproven_frames` (`wrong_session`):
  a direct private-store registry read returned an empty list. The same commit
  passed the branch CI run and 521 local tests (two skips); 20 repetitions of
  the entire rejection-variant test also passed. September 10: concurrent private
  SQLite reads reproduced empty results; the same reads under the gateway lock
  passed 10,000 iterations. The test now uses that lock without changing rejection
  assertions or pairing behavior; 20 repetitions and the full suite passed.

- [x] Complete the production installation-assumption audit. Empty defaults,
  accepted-observation identity recovery, evidence-based ACK routes and generic
  pairing profiles are implemented; historical profiles live only in tests and
  research, and replay samples are explicit `examples/` inputs.
- [ ] Review protocol, gateway, HA, firmware, and research interfaces; introduce
  typed/versioned boundaries, structured errors, and formal HA migrations.
- [x] Finish event-driven HA sensor updates with slow reconciliation fallback
  and authoritative snapshots for valve/control/topology events.
- [ ] Retire remaining superseded probes, temporary acceptance endpoints,
  obsolete gates, firmware artifacts, and dormant two-radio support.
- [ ] Preserve authentication, association-bound TX, bounded duration,
  device-owned confirmation, command spacing, at-most-once opens, and rollback.
- [x] Add encrypted node sessions, TLS record replay protection, credential
  lifecycle controls, API limits, reproducible packaging, and asymmetric OTA
  signatures. Implemented and deployed; see alpha security/fleet evidence above.
  Initial adoption remains explicitly trusted-network-only, and physical RF
  counters remain distinct from transport replay protection.
- [ ] Run CI, security/redaction review, and clean-environment installation tests.

Exit: contributors can build one production stack without household knowledge;
research transmit paths cannot enter a release artifact.

## Phase 7 — documentation and research infrastructure

- [x] Streamline current device references, operational guides, architecture,
  and research procedures. Keep chronology in evidence records and status here.
- [ ] Make receive-only SDR capture a managed Mac service with optional normalized
  forwarding. HA production must remain independent of SDR; current USB absence
  prevents live capture qualification.
- [ ] Decide the research repository boundary before publication. If separated,
  keep protocol fixtures/models with production and move raw data/orchestration.
- [x] Clean merged branches/worktrees and archive obsolete backups/firmware.
  The active catalog retains installed/rollback releases and the staged update;
  raw evidence is preserved, with one canonical development checkout.

Exit: concise user-oriented docs, explicit research boundaries, and independent
capture infrastructure.

## Deferred migration and backlog

Cloud-to-local authority handoff and a HomGar integration merge remain deferred
until Phases 0–5 qualify. Design review may continue without live migration.

- Preserve explicit timezone on SDR observations before restoring it as an
  authoritative receiver; do not reinterpret ambiguous historical timestamps.
- Replace deprecated device-registry `async_get_device` calls in the HA
  integration with entry-scoped APIs before HA 2027.8. HA 2026.9 startup warns
  at coordinator.py and __init__.py; current setup succeeds. Preserve support
  for the declared minimum HA version when implementing the replacement.
- Discover additional device families and determine whether HCS026 P1–P6 soil
  selection is RF, device-local, or cloud metadata.
- Determine whether any pairing field controls long-term telemetry channel.
- Characterize compact product/status integrity before constructing that traffic.
- Optimize channel scheduling and placement beyond the required stability floor.
- Build a dedicated Add device wizard with actual footer Back/Next buttons on
  every selection/review screen. Deferred by the user on September 8 after
  selecting native-flow improvements first. HA 2026.8's standard data-entry
  forms provide Next labels but no previous-step button contract; preserve
  backend validation and explicit Start pairing authorization in any custom UI.
- Finish carrier manufacturing/enclosure work under its physical preorder checklist.

Promote a backlog item only when evidence makes it a qualification blocker or
irrigation reliability issue; do not implement it merely because it was noticed.
