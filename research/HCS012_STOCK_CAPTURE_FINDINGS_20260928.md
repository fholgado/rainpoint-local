# HCS012ARF stock-hub observations

September 28, 2026. Receive-only evidence from a user-identified HCS012ARF rain
gauge, initially powered with the stock hub already running **outside pairing
mode**, then battery-cycled while the stock app searched for a rain gauge.
The user reports successful app registration after the second boot. Previous
association was possible because this is used hardware, but is not established.
Project status belongs in [the roadmap](../PROJECT_ROADMAP.md).

## Evidence

Private capture: `captures/rain-gauge-stock-20260928/20260928-211940/continuous.cu8`.
Nominal start September 29 **01:19:40 UTC**; CU8, 2 Msps, center **433.9 MHz**,
gain 0.9 dB. User insertion confirmation arrived near capture second 76; the
actual insertion preceded it. App-search instructions followed near second 244;
the user reported success near second 326. Neither confirmation is an exact RF
event timestamp. The complete recording finished normally: **600 seconds,
2,400,000,000 bytes**, owner-only permissions. The main controller independently
verified SHA-256 against the capture manifest.

Offline `rtl_433` 25.12 protocol 276 identifies the device as
`RainPoint-HCS012ARF`. Default detection missed the weak burst; setting offline
`minlevel=-50` recovered it, independently confirmed with fixed `level=-30`.
Analysis uses overlapping bounded eight-second windows, not whole-recording
arrays. Raw IDs, packet bytes and debug logs remain private under
`analysis-hcs012/`, excluded from Git with owner-only permissions.

| Capture-relative packet time | Context | Raw byte 5 | Decoded result |
| --- | --- | --- | --- |
| 57.617775 s | First battery insertion, hub not pairing | `61` | Rain 0.0 mm; battery OK |
| 224.617173 s | No further user action yet | `60` | Same ID, rain 0.0 mm; battery OK |
| 299.031588 s | Battery insertion during stock-app search | `61` | Same ID, rain 0.0 mm; battery OK |
| 466.031010 s | Subsequent routine broadcast | `60` | Same ID, rain 0.0 mm; battery OK |

All four validate the additive checksum and retain raw byte 6=`03`.
Each boot-to-routine interval is approximately **167 seconds**; two intervals
are not a guarantee of fixed reporting cadence. Byte 5 bit 0 changes
`1 → 0 → 1 → 0`, corroborating a boot marker across two insertions and their
routine reports. Decoder output `flags1=24` (`18` hex) strips the two low bits
and would hide this difference. The user independently confirmed the stock app
also showed **zero rain and healthy battery** after registration. Battery-low
behavior has not been physically exercised.

The complete 600-second file was scanned in bounded windows, with additional
targeted windows verifying all four readings. Automatic detector acquisition
depends on the window boundary: one full-pass window missed the fourth reading,
which decoded in both the earlier overlapping pass and a targeted eight-second
window. Counts here describe verified distinct events, not proof that every
transmitted repetition or weak burst was recovered.

## Different physical protocol

The boot-adjacent burst has a narrow carrier around **433.9334 MHz**, measured
with uncorrected SDR oscillator error, and OOK/Manchester pulses around
305/610 microseconds. It is **not the native `51` FSK protocol** used by our
valve enrollment captures. The existing native decoder finds no validated
frames in seconds 0–100. During seconds 240–335 its only recovered exchange is
the already-known HTV213 valve's `02`/`82` pair at 280.352/280.437 seconds,
not a rain-gauge response. Baseline gauge samples have no ADC-rail clipping;
finite sensitivity, unsearched modulation and capture scope still prohibit a
claim that the hub transmitted nothing.

The primary upstream implementation describes a 10-byte, reflected Manchester
message: `a5` header; four-byte little-endian identity; flags byte; another flags
byte; two-byte little-endian rainfall count; and the low byte of the sum of
bytes 1–8. Its decoding scale is 0.1 mm per count, and byte 5 bit 1 is battery
low. Upstream itself leaves the high-range rainfall representation unresolved.
Only zero rainfall and the boot/routine flag difference are measured here; the
scale, nonzero increments, battery-low response, overflow and reset behavior
remain unqualified on this unit. Source:
[rtl_433 HCS012ARF decoder](https://github.com/merbanan/rtl_433/blob/master/src/devices/rainpoint_hcs012arf.c).

## Consequences for local support

The same identity and ordinary reading format before and during successful app
registration support **hub-side learning of a broadcast identity** as a working
hypothesis. They do not prove there is no device-side association or receive
path. Avoid importing valve assignment, phase, ACK or channel-sweep assumptions
into this model. Local support would need its own OOK receive profile and
decoder; investigate coexistence with continuous FSK reception before choosing
a radio arrangement. The stock hub's physical radio design alone is not proof
that a single custom receiver can cover both modes without losses.

An observed nonzero reading, compared with the app and a known tipping event,
would discriminate cumulative totals, count scale and boot-reset semantics
more usefully than another valve-style pairing attempt. This file records
evidence and interpretation, not a second task checklist. Upstream GPL decoder
code is a research reference, not code copied into the runtime.
