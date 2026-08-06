# RainPoint 433/434 MHz capture plan

## Minimum hardware

For receive-only discovery:

- one RTL-SDR receiver covering 433.7 MHz
- one 433 MHz antenna with the correct connector
- a Mac or Linux computer near the RainPoint hub and valve

Suitable current receiver families include:

- RTL-SDR Blog V3
- Nooelec NESDR SMArt v5

The RTL-SDR Blog V4 also works technically, but its manufacturer announced it
end-of-line in May 2026. There is no reason to seek one out for this project.

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

`rtl_433` 25.12 is installed on the capture Mac. The receiver is not currently
attached.

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
  -X 'n=RainPoint,m=FSK_PCM,s=48,l=48,r=49152,bits>=620,match={40}79f4882f28' \
  -M time:iso:usec -M level -M bits
```

Decode an existing CU8 capture into a normalized 38-byte frame:

```sh
./tools/decode_rainpoint_iq.py captures/rf/<session>/g001_*.cu8
```

Keep the raw captures even when a decoded row looks correct. We need IQ/pulse
data to locate the address and checksum and to distinguish hub commands from
valve acknowledgements.

## Capture sequence

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
script, and HomGar sensor entities over the capture window. Treat recorder
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
- determine checksum/CRC

Transmit path:

- isolate hub-to-HTV145FRF open and close frames
- determine how duration is encoded
- determine whether a counter, nonce, or rolling code is present
- test replay only with physical observation and a ready stop path

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
