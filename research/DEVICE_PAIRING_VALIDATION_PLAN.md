# Sensor and valve pairing validation plan

This plan separates facts already established from the physical tests still
needed before RainPoint Local can claim repeatable sensor or valve enrollment.
Every test must retain raw RF evidence, normalized frames, radio-node logs,
event markers, device state, firmware versions, antenna placement, and the
result visible on the device or in the stock app.

## HCS026 sensor: established evidence

The following tests do not need to be repeated merely to demonstrate them
again:

- two factory identities established the deterministic high-bit paired
  identities `1bce0024` → `9bce0024` and `15a98024` → `95a98024`;
- both stock enrollments used the same sensor-side `01`, data `02`, short `02`,
  and terminal `03` progression and nearly identical cadence;
- the custom ESP32/CC1101 completed one isolated enrollment of `15a98024` and
  received subsequent moisture telemetry with the stock RainPoint gateway off;
- the custom ESP32/CC1101 completed an isolated enrollment of `1bce0024` using
  four captured replies, received terminal message `03`, and received routine
  telemetry under paired identity `9bce0024` with the stock gateway off;
- the stock gateway can race a custom pairing attempt even after a sensor is
  removed from the vendor app;
- app deletion produced no RF unpair command, and a subsequent sensor power
  cycle returned the deleted device to factory announcements;
- full and low battery states were physically correlated on both test sensors;
- receive-only discovery cannot complete physical pairing.

## HCS026 sensor: remaining physical tests

### Pending telemetry-channel assignment experiment

Use test Sensors A and B to determine whether any enrollment field controls
their long-term telemetry channel. Existing evidence shows that changing the
known pairing selector (Sensor B: 8 to 4; Sensor A: 5 to 4) did not move their
routine reports away from telemetry channel 0, so the selector must not be
treated as the telemetry-channel setting.

1. Confirm both sensors are heard from the Vegetable Garden radio node and
   record receiver RSSI after its August 13 relocation.
2. Re-enroll one test sensor at a time while changing only one candidate reply
   field.
3. Require terminal pairing message `03`, then record the first three routine
   reports and their CC1101 channels.
4. Repeat after battery removal and after an ordinary manual report.
5. Only declare telemetry-channel control when the same field moves a sensor
   reproducibly between channel 0 and channel 11.

If no controlling field is found, learn each device's telemetry channel from
valid post-pairing reports and use it for per-node receive scheduling.

### Sensor A local enrollment result

The 2026-08-12 isolated trial established that Sensor A requires a mixed
four-reply sequence for its observed request state: replies 1–3 from its first
stock enrollment followed by reply 4 from its captured rejoin. The first reply
used 433.4715 MHz, the remaining replies used approximately 434.0215 MHz, and
the successful response delay was 10 ms. The sensor then emitted terminal
message `03`, message `04`, and normal telemetry under identity `9bce0024`.
The stock RainPoint gateway remained unplugged.

The result validates this identity-specific profile but does not prove that
the differing branch is universal across every HCS026 revision. The profile
therefore remains evidence-labelled and endpoint-bounded.

Offline comparison also identifies a provisional pairing-subchannel encoding.
Reply 1 assigns a channel number in bytes 18–19; the sensor echoes the same
number in bytes 16–17 of its following message `01`. Selectors 4, 8, and 9
correspond to 433.4715, 433.9115, and 434.0215 MHz respectively, fitting a
110 kHz channel plan beginning at 433.0315 MHz within 50 Hz across four
captured exchanges. Sensor B has successfully used selectors 8 and 4, proving
that this frequency is negotiated during enrollment rather than permanently
tied to its identity. A controlled local-gateway test on August 12 then paired
Sensor B on selector 4 and Sensor A on selector 5. Both sensors echoed their
assigned selector, emitted terminal message `03`, resumed telemetry, and gave
the long blue success indication while the stock RainPoint gateway remained
unplugged. This proves that the selector is negotiated, but not that it must be
unique per association.

The follow-up same-selector test passed on August 12. Sensor A successfully
enrolled on selector 4 while Sensor B remained paired and powered on selector
4. Sensor B then reported 5% moisture and Sensor A reported 85%; the local
gateway decoded both under their distinct identities and both frames echoed
selector 4. Selector reuse is therefore supported and pairing logic must not
reserve a unique selector per device. Leave both sensors powered for longer
unattended observation of delivery cadence and collisions.

[HWG023-family documentation](https://manuals.plus/asin/B0DS2FDP62.pdf)
advertises up to 39 paired timers/devices, invalidating the earlier eight-device
inference.

Firmware `0.7.0-test.3` and gateway app `0.18.2` contain the
`hcs026_auto_v1` workflow. Home Assistant supplies neither a factory identity
nor an identity-specific transcript. The selected node adopts the first strict
HCS026 factory announcement, derives its paired identity, and generates the
common four-reply first-enrollment branch on shared selector 4. Sensor A passed
this automatic path end to end on August 12, including HA naming and entity
creation. Repeat it with Sensor B before S2 and retain the same RF evidence
required by S1.

```bash
python3 tools/analyze_pairing_profiles.py
```

### S1 — second-identity local enrollment (passed 2026-08-12)

The controlled Sensor A run passed every criterion below. Retain this procedure
as the regression sequence for future identities and hardware revisions.

1. Use the test sensor whose factory endpoint is not `15a98024`.
2. Record its label, hardware markings, LCD state, battery state, and factory
   endpoint before changing association state.
3. Capture one stock enrollment or rejoin immediately beforehand as the
   identity-specific reference.
4. Disconnect the stock RainPoint gateway from power and verify its RF silence.
5. Start simultaneous RTL-SDR and both-radio-node logging.
6. Arm a candidate profile only after its generated frames have been compared
   offline with that sensor's captured stock replies.
7. Hold the sensor button once and record every trigger, reply, frequency,
   latency, LED transition, and endpoint transition.
8. Require terminal message `03`, then trigger a manual moisture report and
   verify that the LCD value, local frame, gateway registry, and HA entity agree.

Pass criteria:

- no reply field was guessed solely from Sensor B;
- the sensor reaches its expected paired identity and emits terminal `03`;
- subsequent telemetry is decoded without the stock gateway or cloud;
- any identity-specific bytes are represented as profile parameters, not
  installation conditionals.

### S2 — persistence and rejoin behavior (release blocker)

After a successful local enrollment:

1. Power-cycle the sensor while the stock gateway remains off.
2. Confirm whether it boots under the paired or factory identity.
3. Power-cycle the custom local gateway and selected radio node independently.
4. Confirm the HA device identity and entity history do not change.
5. If the sensor asks to rejoin, capture the exact exchange and determine
   whether a pairing window is required or a bounded rejoin path is sufficient.

Repeat once after a gateway restart and once after a radio-node restart. A
routine reboot must never silently create a second HA device.

### S3 — unattended reporting without stock acknowledgements

Leave the locally paired sensor operating for at least 72 hours with the stock
gateway off. Preserve all frames and check:

- expected periodic and manual reports continue;
- unchanged moisture still produces approximately eight-minute updates, as
  specified by the HCS026FRF manual (the device measures every three minutes
  but refreshes the app every eight minutes, after manual detection, or after
  an automatic change greater than 5%);
- report cadence does not decay after a fixed number of unanswered messages;
- moisture changes propagate correctly;
- no unrecognized gateway acknowledgement is required;
- battery and last-report entities remain coherent;
- radio-node reconnects do not inflate logical report counts.

This test establishes local data reliability; it does not require deliberately
draining a battery.

The first run failed on 2026-08-13: Sensor B stopped at 00:58 and Sensor A at
04:59 after initially reporting successfully. Manual button presses later that
day produced no RF frame, while the SDR and both custom nodes continued to
receive established sensors. Reanalysis identified deterministic reversed
frames 177--188 ms after established sensor reports; A and B never received
them. Treat routine acknowledgement support as required unless the controlled
trial below disproves that interpretation.

For firmware `0.8.0-test.1`, repeat S3 as follows:

1. Flash only the selected test node with the routine-ack candidate target.
2. Keep the stock RainPoint gateway off and re-enroll one test sensor through
   that node. Confirm `authorized_until_reboot` for the paired endpoint.
3. Confirm the first routine report produces a byte-for-byte expected reply,
   `routine_ack_transmissions` increments, and the SDR sees the reply on the
   negotiated enrollment selector frequency.
4. Leave the node powered for 72 hours and verify periodic reports do not
   decay. Do not reboot it; authorization is intentionally boot-scoped.
5. Reboot the node and verify acknowledgements stop until an explicit rejoin
   completes. This is the fail-safe behavior for the candidate build.
6. Repeat with the second sensor before designing persistent authorization,
   reassignment, or forget synchronization.

First `0.8.0-test.1` trial started 2026-08-13 with the stock RainPoint gateway
unplugged. Sensor A (`9bce0024`) completed the four-step local enrollment on
selector 4 and became authorized until reboot. Its immediate routine message
`04` and a manual message `05` each caused the node to report a completed
transmission at 433.5165 MHz, for two sends and zero driver failures. Serial
output preserved the second generated reply:

```text
report: 79f4882f28b98402809bce00240581820205c400800000000000000000000000000000000276
reply:  79f4882f289bce00243984028085c1810001000000000000000000000000000000000000657f
```

The broad RTL-SDR path decoded both triggering reports but did not decode the
short replies, and the manual press did not produce a blue LED indication.
Neither observation proves RF failure: blue is validated as pairing feedback,
not routine-ack feedback, while the broad decoder can miss short replies.
Treat sensor receipt as unconfirmed until focused IQ captures show the emitted
carrier/timing or the isolated 72-hour cadence test demonstrates sustained
reporting. Do not reboot the node during that test because authorization is
intentionally RAM-only.

### S4 — selected-node and overlapping-receiver behavior

With two custom radio nodes and the RTL-SDR online:

1. Select the node closest to the sensor for pairing.
2. Verify exactly one node reports `tx_armed` and transmits replies.
3. Confirm the other node and RTL-SDR remain receivers.
4. Verify duplicate receptions update coverage for every receiver but create
   one logical sensor report and one HA activity event.
5. Repeat one manual report after moving the second node to a different area.

### S5 — physical interruption and recovery

Perform only on a disposable/unpaired test state:

- cancel before the first sensor announcement;
- cancel after the first reply;
- remove power from the selected node during an attempt;
- allow a pairing window to expire without pressing the sensor button.

In every case the gateway must report failure/incomplete state, persist no new
association, and start the next attempt disarmed. The sensor must either remain
factory-unpaired or have a documented, recoverable rejoin state.

### S6 — forget and reassociation semantics

1. Forget a locally paired test sensor in HA/RainPoint Local and confirm no RF
   unpair command is transmitted.
2. Confirm later telemetry remains recorded as evidence but cannot recreate an
   exposed HA device automatically.
3. Determine the sensor's physical reset/unpair gesture from controlled button
   and power-cycle tests.
4. Re-pair it and verify that the intended HA identity/history policy is
   preserved.

### S7 — soil profile (`P1`) encoding

The HCS026 LCD's `P1` indicator is the user-selectable soil type/profile shown
by the stock app; it is not a pairing-step or device-slot indicator. With a
test sensor paired to the stock gateway, capture one manual report at each
available profile while holding moisture and battery state constant. Determine
whether the selected profile is transmitted by the sensor, changes only the
display-side moisture calibration, or is stored solely in the stock app/cloud.
If it is an RF field, expose the raw and decoded value locally before adding a
writable HA setting. Record the available profile range and app labels as
product metadata rather than assuming `P1` is universal.

The physical HCS026FRF label (lot `202503`) documents these six profiles:

| Display | Label |
| --- | --- |
| P1 | Mixed soil |
| P2 | Peat soil |
| P3 | Black earth soil |
| P4 | Sandy loam |
| P5 | Laterite soil |
| P6 | Other soil |

The same label prints common moisture ranges of 1–30% dry, 30–70% moist, and
70–99% wet. These overlapping endpoints are transcribed as printed and should
not yet be treated as protocol thresholds.

### Sensor completion criteria

Sensor pairing can be described as model-supported only after S1 and S2 pass
on two distinct identities. S3 and S4 are required before recommending the
local path for unattended use. S5 and S6 are required before publishing the
pairing/removal UX as complete.

## HTV145 valve: safety boundary

Valve association is not valve control. Pairing work must not reuse the open
or close command builder, and a successful association must not be inferred
from TX success.

Use only the dedicated test valve. Keep it disconnected from pressurized water
for association experiments, with its outlet pointed safely and any motor
movement observable. Keep the production irrigation valve and its schedules
out of scope. Never intentionally factory-reset a production valve.

The stock RainPoint gateway must remain available until a complete stock
pairing and recovery record exists. The RTL-SDR remains the independent
reference receiver throughout custom-node work.

## HTV145 valve test sequence

### V0 — inventory and passive baseline

Before opening the stock app's pairing screen:

1. Photograph and record the exact model, label identifiers, firmware shown by
   the app, power source, buttons, LED states, and printed reset instructions.
2. Start a wide-band raw IQ capture covering the full known RainPoint window,
   plus normalized RTL-SDR and radio-node logs.
3. Install power without pressing any button and observe at least ten minutes.
4. Press each non-destructive button briefly once, separated by at least one
   minute, and mark the exact action time.
5. Identify factory announcements, channels, wake lengths, frame lengths, and
   any identity that is not part of the existing valve link.

Do not hold a button or invoke factory reset until its behavior can be recovered
through the stock gateway.

### V1 — first stock enrollment capture

1. Start raw IQ, normalized RF, radio-node, stock-app screen recording, and
   timestamped action markers before entering pairing mode.
2. Put the stock RainPoint gateway/app into valve enrollment mode.
3. Perform the valve's documented pairing gesture once.
4. Continue capturing for at least ten minutes after the app declares success.
5. Record every device-visible transition and the valve entry created in the
   cloud integration/HA, including model and identity metadata.
6. Trigger no watering during this phase unless the vendor workflow makes it
   unavoidable; if it does, keep the valve dry and record actuator movement.

Analysis must separate valve-to-gateway triggers from gateway-to-valve replies
by timing, endpoint direction, carrier, wake length, and repeated-frame
behavior. Do not assume the sensor's high-bit identity rule applies to valves.

### V2 — stock reboot, rejoin, delete, and repeat matrix

Capture each operation as a separate trial:

1. valve power cycle while still registered;
2. stock RainPoint gateway restart followed by valve power cycle;
3. app deletion while the valve remains powered;
4. valve power cycle after app deletion;
5. second complete stock enrollment;
6. third complete stock enrollment after another factory reset.

Three enrollments are the minimum needed to classify fields as stable,
identity-derived, session-generated, counters, timestamps, or random material.
Record whether app deletion itself emits RF and whether reboot uses a shorter
rejoin exchange.

### V3 — offline protocol reconstruction

Before custom transmission:

- normalize and promote the smallest complete exchanges into redacted fixtures;
- determine factory, paired valve, and controller identities without borrowing
  the installed valve's constants;
- classify every gateway reply byte by evidence and retain unknowns explicitly;
- measure trigger-to-reply latency, channel changes, symbol rate, deviation,
  polarity, wake length, repeat count, and completion indication;
- determine whether trailer residue, sequence, time, product code `0x012e`, or
  other counters participate in acceptance;
- implement a fail-closed symbolic profile and offline waveform round-trip
  tests with transmission disabled.

Exit criterion: replaying captured valve triggers through the symbolic state
machine selects exactly the captured reply sequence and rejects truncated,
duplicate, out-of-order, and identity-mismatched exchanges.

### V4 — SDR validation of custom reply probes

With the test valve unpowered and the stock gateway disconnected, emit each
candidate reply as an individually armed bench probe. Compare it with the
corresponding stock waveform using the RTL-SDR. Confirm carrier, deviation,
timing, polarity, wake, complete frame bytes, trailer, and power before allowing
automatic replies.

These probes must be compiled out of production firmware and must not contain
open or close frames.

### V5 — isolated custom valve enrollment

1. Keep the test valve dry and the stock gateway powered off; verify RF silence.
2. Start RTL-SDR and all radio-node logs.
3. Select exactly one nearby custom node and arm the identity-specific valve
   pairing profile for a short bounded window.
4. Apply the valve's pairing gesture once.
5. Require the complete captured terminal association signal plus ordinary
   post-pair telemetry; do not treat sent replies or an LED alone as success.
6. Confirm the gateway creates a provisional valve record, then name it in HA.
7. Power-cycle the valve, selected node, and custom gateway separately and
   verify stable association and HA identity.

If the valve unexpectedly opens, immediately remove valve power. Do not begin
bounded watering tests as part of this sequence.

### V6 — multi-node placement and ownership

1. Pair through the explicitly selected closest node.
2. Confirm all other nodes remain receive-only during association.
3. Verify receiver deduplication and coverage metrics from ordinary valve
   telemetry.
4. Persist the preferred transmitter assignment separately from valve RF
   identity.
5. Confirm changing node placement does not change the HA valve device.

The preferred node is not yet authorized to open the valve. Valve-control
testing begins later with the separate close-first/watchdog plan.

## Evidence record for every trial

Use `tools/rf_trial.py` to snapshot the gateway, establish an exact event
cursor, timestamp actions, retain only the trial's new gateway events, and
produce automatic route, message, known-stock-endpoint, and terminal-message
checks. The endpoint check supplements the required physical power-off and RF
baseline; it cannot independently prove that the stock RainPoint gateway is
silent. Preparation is always receive-only and writes
`rf_transmit_authorized: false` into the manifest.

Sensor A example (prepare only after the independent raw-IQ capture is active):

```bash
python3 tools/rf_trial.py prepare \
  --trial-id sensor-a-local-01 \
  --kind sensor_pairing \
  --gateway-url http://homeassistant.local:8787 \
  --selected-node rp-001122aabbcc \
  --stock-gateway-state off_verified \
  --factory-endpoint 1bce0024 \
  --paired-endpoint 9bce0024

python3 tools/rf_trial.py mark captures/trials/sensor-a-local-01 \
  sensor_button_held --detail "red flash followed by blue flash"

python3 tools/rf_trial.py finish captures/trials/sensor-a-local-01
```

For a new valve, omit the unknown endpoint arguments during V0/V1. Fill them
only after the captured exchange establishes the identities. Raw IQ, serial
logs, photos, and the HA recorder output remain required alongside this trial
bundle.

Record at minimum:

| Field | Required value |
| --- | --- |
| Trial ID | Stable name used by logs, markers, and fixture |
| Hardware | Model, label/revision, batteries/power, radio-node ID |
| Software | Stock app/gateway, add-on, integration, and firmware versions |
| Topology | Stock gateway on/off, selected TX node, active receivers |
| RF setup | Antenna positions, center/sample rate, node correction and power |
| Action | Exact button/app action and wall-clock timestamp |
| Result | Device LED/LCD/motor, app, HA, and RF terminal evidence |
| Frames | Trigger/reply identities, frequencies, latency, repeats, trailers |
| Recovery | Final association state and how the device returns to a safe state |

Failed attempts are evidence and must be retained. Do not tune multiple
variables within one trial.
