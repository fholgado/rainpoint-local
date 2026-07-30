# Passive monitoring — 2026-07-30

No hub, network, Home Assistant, or valve settings were changed for this
monitoring.

## Network capture

A bounded passive capture started at approximately 10:07 EDT:

```text
captures/rainpoint/rainpoint-passive-20260730-100622.pcap
```

It runs in detached screen session `rainpoint_passive_24h` and has a hard
24-hour timeout. Expected automatic completion is approximately 10:07 EDT on
2026-07-31. The capture uses the existing restricted UDM SSH key, whose forced
command permits only `tcpdump` filtered to the configured hub IP.

The capture observes existing traffic only. It does not redirect, block,
disconnect, deauthenticate, or modify the hub.

At 10:07:20 EDT, Home Assistant recorded a new Right Bed raw RF payload at the
same instant the hub sent a 217-byte TLS record and received a 33-byte
acknowledgment. This labels the common 217/33 network pattern as a single-device
sensor/status publication; it should not be interpreted as valve activity
without a simultaneous decoded state.

## Soil-sensor health baseline

Home Assistant Recorder history was queried from 2026-07-28 14:08 UTC through
2026-07-30 14:08 UTC. The HomGar entities were reloaded around 12:16 UTC on
July 30, which forms the beginning of the useful live-observation window.

| Sensor | Live events | Latest RF report | Latest moisture | Observed cadence |
|---|---:|---|---:|---|
| Right Bed | 26 | 10:07:20 EDT | 60% | average 4.4 min, maximum 8.8 min |
| Left Bed | 6 | 09:54:01 EDT | 64% | average 19.6 min, maximum 53.5 min |
| Front Yard 1 | none after reload | 20:20:07 EDT on July 29 | 61% cached | stale |
| Front Yard 2 | none after reload | 08:07:18 EDT | 82% cached | stale |

Because type 54 embeds a report timestamp, every genuine sensor report changes
the raw entity state even if moisture is unchanged. The lack of post-reload
state changes for Front Yard 1 and 2 therefore appears to be genuine staleness,
not merely Home Assistant suppressing duplicate values.

Possible causes to check only after returning home:

- sensor-to-hub range or obstruction
- sensor pairing/address mapping
- battery contact despite cached 100% state
- sensor reset or failed transmitter

No remote re-pairing or reset should be attempted while the property is
unattended.

## Passive research clues

The HWG023WRF FCC record confirms both Wi-Fi and 433.92 MHz operation. The
internal-photo report labels separate 433 MHz transmit and receive antennas,
which supports the observation that the hub is a bidirectional RF bridge
rather than a receive-only sensor gateway.

References:

- <https://fccid.io/2AWDBHWG023WRF>
- <https://fcc.report/FCC-ID/2AWDBHWG023WRF/7124941.pdf>
