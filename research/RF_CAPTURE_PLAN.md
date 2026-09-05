# RainPoint RF research capture and validation guide

This is a reusable capture procedure, not a project-status list. Active work is
tracked only in `../PROJECT_ROADMAP.md`.

## Minimum hardware

For receive-only discovery and validation:

- one RTL-SDR receiver covering the 433/434 MHz band
- one 433 MHz antenna with the correct connector
- a Mac, Linux computer, or Home Assistant host near the devices

For later transmit testing:

- one ESP32 development board
- one **433 MHz** CC1101 SPI transceiver module
- one 433 MHz antenna
- jumper wires or a small soldered carrier

Do not buy an 868/915 MHz CC1101 module for this system; the matching network
and antenna need to suit 433 MHz.

An RTL-SDR cannot transmit. A HackRF-class SDR could capture and transmit, but
it is not required and is substantially more expensive than the two-stage
RTL-SDR plus CC1101 approach.

## Software

The deployed Home Assistant app and standalone development commands both use
`rtl_433`.

The repository includes a bounded capture helper that records raw I/Q signals,
decoded JSON, analyzer logs, session metadata, and an action timeline in one
ignored local directory:

```sh
./tools/capture_rainpoint_rf.sh --duration 15m
```

While it is running, timestamp an app or physical action from another terminal:

```sh
./tools/mark_rainpoint_rf_action.sh "valve start requested for 60 seconds"
./tools/mark_rainpoint_rf_action.sh "valve stopped manually"
```

The most recent session is available at `captures/rf/latest`. Capture artifacts
are intentionally ignored by Git because raw I/Q files can be large and may
contain unrelated nearby radio traffic.

The HCS026FRF filing specifies 433.7 MHz ASK, but its radiated-emission test
measured the fundamental at 434.07 MHz with 184.2 kHz occupied bandwidth. Local
captures contain RainPoint tone energy from approximately 433.08 MHz through
434.38 MHz. Use a 2.0 MHz window centered at 433.7 MHz so both the lower
data-rich sensor reports and the upper notification/control channel fit in one
capture.

Receive and save only matching RainPoint packets:

```sh
rtl_433 -f 433700000 -s 2000000 -R 0 -S known \
  -X 'n=RainPoint,m=FSK_PCM,s=50,l=50,r=50000,bits>=620,match={40}79f4882f28' \
  -M time:iso:usec -M level -M bits
```

Decode an existing CU8 capture into a normalized 38-byte frame:

```sh
./tools/decode_rainpoint_iq.py captures/rf/<session>/g001_*.cu8
```

Keep the raw captures even when a decoded row looks correct. We need IQ/pulse
data to locate the address and checksum and to distinguish hub commands from
valve acknowledgements.

The HTV145 and HTV405 enrollment analyzers can share one vectorized frequency
discriminator across every RF leg when NumPy is installed. This is strongly
recommended for multi-minute continuous-IQ files; the dependency-free fallback
remains suitable for small fixtures:

```sh
python3 -m pip install numpy
python3 tools/analyze_htv145_pairing_iq.py CAPTURE.cu8 \
  --factory-endpoint FACTORY --paired-endpoint PAIRED \
  --companion-endpoint COMPANION --controller-endpoint CONTROLLER
```

Use a capture of at least 300 seconds for a stock HTV145 enrollment. A
controlled 2026-09-01 trial measured the stock gateway's first RF transmission
at about 179 seconds in an earlier 180-second recording, leaving the successful
exchange outside the file. The five-minute capture retained the complete reset,
gateway boot, pairing, and post-enrollment idle tail.

## HTV145 stock pairing and dry control comparison

Use this procedure for the fresh stock comparison after candidate `.22`.
The [canonical roadmap](../PROJECT_ROADMAP.md) tracks completion. The user
requested watering-command captures in the same session as the new pairing;
the single-zone test valve is dry.

1. Keep the valve, stock gateway, and SDR positions documented and fixed.
   Verify custom pairing and control transmitters are disarmed for this valve;
   preserve existing sensor ACK ownership. Record firmware and battery condition.
2. Start continuous raw IQ before stock gateway startup or any pairing gesture.
   Use 433.7 MHz center, 2 Msps, and the established low gain of 0.9; check that
   both directions are visible without clipping. Allow at least ten minutes of
   recording and enough disk space (about 2.4 GB per ten minutes). Extend the
   bounded recording if setup runs long so it includes every command and the
   final idle tail. Record UTC action markers and capture-relative times.
3. Perform one user-assisted stock pairing. Retain the entire exchange,
   association endpoints, selector, carrier, app result, and LED observation.
   Require the complete valve-originated terminal request and matching
   controller reply for the captured branch; the counter-2 branch uses
   `84/2c/80/99` and `84/6c/81/80/19`. Validate other stock branches against
   their own transcripts rather than imposing counter-2 bytes.
   A white LED alone is insufficient. If terminal evidence is missing, retain
   the attempt for diagnosis and defer the control sequence.
4. After terminal enrollment and an idle baseline, use the stock app or the
   existing HA HomGar/RainPoint Cloud integration to command the stock gateway.
   For HA, verify the device is HTV145FRF, confirm the duration unit, and save
   the original duration setting before changing it. Issue the following
   actions on the single-zone test valve. Keep the same
   association throughout, with at least 30 seconds of confirmed idle between
   runs. Record actual action times rather than assuming the planned spacing.

   | Run | Requested duration | Stop action | Comparison |
   |---|---|---|---|
   | A | 60 seconds | Let the valve stop automatically | Open acknowledgment, autonomous stop, and final report/ACK exchange |
   | B | 120 seconds | Send stock Stop after about 30 seconds of observed opening | Duration encoding and explicit close/acknowledgment |
   | C | 60 seconds | Send stock Stop after about 20 seconds of observed opening | Repeat A's duration to distinguish counter changes from duration, and repeat explicit close |

   Record audible/visible motor movement, app state, and RF state separately.
   If an open is unconfirmed, do not stack further opens or treat a subsequent
   close as accepted-control evidence. Use the stock stop path if needed and
   retain the unresolved outcome. Confirm idle before proceeding.
5. Continue recording for at least 60 seconds after the last confirmed stop.
   Retain any delayed reports, gateway acknowledgments, and retries. Verify
   the valve is idle and custom pairing/control remains disarmed when done.
   Restore the original HA duration setting if it was changed for the trial.
6. Decode both RF directions using endpoints and carriers from this fresh
   association. For each action retain exact frame bytes and CRC/residue,
   wake length, request/response timing, retries, command counter, duration,
   action/result fields, and subsequent state. Distinguish an immediate
   command response from a later state report and its gateway ACK; an app
   indication alone does not establish RF acceptance. Check whether opens
   advance the counter and closes retain it, and whether autonomous stop
   involves any gateway transmission.
7. Compare the complete stock pairing with `.22`, then compare accepted stock
   controls with the existing stock fixtures and partial-pairing local probes.
   Preserve raw IQ privately and promote minimal exchanges to consistently
   redacted fixtures. This establishes a current stock baseline; successful
   stock control alone does not prove that local control requires step 6.

## Controlled capture sequence

Place the receiver close enough to see both hub and accessories without
overloading the front end.

1. Record five minutes with no user actions.
2. Note naturally occurring soil-sensor report timestamps.
3. Start the RainPoint valve for exactly 60 seconds.
4. Let it stop automatically.
5. Wait another five minutes.
6. Repeat once with a 120-second requested duration, then stop it manually
   after 30 seconds.

For every action, record local time to the second. Do not operate any unrelated
433 MHz remote during the experiment.

After every capture, query the Home Assistant recorder for all relevant valve,
script, and reference sensor entities over the capture window. Treat recorder
timestamps as the authoritative action/state timeline even when the operator
also supplies manual notes. Always include other irrigation systems in the
query so unrelated Zigbee or Wi-Fi valve actions are not attributed to
RainPoint RF traffic.

Use the repository helper to produce that timeline directly from the HA box:

```sh
./tools/correlate_ha_recorder.sh \
  --start '2026-01-01 12:00:00' \
  --end '2026-01-01 12:15:00'
```

## Analysis goals

Receive path:

- determine modulation and symbol timing
- identify preamble/sync and repeated packets
- locate device identity/address
- map the HCS026FRF moisture value to over-the-air bytes
- locate the HCS026FRF battery OK/low flag using a test sensor
- determine checksum/CRC

Transmit path:

- isolate hub-to-HTV145FRF open and close frames
- determine how duration is encoded
- determine whether a counter, nonce, or rolling code is present
- test replay only with physical observation and a ready stop path

## Battery-status experiment

The stock system exposes only battery OK (`100%`) or battery low (`10%`), so
the RF experiment should look for a flag or small enum rather than a voltage or
percentage field. Receiver-measured RSSI is not expected to appear inside the
transmitted packet.

1. Enroll a test HCS026 sensor and confirm the reference entity reports battery
   `100%`.
2. Record several button-triggered and periodic full-report/heartbeat pairs at
   normal battery voltage.
3. Verify the sensor's nominal voltage and polarity. Using a current-limited
   bench supply, reduce voltage in small steps without exceeding the nominal
   voltage; alternatively use measured, known-low batteries.
4. At each voltage, trigger a report and retain the raw RF frames plus the HA
   independently observed battery state and timestamp.
5. Continue only until the reference entity changes from `100%` to `10%`, then
   restore normal power promptly.
6. Diff both packet types bit-for-bit. Prioritize the heartbeat status sequence
   currently observed as `... 41 81 00 01 00 ...`, while accounting for the
   `41`/`c1` retransmission-bit change. Across 358 retained normal-battery
   heartbeats, normalized offset 17 was always `01`; the primary confirmation
   target is therefore a repeatable change from `01` to `02`--`04` as the stock
   reference changes to low.
7. Also look for a compact one-byte battery TLV. HomGar metadata assigns
   battery type 31, whose one-byte compact header is expected to be `0xdc`;
   candidate normal/low sequences are therefore `dc 01` and `dc 02`. Treat
   these only as search signatures until an RF transition confirms them.
8. Repeat the transition at least twice before assigning a battery field, then
   add positive and negative decoder fixtures.

This hypothesis was superseded by same-file IQ analysis: the reversed frames
are stock-gateway acknowledgements, not sensor heartbeats. The decoder now
retains acknowledgement identity/message metadata and does not derive battery
state from byte 17.

## Pairing discovery signatures

The product catalog gives exact model identifiers that may appear only during
enrollment or capability exchange:

| Device | Model code | Search both byte orders |
|---|---:|---|
| HWG023WBRF-V2 hub | `0x0121` | `01 21`, `21 01` |
| HTV145FRF valve | `0x012e` | `01 2e`, `2e 01` |
| HCS026FRF sensor | `0x013d` | `01 3d`, `3d 01` |

These sequences did not occur outside trailers in the 2,189 retained ordinary
telemetry events. A pairing experiment must save all detected signals because
the enrollment exchange may use a different sync word or frame length from
the known 38-byte telemetry format.

## Safety constraints

- Begin with receive-only work.
- Never transmit arbitrary fuzzed frames.
- Limit early watering commands to 60 seconds.
- Require an automatic timeout in the eventual bridge.
- Keep the original RainPoint app available as an emergency stop until local
  close behavior is verified repeatedly.

## Primary references

- Exact HTV145FRF filing, confirming 433.7 MHz:
  <https://fccid.io/2AWDBHTV145FRF>
- HCS026FRF test report, confirming ASK and the measured 434.07 MHz carrier:
  <https://device.report/m/c7ca872340efa550c43d8d4d9a2e9d8d50873e184d8837862a58108496aa0697.pdf>
- Community HCS021FRF FSK decoder and sensor-field analysis:
  <https://github.com/user-attachments/files/26152016/rainpoint_decoding.txt>
- Prior RainPoint OOK/Manchester investigation:
  <https://github.com/merbanan/rtl_433/issues/1781>
- `rtl_433`:
  <https://github.com/merbanan/rtl_433>
- TI CC1101 specifications:
  <https://www.ti.com/product/CC1101>
- Nooelec NESDR family specifications:
  <https://support.nooelec.com/hc/en-us/articles/360005805834-NESDR-Series>
