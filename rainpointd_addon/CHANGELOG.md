# Changelog

## 0.33.13 / Integration 0.13.1 / Firmware 0.15.0-supervised-beta.10

- Promote an already-selected HTV405 timeout-recovery counter automatically
  after the complete possible run plus safety guard elapses, so HA control no
  longer remains recovery-blocked until a hidden direct API call is attempted.
- Accept an exact, in-window valve command response received by any
  authenticated radio node while retaining the association owner as the sole
  transmitter. This adds receiver diversity without broadening RF authority or
  accepting command intent as state.
- Expose bounded recovery timing and attempt diagnostics on the HA zone
  entities so irrigation logic can wait safely before a limited retry.

## 0.33.12 / Integration 0.13.0 / Firmware 0.15.0-supervised-beta.10

- Add a management-authenticated, supervised HTV405 counter probe for an
  exhausted timeout recovery. It accepts one explicit candidate only after the
  previous bounded run duration plus the 15-second hardware guard has elapsed,
  the valve remains linked and canonically idle, and no command is pending.
- Keep the guarded probe outside ordinary Home Assistant valve controls; it is
  an evidence-recovery primitive for determining the retained counter without
  weakening normal command-counter synchronization.
- Use that probe to prove a same-identity valve retained counter `3`: additive
  five-minute payloads were negatively acknowledged at counters 3--5, while
  counter 3 with the known `9e 00` one-minute payload authenticated, watered,
  advanced to 4, and stopped automatically. Multi-byte duration construction
  across the low-byte bit-7 boundary is therefore unresolved rather than
  promoted as an additive inverse.

## 0.33.11 / Integration 0.13.0 / Firmware 0.15.0-supervised-beta.10

- Treat a strict controller-addressed valve report during the active HTV405
  session as the authoritative pairing outcome, while leaving the selected
  node armed for its bounded optional transcript tail.
- Preserve a later node `failed`/`session_timeout` result as raw protocol
  diagnostics without allowing that optional-tail timeout to overwrite a
  completed HA pairing or reset valve control state.
- Keep pre-terminal node timeouts as real failures and make the effective,
  raw-node, and optional-tail outcomes independently inspectable through the
  gateway diagnostics.

## 0.33.10 / Integration 0.13.0 / Firmware 0.15.0-supervised-beta.10

- Resolve the HTV405 long-duration bias from a physical 15-minute trial. The
  two-second counter adds `0x80`; the former bitwise-OR encoder transmitted 644
  seconds for a requested 900-second run whenever the counter already had bit
  7 set.
- Decode both bytes of HTV405 requested and remaining duration fields, and
  advance supervised firmware with the corrected additive encoder.
- Regress the exact valve-originated reports from the failed 15-minute local
  Zone 1 trial: 644 seconds requested and 638/636 seconds remaining, followed
  by an automatic idle report 646 seconds after command acceptance.

## 0.33.9 / Integration 0.13.0 / Firmware 0.15.0-supervised-beta.8

- Merge receiver-partial HTV405 zone reports into one canonical valve state, so
  an SDR report that omits other zones cannot change their HA entities from Off
  to Unknown after a complete radio-node report.
- Rebuild canonical four-zone state from the retained observation journal on
  startup, repairing snapshots already affected by the multi-receiver race
  without altering the raw protocol evidence.
- Regress the exact 2026-08-26 complete-idle then partial-Zone-3 frame sequence
  that exposed the issue.

## 0.33.8 / Integration 0.13.0 / Firmware 0.15.0-supervised-beta.8

- Add association-scoped recurring HTV405 liveness acknowledgements from the
  valve's single assigned control node. The gateway restores that authorization
  after node reconnect and OTA, revokes the old owner before reassignment or
  removal, and never includes zone, duration, or actuation fields.
- Reproduce the captured stock-gateway endpoint, counter, timing, carrier, and
  320-symbol wake transform for ordinary idle and watering reports.
- Decode HTV405 liveness replies independently so an SDR or second radio node
  can confirm the bridge's transmission over air without treating it as valve
  state or command success.
- Advance every shared-source firmware variant so OTA cannot mistake an older
  binary for this liveness-capable build.

## 0.33.7 / Integration 0.13.0 / Firmware 0.15.0-supervised-beta.7

- Do not cancel the selected HTV405 radio node when HA receives terminal
  pairing evidence and completes device naming. The node now retains its
  bounded session long enough to finish the remaining modeled association
  replies or expire naturally.
- Associate strict selector-`0x07` HTV405 paired-link reports with the valve
  device so report time and availability reflect valid RF activity, while
  preserving the latest definitive zone and watering state.
- Record the reversible, stepped Add-device wizard as a post-stabilization UX
  requirement in the canonical roadmap.

## 0.33.6 / Integration 0.13.0 / Firmware 0.15.0-supervised-beta.7

- Present gateway-advertised pairing profiles in Home Assistant under broad
  Sensors and Valves categories, with supported models listed beneath each.
- Add HTV405 to the normal HA pairing flow without asking users to copy a
  factory endpoint, controller route, or companion endpoint.
- Let a selected radio node adopt the first strict HTV405 factory announcement
  in its bounded session, while preserving every captured pairing reply,
  carrier, timing, and generated custom-controller-identity safety check.
- Select pairing nodes by the chosen model's advertised capability; a node at
  its sensor ACK capacity remains available for compatible valve enrollment.
- Advertise automatic HTV405 identity discovery as a distinct node capability,
  so older explicit-pairing firmware is never offered by the no-ID HA flow.
- Give research-only HTV145 images a distinct OTA firmware variant so they
  cannot be offered as upgrades to normal unified garden nodes.
- Keep the unaccepted HTV145 transmitter out of the normal UI while retaining
  its research-only profile and build boundary.
- Advance the isolated HTV145 pairing build to
  `0.15.1-htv145-pairing-probe.5` because the shared radio-node source changed;
  its accepted assignment prefix and model-specific continuation are unchanged.

- Make pairing completion and HA device-menu removal work through one
  family-neutral lifecycle for sensors and valves.
- Restore a deliberately removed valve only after command-scoped,
  valve-originated terminal evidence, retaining one stable device identity and
  preventing ordinary reports from bypassing suppression.
- Require a valve's terminal confirmation to address the active pairing
  controller identity, so simultaneous stock-gateway traffic cannot confirm a
  custom-local association.
- Preserve valve routing across metadata updates and clear private HTV145
  control state when its association is removed.
- Preserve both rejected probe-.3 physical trials and distinguish an
  assignment transmit from valve-originated acceptance.
- Restore the probe-.2 49.5 ms initial assignment scheduler without changing
  the recovered six-stage HTV145 continuation. Require continuous IQ evidence
  before any further stage-0 calibration change.

## 0.33.5 / Integration 0.12.1 / Firmware 0.15.1-htv145-pairing-probe.3

- Replace the HTV145 post-assignment HTV405 hypothesis with the complete
  six-stage transcript recovered from a successful continuous stock-gateway
  capture.
- Reproduce the delayed long-wake controller command, model-specific reply
  destinations, per-step turnaround slots, and temporary routine-carrier
  receive window without modifying the physically accepted HTV405 path.
- Freeze the stock frames, RF centers, wake lengths, and timing evidence in a
  dedicated regression fixture pending local physical acceptance.

## 0.33.4 / Integration 0.12.1

- Add a research-gated HTV145FRF factory-enrollment profile based on the
  2026-08-25 explicit long-press capture.
- Keep HTV145 pairing capability isolated from the validated HTV405 path and
  require an explicitly compatible radio-node firmware.

## 0.33.3 / Integration 0.12.1

- Give observation-only valves and durable HTV405 associations the same
  authenticated, local-only HA forget lifecycle already used by soil sensors.
- Let HA remove a stale device after a successful gateway inventory proves the
  backend no longer exposes it.
- Migrate legacy trailer-invalid HTV405 snapshots, cadence metrics, receiver
  metrics, and endpoint candidates out of the live device inventory while
  retaining their raw events as protocol evidence.
- Make an explicitly invalid HTV405 trailer override the stale positive
  acceptance projection briefly persisted by gateway 0.33.1.

## 0.33.2 / Integration 0.12.0 / Firmware 0.15.0-supervised-beta.5

- Require a session-scoped, terminal sensor frame addressed to the requested
  RF controller identity before HCS026 pairing may complete or transfer its
  persistent ACK owner.
- Preserve a generated controller identity when automatic HCS026 discovery
  rebuilds its pairing profile in place; the prior aliasing bug silently
  restored the retained stock identity after a factory announcement.
- Attribute retained HTV145 controller requests and valve-originated reports
  by the transmitting endpoint so requests cannot advance device cadence and
  valid valve reports can confirm availability.
- Allow authenticated removal of persisted valve links, suppress forgotten
  endpoints from RF rediscovery, and cover corrupted phantom-device cleanup
  with storage and HTTP regressions.
- Complete HTV405 pairing from a session-scoped, trailer-valid paired-link
  report after the selected node transmits at least one reply; the 18-row stock
  transcript remains a traffic model rather than a mandatory completion count.
- Reject trailer-invalid HTV405 frames from link discovery and preserve the
  latest definitive watering state across valid phase-only heartbeats.
- Retain narrowly scoped HTV405 timeout evidence and permit the next explicit
  bounded open to try only the same or immediately following command counter,
  after the entire possibly accepted run plus a 15-second guard has elapsed.
  Unexpected watering, node rejection, dispatch failure, and authenticated
  response mismatch remain terminal and cancel recovery.
- Expire an HTV405 command reservation in the gateway when a disconnected,
  outdated, or interrupted radio node does not return a usable terminal result,
  preventing one missing node report from wedging all later valve control.
- Allow the authenticated RF egress node for an idle HTV405 association to be
  changed independently of the valve/controller identity. The change clears
  command-counter state and requires fresh synchronization before control.
- Generate and persist one gateway-wide RF controller/companion identity in
  SQLite, expose it in diagnostics, and share it across every radio node.
- Parameterize automatic HCS026 pairing, known-sensor recovery, routine ACKs,
  and HTV405 pairing with the association's controller identity while
  preserving all pre-existing assignments as retained stock associations.
- Require an explicit radio-node firmware capability before a generated
  identity can be paired or assigned, preventing an older firmware from
  silently falling back to the stock RainPoint identity.

## Firmware 0.15.0-supervised-beta.4

- Consolidate the current sensor pairing/recovery, persistent ACK ownership,
  HTV405 enrollment and supervised control, managed OTA, diagnostics, and
  configurable RF controller identity into one radio-node artifact.
- Preserve the physically successful HTV405 enrollment mechanism unchanged:
  custom identity alters only the association endpoints, while every captured
  request/reply body, RF channel, deviation, and reply-timing rule remains
  pinned by the hardware-independent protocol regression.
- Record the successful installed 20-minute Zone 1 run, including authenticated
  open confirmation and valve-originated automatic-idle confirmation.

## 0.33.1 / Integration 0.12.0 / Firmware 0.15.0-supervised-beta.3

- Extend supervised HTV405 opens from the original 1--4 minute pilot boundary
  to configurable 1--60 whole-minute runs across the gateway, authenticated
  radio-node command boundary, frame builder, and Home Assistant entities.
- Add one HA duration number per HTV405 zone. Valve opens consume the selected
  duration while retaining single-zone exclusivity, durable command
  reservation, authenticated response matching, and valve-owned automatic
  stop semantics.
- Preserve the authenticated response role across radio-node and gateway
  restart recovery, and normalize mixed legacy SDR timestamps without allowing
  telemetry to substitute for the independent controller counter.
- Move the installation example dashboard from the retired HTV145 `valve-1`
  identity to the currently paired HTV405 Zone 1. HTV405 battery remains
  unavailable pending an independently correlated RF transition.
- Record the remaining publication gates explicitly: installed longer-duration
  field acceptance, battery-cycle rejoin, battery decoding, interrupted OTA,
  signed releases, and a second valve specimen.
- Add a disabled, token-protected HTV145 dry-valve acceptance endpoint and
  command-line runner. It derives the independent command counter from retained
  stock traffic, enforces controller silence and fresh-idle preflight, permits
  one bounded open, and passes only on valve-originated active and automatic
  idle evidence.
- Derive the HTV145 acceptance carrier from positively confirmed channel-0/11
  RF evidence, reject low or unknown valve battery state, and prevent stale
  stock-command evidence from being reused after a local attempt.
- Keep controller-to-valve requests as retained intent only. They no longer
  invent watering state or advance valve report/availability metrics when a
  local receiver hears its own unacknowledged transmission.

## 0.32.0 / Firmware 0.15.0-supervised-beta.1

- Add a disabled-by-default, token-protected HTV405 control API and four Home
  Assistant valve entities. Every open is limited to 1--4 whole minutes, only
  one zone may run, and early stop targets only the confirmed active zone.
- Persist every HTV405 command reservation before RF dispatch. Node rejection,
  response mismatch, or timeout invalidates the counter and is never retried;
  HA state changes only after a matching valve response or accepted telemetry.
- Preserve the authenticated next command counter across a valve's automatic
  idle report. Unexpected watering invalidates it as possible competing-
  controller activity.
- Correlate the stock early-stop exchanges: an accepted open consumes the
  current command counter, while a confirmed close leaves that counter ready
  for the next bounded open.
- Add a disabled, non-public HTV145 dry-valve acceptance harness that selects
  one node, synchronizes only from passive command evidence, dispatches one
  bounded logical open, and requires observed open plus automatic idle.
- Distinguish candidate transmit, receiver, corrupt/foreign-response, missing
  response/state, gateway-loss, and ambiguous-counter failures in the radio
  node audit report.
- Generalize retained transaction analysis across HTV145 and both HTV405 zone
  layouts, and machine-classify new enrollment versus retained rejoin evidence.

## Research firmware 0.14.0-valve-control-probe.40

- Isolate the unvalidated HTV405 battery-cycle retained-rejoin candidate in a
  dedicated one-reply state machine. The validated 18-step new-enrollment
  session no longer contains a rejoin mode, and crossed regression tests prove
  that each workflow rejects the other's announcement.

## Research firmware 0.14.0-valve-control-probe.39

- Physically validate duration-bounded local opens for HTV405 Zones 2--4 with
  port-specific authenticated responses, matching lower state reports, and
  automatic idle reports.
- Keep selector-`0x07` phase reports from overwriting valve state, decode the
  locally enrolled port nibble, and clear all mutually exclusive zones when a
  local idle report omits the previous active port.
- Retain the fresh-battery boundary comparison without assigning an unsupported
  battery field; known startup/link families were unchanged, while the changing
  diagnostic offsets also varied with watering-session state.
- Keep multi-zone transmit commands compiled out of production firmware and
  unavailable through public gateway and Home Assistant APIs.

## 0.31.2 / Firmware 0.14.0-valve-control-probe.35

- Persist the start, duration, and expected completion of an authenticated
  duration-bounded HTV405 research run separately from routine telemetry.
- Make startup, client loss, missing acknowledgements, and missing telemetry
  observation-only; none of them emits a valve command.
- Block control when the authenticated counter is uncertain. Permit exact-
  counter retries only for an explicit early-stop, and require a fresh overdue
  watering report before an automatic anomaly close.
- Keep valve control unavailable through the public gateway and Home Assistant
  APIs.

## 0.31.0 / Firmware 0.14.0-combined.1

- Combine the selector-2 HTV405 pairing candidate with authorized paired-state
  HCS026 sensor recovery in the single supported radio-node firmware.
- Preserve the valve safety boundary: enrollment replies remain bounded and
  valve open/close control is still unavailable.
- Expose per-sensor ACK ownership, over-air confirmation, unconfirmed replies,
  and recovery-phase diagnostics through the gateway and Home Assistant.

## 0.30.0 / Firmware 0.12.9

- Correct the selector-2 initial HTV405 reply center by +10.055 kHz. Direct
  local/stock spectral comparison anchored by the valve's own request showed
  the 0.12.8 reply at 433.546375 MHz versus 433.556430 MHz for stock.
- Keep the selector-2 routine channel unchanged; only the initial assignment
  center moves. Valve control remains disabled.

## 0.29.9 / Firmware 0.12.8

- Reduce the experimental HTV405 software reply delay from 50 ms to 49 ms.
  A continuous local IQ capture measured the prior physical reply start about
  1.3 ms later than the accepted stock exchange.
- Preserve the now-validated selector-2 frame, current packed clock, carrier,
  deviation, wake waveform, and disabled valve-control boundary.

## 0.29.8 / Firmware 0.12.7

- Anchor the pairing wall clock after HTV405 frequency preparation. The
  selector-2 trial transmitted a structurally correct frame whose packed time
  was about four minutes ahead of the physical attempt.
- Preserve the validated selector-2 markers, channels, 50 ms reply delay, and
  disabled valve-control boundary.

## 0.29.7 / Firmware 0.12.6

- Switch the isolated HTV405 enrollment candidate to the fully observed
  selector-2 assignment, request markers, and reply-frequency branch after
  selector 6 was rejected despite validated carrier and stock reply timing.
- Keep watering-command transmission disabled while enrollment remains under
  physical validation.

## 0.29.6 / Firmware 0.12.5

- Replace the misleading split-file HTV405 timing estimate with a continuous
  2.0 Msps measurement: 81.886 ms request-start to reply-start and 50.656 ms
  receive-complete to reply-start.
- Delay the cached-calibration assignment by 50 ms and use the current local
  wall clock instead of the HCS026-specific four-minute lead.
- Preserve the selector-6 assignment template; a third successful stock
  enrollment shows that selector 2 uses a distinct marker and channel branch.

## 0.29.5 / Firmware 0.12.4

- Record the physically measured 0.12.3 assignment reply: correct decoded
  frame, 433.505786 MHz center, and an approximately 1.1 ms turnaround gap.
- Pre-calibrate the two HTV405 reply frequencies when the bounded window is
  armed and restore their CC1101 FSCAL values for the time-critical hop.

## 0.29.4 / Firmware 0.12.3

- Pre-initialize the ESP32 RMT transmitter when the bounded HTV405 pairing
  window is armed.
- Defer the redundant CC1101 return-to-RX calibration until after the
  time-critical valve reply, targeting the measured 4.2 ms turnaround gap.

## 0.29.3 / Firmware 0.12.2

- Correct the stock HTV405 response timing calculation for unequal rtl_433
  saved-window lengths and transmit immediately after request reception.
- Combine the zero-added-delay cadence with the measured test-node carrier
  correction; the earlier builds validated only one of those two at a time.

## 0.29.2 / Firmware 0.12.1

- Correct only the HTV405 candidate's node command offset after an SDR capture
  measured its valid assignment waveform 52,154 Hz below the stock carrier.
- Preserve the proven HCS026 pairing and routine-ack frequency correction.

## 0.29.1 / Firmware 0.12.1

- Correct the HTV405 candidate's reply delay from 10 ms to the stock gateway's
  measured 100 ms receive-complete-to-transmit interval.
- Retain the measured timing and its capture-quality limitation in the protocol
  fixture so future changes do not regress to an unverified cadence.

## 0.29.0 / Firmware 0.12.0

- Add an internal, association-specific HTV405 enrollment candidate reconstructed
  from the isolated stock-gateway transcript.
- Model 18 valve-originated steps with 17 bounded replies, including the
  intentional no-transmit step and distinct initial modulation profile.
- Keep valve open, close, and watering commands outside the production firmware
  boundary pending isolated physical enrollment and safety validation.
## 0.28.1 / Firmware 0.13.0-sensor.1

- Recover an already-authorized HCS026 sensor when it emits the captured
  paired-state `01 -> 02 -> 02 -> 03` control exchange, without opening a
  pairing window or accepting an unknown identity.
- Keep recovery replies on the sensor's single-owner radio node and expose the
  reply phase, outcome, owner, and aggregate recovery counters as diagnostics.
- Publish this as a sensor-only prerelease so valve-pairing experiments remain
  isolated until both paths have been validated independently.

## 0.28.0 / Firmware 0.11.0

- Consolidate the supported ESP32/CC1101 node into one `rainpoint_bridge`
  firmware build containing receive, generalized HCS026 pairing, persistent
  single-owner routine acknowledgements, diagnostics, and managed OTA.
- Remove obsolete bench and candidate firmware choices from CI and operator
  documentation while retaining executable protocol and safety regressions.
- Document physically validated automatic enrollment and one-reply recovery
  across independent test and installed-sensor identities.

## 0.27.0

- Mark gateway-initiated recovery of a known HCS026 identity as a one-reply
  rejoin transaction, distinct from first-time four-step enrollment.

## Firmware 0.10.0-test.8

- Queue up to eight authenticated gateway commands so all persisted sensor ACK
  assignments are restored after a reconnect or OTA reboot.
- Complete a known-sensor automatic rejoin after its first valid reply, then
  immediately return the radio to routine receive and acknowledgement duty.

## Firmware 0.10.0-test.7

- Accept the validated HCS026 factory-announcement retry counters 1, 2, and 4
  during a bounded pairing session. This allows known-sensor automatic rejoin
  to answer a retry after the first announcement triggered remote arming.

## 0.26.0

- Persist radio-node friendly names and areas in the gateway registry and
  migrate legacy Home Assistant-only overrides without rotating credentials.
- Record known-sensor factory announcements and request a bounded automatic
  rejoin through the sensor's existing ACK owner; unknown identities remain
  blocked until an explicit pairing window.
- Accept identity-specific automatic rejoin profiles in unified firmware
  `0.10.0-test.6`.
- Keep nodes with active HCS026 acknowledgement assignments on the validated
  telemetry channel, preventing broad-scan timing from repeatedly missing a
  nearby sensor's retry burst.

## Integration 0.10.3

- Migrate legacy radio-node display names and areas from Home Assistant into
  gateway-owned metadata so pairing and management surfaces use the same
  friendly labels.

## 0.25.0

- Expose command-scoped pairing identities and detailed exchange stages so an
  already-enrolled sensor can complete a recovery session without being
  mistaken for an expired pairing window.

## Integration 0.10.2

- Complete pairing from either a newly created enrollment or a radio-confirmed
  recovery of an existing endpoint, preserving its Home Assistant identity.
- Explain the selected radio node, pairing deadline, four-message exchange, and
  terminal-confirmation delay while the pairing modal is in progress.
- Update the open Home Assistant progress modal as the radio advances from
  listening to message exchange and terminal-confirmation verification.

## 0.24.0

- Include managed radio-node names and areas in the pairing-node inventory so
  Home Assistant can present friendly installation labels instead of IDs.

## 0.23.0

- Atomically replace a stale radio-node TCP session only after the reconnecting
  node proves the same managed credential, allowing OTA and power-reset recovery
  without restarting the custom local gateway.
- Prevent the retired connection handler from marking its authenticated
  replacement disconnected.

## 0.22.0

- Persist one radio-node owner for each HCS026 routine acknowledgement route.
- Restore bounded ACK authorizations after reconnect and OTA reboot, and revoke
  the old owner before reassignment or sensor removal.
- Consolidate generalized pairing, routine acknowledgements, and OTA into one
  universal experimental firmware track.
- Allow a universal release to declare the older firmware variants from which
  it may be installed without weakening hardware/channel compatibility checks.
- Defer a verified OTA restart to the top-level firmware loop after a physical
  trial exposed an occasional stall inside the network-command handler.

## 0.21.0

- Add a strict local firmware catalog and verify exact size plus SHA-256 before
  making an artifact available to a radio node.
- Serve immutable catalogued artifacts from the local gateway and let
  authenticated management clients install by release ID instead of supplying
  arbitrary URLs or hashes.
- Annotate compatible radio nodes with update availability and progress for a
  native Home Assistant firmware update entity.
- Match releases by hardware profile, channel, and firmware variant so the
  routine-ack experiment cannot be replaced by a generic OTA image.
- Allow operators to stage the strict catalog in a configured shared-storage
  directory when direct add-on data access is unavailable.

## Integration 0.10.0

- Add one native firmware update entity per OTA-capable custom radio node,
  including release notes, progress, reboot verification, and failure state.

## 0.20.0

- Add an isolated, capability-gated radio-node OTA trial command without
  enabling OTA in normal firmware.
- Record OTA download, verification, candidate-boot, health-confirmation, and
  rollback diagnostics in the gateway's radio-node state.
- Accept OTA trial firmware during authenticated commissioning while retaining
  strict rejection for unknown node capabilities and generic RF commands.
- Add an authenticated management endpoint for hash-bound OTA trials on an
  explicitly selected, connected, non-RF-armed candidate node.

## 0.19.3

- Permit the isolated routine acknowledgement firmware capability during
  authenticated protocol-v2 node setup.

## Integration 0.9.3

- Expose bounded routine sensor-acknowledgement counts as radio-node
  diagnostics for the controlled firmware trial.

## 0.19.2

- Accept routine acknowledgement status and health counters from the isolated
  candidate firmware without enabling RF transmission in production builds.

## Integration 0.9.1

- Add a chartable last-report interval diagnostic for each local device.

## 0.19.1

- Persist the interval between the latest two accepted, deduplicated device
  reports and backfill it from retained history during schema migration.
- Add test sensors and report-cadence charts to the example local garden
  dashboard.

## Integration 0.9.0

- Migrate legacy config entries to a versioned credential layout and remove
  obsolete report entities during migration instead of every startup.
- Negotiate typed gateway capabilities and use durable long-poll events for
  immediate state refresh, with compatible polling fallback.
- Add one-time standalone gateway claiming and radio-node revocation flows.

## 0.19.0

- Advertise explicit versioned API capabilities and durable event cursors.
- Add long-poll event delivery, standalone claim codes, atomic management-token
  rotation, and radio-node credential revocation.
- Separate the installable production add-on from replay and raw-capture
  controls while retaining those tools in the development CLI.
- Extract transport-neutral RF observations shared by network, RTL-SDR, and
  serial ingestion.
- Add production firmware artifact manifests, integrity verification, and the
  firmware-side rollback-state contract; OTA delivery remains disabled.

## Integration 0.8.2

- Include catalog-derived product-family capabilities in report diagnostics.

## 0.18.2

- Treat shared RF product codes as functional capability families rather than
  exact retail-model identifiers.
- Require variant-level model-code evidence or trusted migration metadata to
  identify an exact product such as HCS026FRF.

## Integration 0.8.1

- Reconcile existing Home Assistant device-registry model labels with the
  gateway's current evidence-based identity instead of retaining a stale
  pre-inference model name.

## 0.18.1

- Report explicit family-level device kind and exact-model confidence after a
  legacy registry row migrates to provisional identity metadata.

## 0.18.0

- Centralize RainPoint product codes, model codes, device kinds, and protocol
  families in an evidence-based product identity catalog.
- Register newly paired sensors provisionally as HCS02x-compatible instead of
  asserting an exact retail model from frame shape alone.
- Promote and persist `HCS026FRF` only after a validated RF product-code or
  model-code observation, while rejecting contradictory identifiers.
- Persist protocol, model-source, product-code, and model-code provenance in
  additive storage schema version 5.
- Reclassify exact HCS026 names written by older hardcoded pairing releases as
  provisional during migration unless retained RF evidence confirms them.
- Advertise lifecycle capabilities independently of retail model labels so
  provisional devices can be managed safely from Home Assistant.
- Include product-identity provenance in Home Assistant report diagnostics.

## 0.17.1

- Expose a newly named HCS026 sensor immediately after pairing even when its
  final telemetry arrived while a prior forget suppression was still active.
- Restore registered sensors as unavailable placeholders after gateway restart
  until their next accepted RF report populates live entities.

## 0.17.0

- Add model-level `hcs026_auto_v1` pairing orchestration: the selected radio
  node adopts the first strict HCS026 factory announcement and derives its
  paired identity without the user or Home Assistant supplying an RF ID.
- Replace public identity-specific profile selection with one automatic HCS026
  workflow while retaining captured profiles as offline regression evidence.
- Use the common four-reply first-enrollment branch and shared selector 4;
  physical validation of automatic adoption remains required before release.

## 0.16.4

- Add the physically validated four-reply Sensor A pairing profile while
  retaining endpoint and firmware-target boundaries.
- Accept both observed HCS026 short-message pairing subtypes and require the
  terminal message before completing enrollment.
- Make sensor removal idempotent and move it to the Home Assistant device menu.
- Correct RF trial isolation analysis so installed valve traffic is not
  misidentified as stock RainPoint gateway traffic.

## 0.16.2

- Decode the controlled marker-relative HCS026 battery flag across both known
  moisture-report layouts so all locally received sensors expose categorical
  normal/low battery status.
- Require a validated ordinary trailer before battery state can update, while
  continuing to retain moisture from corrupt reports only as rejected evidence.

## 0.16.1

- Add an authenticated local-forget operation for any currently known HCS026
  sensor, including automatically discovered paired sensors without a registry
  row.
- Remove enrollment state and suppress automatic rediscovery atomically while
  explicitly transmitting no RF unpair or reset command.

## 0.16.0

- Replace Sensor-B-specific pairing orchestration with an evidence-labelled
  protocol-profile registry shared by the gateway and firmware.
- Support arbitrary installation catalogs from JSON while retaining the old
  prototype catalog only as an explicit identity-compatibility fallback.
- Add gateway-managed adoption sessions: temporary per-node credentials are
  issued through the authenticated API, remain absent from public status, can
  be cancelled, and persist only after the node's first successful mutual-
  authentication handshake.
- Support the firmware 0.6 captive-portal, zeroconf, physical-confirmation, and
  zero-copy Home Assistant adoption contract.

## 0.15.0

- Add a bounded, authenticated Identify command that can blink a capable
  custom local radio node without enabling or configuring its RF transmitter.
- Accept the optional protocol-v2 `identify` capability while preserving
  compatibility with firmware 0.5 nodes.
- Expose node identification through the authenticated management API for the
  Home Assistant device button and future discovery/adoption flow.

## 0.14.0

- Migrate legacy node-option credentials into a private persistent radio-node
  registry without overwriting later managed credentials or metadata.
- Keep registered nodes visible while offline and accept authenticated node
  registration through the management API.
- Validate node health heartbeats for Wi-Fi, memory, temperature, uptime,
  network, loop-latency, reset, and reconnect diagnostics.

## 0.13.0

- Assign a stable identity to the local SDR and every serial or Wi-Fi receiver.
- Deduplicate the same air transmission across receivers before it can inflate
  logical device report counts or Home Assistant activity.
- Persist per-receiver and per-device frame, integrity, duplicate, and RSSI
  coverage metrics and expose them at `/api/v1/receivers`.

## 0.12.0

- Version the SQLite schema and migrate existing databases transactionally.
- Persist the latest accepted observation for every device independently of the
  event journal.
- Bound retained event history without discarding device state, endpoint
  inventory, lifetime reporting metrics, registry records, or enrollments.

## 0.11.0

- Store HCS026 physical enrollment mappings in the gateway SQLite database.
- Migrate the legacy pairing JSON once, reject conflicting state, and archive
  the imported file with a `.migrated` suffix.
- Make registry forget remove the enrollment mapping and add persistent
  rediscovery suppression in the same SQLite transaction.

## 0.10.0

- Separate installation identities and transport-neutral RF ingestion from the
  RTL-SDR process adapter.
- Make accepted HCS026 registry metadata drive live decoding, names, and areas
  without changing established Home Assistant device IDs.
- Migrate legacy registry rows for known prototype endpoints onto their
  already-exposed stable device identities.
- Persist forgotten endpoint suppression so later RF traffic remains raw
  evidence and cannot recreate a removed device until it is accepted again.

## 0.9.0

- Add a network-only production transport for authenticated Wi-Fi radio nodes.
- Make network mode the default for new app installations instead of synthetic
  replay data.
- Persist gateway identity independently of receiver transport while preserving
  the legacy identity when an existing database is first migrated.
- Migrate a legacy transport-derived Home Assistant config-entry identity when
  Supervisor discovery first publishes the persistent gateway identity.

## 0.8.0

- Generate and persist the gateway management credential inside app data.
- Publish the gateway address and credential through supported Home Assistant
  Supervisor discovery so users never copy it into an ordinary pairing flow.
- Add a side-effect-free authenticated endpoint for standalone-gateway setup.

## 0.7.1

- Make registry forget remove the corresponding local HCS026 enrollment mapping
  while explicitly sending no RF unpair command.

## 0.7.0

- Add backward-compatible, mutually authenticated radio-node protocol v2 with
  one bounded Sensor B pairing command and no valve-command vocabulary.
- Start pairing on an explicitly selected node through the Home Assistant
  Configure flow and require matching node completion plus terminal sensor
  message `03` before registry finalization.
- Decode the validated paired message `05`/`06` telemetry layout, including the
  independently observed 11% report.
- Keep protocol-v1 nodes receive-only and disconnect every active node when the
  gateway shuts down so an armed session fails closed.

## 0.6.6

- Accept explicitly disarmed `pairing_tx_bench` ESP32 firmware while keeping
  valve commands unavailable.
- Surface the node's pairing state, completed reply count, and live armed state
  in `/api/v1/nodes` for physical bench testing.

## 0.6.5

- Add a non-transmitting, capture-derived five-step Sensor B pairing profile.
- Report whether a pairing monitor is waiting, has found an unsupported
  factory identity, needs a transmitter, or observed a paired identity.
- Reject Wi-Fi radio nodes that claim transmit capability or report an armed
  transmitter while the node protocol remains receive-only.

## 0.6.4

- Correct pairing capability after a controlled factory-only test proved that
  physical HCS026 enrollment requires a stock-gateway RF reply.
- Report pairing monitoring separately from transmitter availability.
- Add offline recovery and regression fixtures for the short gateway replies.

## 0.6.3

- Add authenticated, receive-only HCS026 pairing windows and persistent
  factory-to-paired identity mappings.
- Allow a proven pairing result to be named and assigned to an area without
  transmitting an RF enrollment or reset command.
- Report pairing capability and progress through the local v1 API.

## 0.6.2

- Recognize validated HCS026 factory announcements and paired endpoint
  identities from two controlled enrollment captures.
- Discover new HCS026 sensors from the strict paired telemetry layout instead
  of requiring an installation-specific endpoint allowlist.
- Decode the controlled HCS026 full/low battery flag at frame byte 17, bit
  `0x04`, for that paired report layout.
- Preserve factory and paired identities in device state and restore dynamic
  sensors from persistent observations after app restarts.

## 0.6.1

- Retain trailer-invalid frames for research without allowing them to update
  Home Assistant device state.
- Track valid/invalid RF frame totals and reception-success percentage per
  device for antenna-placement diagnostics.
- Advance valve report freshness from valid routine frames on its established
  endpoint link without changing the last decoded valve state.
- Rebuild endpoint discovery from trailer-valid history so one-off corrupted
  addresses no longer appear as candidate devices.

## 0.6.0

- Accept telemetry from multiple outbound Wi-Fi ESP32/CC1101 connections while
  retaining the existing RTL-SDR or replay backend.
- Authenticate every node with a unique nonce/HMAC enrollment credential; the
  credential itself is never sent over the network.
- Attach authenticated node provenance to decoded RF state and expose
  connection diagnostics at `/api/v1/nodes`.
- Deduplicate the same frame heard by different nodes within 250 ms without
  suppressing ordinary retransmissions heard by one node.
- Keep the network surface receive-only; command and transmit messages are not
  implemented.

## 0.5.0

- Add a persistent local registry for accepting, naming, assigning, and
  forgetting endpoints already observed by the receive-only gateway.
- Add timed learning sessions that highlight endpoints first observed during
  the window without transmitting pairing traffic.
- Protect every registry mutation with an optional bearer token; writes remain
  disabled when no token is configured.
- State explicitly in every mutation response that local acceptance/forgetting
  does not pair or unpair a physical RF device.

## 0.4.3

- Persist per-device report counts, average intervals, and longest observed
  gaps, including a one-time backfill from existing event history.
- Publish model-specific reporting freshness using observed production cadence:
  15 minutes for HCS026 moisture sensors and 6 hours for the HTV145 valve.
- Correct the Home Assistant signal entity to use the receiver's `rf_rssi_db`
  field and expose reporting-health diagnostics.

## 0.4.2

- Preserve the ESP32 radio name, channel, and CC1101 LQI alongside normalized
  receive events.
- Surface bridge radio initialization errors through gateway health instead of
  silently ignoring diagnostic messages.

## 0.4.1

- Decode the repeated compact `88 VV e0 RR` moisture/RSSI form even when its
  preceding slot byte is not field code 10.
- Keep the compact values unassigned until their changing route fields can be
  mapped safely to a stable sensor identity.
- Add offline event-corpus analysis for trailer selectors and status timing.

## 0.4.0

- Add a receive-only USB serial transport for the ESP32/CC1101 bridge.
- Reuse the established RF decoder and device publisher so ESP32 and RTL-SDR
  frames create identical local state.
- Validate frame length and sync locally before accepting bridge input.

## 0.3.6

- Retain the provisional HCS026 heartbeat battery status for controlled
  transition analysis without exposing it as a supported battery entity.
- Calculate and retain the ordinary-frame CRC-CCITT residual and validation
  result using the two residues established from the capture corpus.

## 0.3.5

- Decode the HCS026 product-code/TLV moisture report and canonicalize it to the
  sensor's established endpoint.
- Retain compact moisture and stock-hub RSSI fields from unassigned status
  frames for further routing analysis without creating phantom devices.
- Add regression fixtures for both newly correlated packet layouts.

## 0.3.2

- Expand the default receive window to cover both observed RainPoint channels.
- Decode the alternate HCS026FRF moisture-field position used by lower-channel
  reports.
- Map the confirmed Left Bed, Front Yard Sensor 1, and newly identified Front
  Yard Sensor 2 RF endpoints.
- Restrict moisture decoding to confirmed sensor endpoints so valve payloads
  cannot create false sensor observations.

## 0.3.1

- Add a bounded receive-only broad-capture phase for decoder research.
- Keep the API and persistent event decoder active while saving raw detected
  signals.
- Automatically return to normal live decoding when the configured capture
  duration ends.
- Store raw captures under `/share/rainpoint-captures` for local analysis.

## 0.3.0

- Persist live normalized RF events in SQLite under the app data volume.
- Restore decoded device state after app restarts.
- Add an endpoint inventory with first/last seen times, role counts, message
  type, signal level, and most recent frame.
- Expose the inventory at the read-only `/api/v1/endpoints` endpoint.

## 0.2.1

- Retain normalized non-moisture RainPoint RF frames in the event stream for
  endpoint discovery and valve-traffic correlation.
- Keep raw-frame discovery receive-only and separate from Home Assistant device
  state.

## 0.2.0

- Add a receive-only `rtl_433` transport for USB RTL-SDR receivers.
- Decode confirmed HCS026FRF soil-moisture reports locally.
- Map raw USB into the protected app without privileged or full host access.
- Retain replay mode as the upgrade-safe default.

## 0.1.0

- Package the replay-backed `rainpointd` service as a Home Assistant app.
- Expose the read-only API on TCP port 8787.
- Add Supervisor health monitoring.
- Support `aarch64` and `amd64`.
## 0.3.3

- Ignore obsolete auto-discovered HCS026 devices whose RF endpoint is not a
  confirmed moisture sensor, preventing valve responses from returning as
  phantom sensors after a restart.
- Keep existing Home Assistant entities safely unavailable when a gateway
  device is reclassified and removed from discovery.
## 0.3.4

- Decode confirmed HTV145 open/close state and requested duration from local RF.
- Decode packed last-session water usage, including values larger than 25.5 L.
- Register the live Garden Valve device so duration, watering state, and last
  usage can populate in Home Assistant without the RainPoint cloud.
