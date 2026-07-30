# RainPoint 433.7 MHz capture plan

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

Install `rtl_433` on the capture computer. The receiver is not currently
installed or attached to the Mac used for this research.

Initial analyzer command:

```sh
rtl_433 -f 433700000 -R 0 -A -S all \
  -M time:iso:usec -M level
```

Candidate flex decoder based on a prior RainPoint sensor investigation:

```sh
rtl_433 -f 433700000 -R 0 \
  -X 'n=RainPoint,m=OOK_MC_ZEROBIT,s=500,l=500,r=1500' \
  -S all -F json
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
- Prior RainPoint OOK/Manchester investigation:
  <https://github.com/merbanan/rtl_433/issues/1781>
- `rtl_433`:
  <https://github.com/merbanan/rtl_433>
- TI CC1101 specifications:
  <https://www.ti.com/product/CC1101>
- Nooelec NESDR family specifications:
  <https://support.nooelec.com/hc/en-us/articles/360005805834-NESDR-Series>
