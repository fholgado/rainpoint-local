# RainPoint 433 MHz RF protocol

This is the primary protocol reference for the RainPoint devices supported by
this project. It describes behavior demonstrated by local RF captures. Dated
capture notes and cloud-side observations live under `research/` and are not
part of the protocol contract.

## Protocol at a glance

| Property | Confirmed value |
|---|---|
| Devices tested | HTV145FRF and HTV405FRF valves, HCS026FRF soil sensor, HWG023WBRF-V2 hub |
| Band | 433/434 MHz |
| Modulation | 2-FSK PCM |
| Symbol width | 50 microseconds, 20.0 ksymbols/s |
| Sync word | `79 f4 88 2f 28` |
| Normalized frame | 38 bytes |
| Prefix/wake forms | About 320, 1,200, or 2,400 symbols before sync |
| Receive implementation | RTL-SDR with `rtl_433` |
| Planned transceiver | ESP32 with a 433 MHz CC1101-class radio |

The working `rtl_433` flex decoder is:

```text
n=RainPoint,m=FSK_PCM,s=50,l=50,r=50000,bits>=620,match={40}79f4882f28
```

A 2.0 Msps capture centered at 433.7 MHz has been the most useful general
receive configuration. Installed-device energy has appeared across roughly
433.08--434.38 MHz, so narrower captures can miss valid report types.

### Measured RF parameters

FFT and pulse analysis of 25 clean 2.0 Msps CU8 captures produced:

| Parameter | Measured result |
|---|---:|
| Symbol rate | 20,000 symbols/s |
| Symbol period | 50.0 microseconds; dominant runs were 100 samples at 2.0 Msps |
| Tone separation | 79.997 kHz average |
| Frequency deviation | approximately +/-40.0 kHz |
| Lower channel center | 433.142217 MHz mean across 21 captures |
| Upper channel center | 434.241535 MHz mean across 4 captures |
| Channel separation | approximately 1.100 MHz |
| 95% occupied bandwidth | typically 100--105 kHz |
| 99% occupied bandwidth | typically 180--207 kHz; sensitive to CU8 clipping |

The per-device lower-channel centers differ by several hundred hertz, while
the two channel groups are almost exactly 1.100 MHz apart. The working nominal
centers are therefore `433.140 MHz` and `434.240 MHz`; the additional measured
1--3 kHz is consistent with transmitter and RTL-SDR oscillator error. Both
channels use the same approximately 80 kHz tone separation.

The short prefix is approximately 320 alternating symbols (16 ms). Long
wake/command traffic uses approximately 1,200 alternating symbols (60 ms).
A repeatable 2,400-symbol sensor form lasts 120 ms and begins with a variable
constant-tone interval before a long alternating suffix. The 38-byte frame
itself lasts 15.2 ms. Pulse-slicer start alignment can move the reported prefix
count by a few symbols, so these durations are more portable than a particular
decoded offset.

### Initial CC1101 receive profile

For a CC1101 module with a 26 MHz crystal, the first receive-only prototype
should use this profile and validate it against the RTL-SDR before refinement:

| Setting | Candidate value | Actual result |
|---|---:|---:|
| Modulation | 2-FSK | no Manchester, whitening, FEC, or hardware CRC |
| `MDMCFG4` | `0x89` | 203.125 kHz RX bandwidth; data-rate exponent 9 |
| `MDMCFG3` | `0x93` | 19.9852 ksymbols/s |
| `MDMCFG2` | `0x02` | 2-FSK with exact 16/16 sync qualification |
| `DEVIATN` | `0x45` | 41.2598 kHz expected deviation |
| `FREQ2/1/0` | `10 a8 c3` | 433.139862 MHz base channel |
| `MDMCFG1.CHANSPC_E` | `1` | used with `CHANSPC_M` below |
| `MDMCFG0` | `0xf8` | 99.9756 kHz channel spacing |
| Channel number | `0` or `11` | 433.139862 or 434.239594 MHz |
| `SYNC1/0` | `79 f4` | validate the remaining `88 2f 28` in software |
| `PKTLEN` | `0x24` | 36 bytes after the two hardware-sync bytes |
| `PKTCTRL0` | `0x00` | fixed length; hardware whitening and CRC disabled |
| Fixed received bytes after hardware sync | 36 | prepend `79 f4` to reconstruct the 38-byte normalized frame |

The CC1101's closest deviation setting is about 1.26 kHz above the measured
value; receive validation will show whether `0x45` or the next-lower `0x44`
performs better. The 203 kHz filter is intentionally conservative enough to
cover the clipped-capture 99% bandwidth and oscillator error.

This is a receive profile, not yet a safe transmit recipe. The CC1101 hardware
preamble generator is shorter than RainPoint's observed 40-, 150-, and
300-byte-equivalent prefixes. Transmit firmware will need FIFO/continuous or
asynchronous streaming to reproduce the complete wake sequence, sync, frame,
and retry timing rather than relying on ordinary packet-mode preamble output.

## Frame format

Every decoded packet normalizes to:

```text
79 f4 88 2f 28 | endpoint A (4) | endpoint B (4) | body (23) | trailer (2)
```

| Offset | Length | Meaning | Status |
|---:|---:|---|---|
| 0 | 5 | Sync word | Confirmed |
| 5 | 4 | Endpoint A | Confirmed field; physical direction is role-dependent |
| 9 | 4 | Endpoint B | Confirmed field; physical direction is role-dependent |
| 13 | 23 | Message body | Partially decoded |
| 36 | 2 | CRC-CCITT-derived trailer | Partially confirmed; selector unresolved |

The endpoint fields should not yet be treated as ordinary source and
destination MAC addresses. Their order reverses in valve request/response
traffic, while sensor reports use two observed route shapes.

## Known endpoints

| Association | Endpoint | Evidence |
|---|---|---|
| Hub/controller side of valve exchange | `b42d008f` | Open and close requests |
| HTV145FRF valve side of exchange | `b9840280` | Immediate valve responses |
| Right Bed HCS026FRF | `9ce58024` | Repeated moisture matches |
| Left Bed HCS026FRF | `c4e50024` | Controlled 58% and 12% matches |
| Front Yard Sensor 1 | `ce628024` | Repeated 59% matches |
| Front Yard Sensor 2 | `d1e28024` | Repeated 78--79% matches |
| Sensor companion/acknowledgement route | `39840280` | Short frames following lower-channel reports |

Friendly names are installation-specific. The stable endpoint values are the
portable part of the protocol.

## HTV405FRF four-zone control reports

A dry, isolated HTV405FRF was enrolled through the stock RainPoint gateway and
tested in a crossed matrix: Zones 1--4 at both 60 and 120 seconds. Every open,
stop, and subsequent closed-state report used one paired chassis endpoint.
The four ports are therefore selected inside the message body; they are not
four independent RF devices.

Stock gateway control frames have the confirmed signature below. Offsets are
from the beginning of the normalized 38-byte frame:

| Offset | Confirmed meaning |
|---:|---|
| 17 | `0x85` in open and stop control frames |
| 18 | Low seven bits contain the zero-based zone-pair index |
| 19 | High bit selects the odd-numbered member of the zone pair |
| 20 | Low seven bits are `0x4f`; high bit is set while watering |
| 25 | `0x40` in all observed control frames |
| 26 | Low seven bits matched remaining time in two-second units |
| 28 | `0x56` in all observed control frames |
| 29 | Requested duration in two-second units while watering; high bit set |

The one-based port number is:

```text
zone = 2 * (frame[18] & 0x7f) + ((frame[19] >> 7) & 1)
```

This produced Zones 1, 2, 3, and 4 across both tested durations. Requested
duration decoded as `(frame[29] & 0x7f) * 2`: `0x9e` represented 60 seconds and
`0xbc` represented 120 seconds. At the first RF observation, offset 26 decoded
to 54 or 114 seconds, matching the roughly six-second app-to-radio delay. Stop
frames cleared the watering bit and did not expose stale duration state.

Automatic one-minute stops and manual stops both produced a stop frame followed
by a distinct closed-state report. The observed confirmation delay ranged from
less than one second to about nine seconds. The receive decoder implements
these fields, but HTV405 frame construction remains deliberately unavailable
until custom enrollment, acknowledgement, idempotent close, and the node-local
watchdog are validated on the isolated valve.

Local enrollment on August 18 produced the same four-zone layout with offset
17 equal to `0x05`. A later raw stock-control capture disproved the interim
interpretation that its high bit universally distinguishes stock commands from
local reports: association branch and command body must be treated together.
The valve retained its paired endpoint after battery removal and emitted
periodic paired-link reports every roughly 40 seconds. A live chassis check
also confirmed that only one outlet can be active at a time: opening another
zone ends the previous zone. HA therefore models the four outlets as mutually
exclusive states under one valve device.

On August 19 the valve was re-enrolled by the stock gateway on selector branch
6, then Zone 1 was requested for 120 seconds and stopped manually after roughly
45 seconds under a raw 2.0 Msps SDR burst capture. The recovered commands were:

```text
open  79f4882f28b984028094a9801309810786058090cf8000000040b90056bc0000000000004d64
close 79f4882f28b984028094a980130a0107860580804f80000000408000568000000000000045ff
```

Both commands used a 320-symbol wake and appeared at approximately 433.1417
MHz in the same SDR. The open used sequence 9 repeat phase; the close advanced
to sequence 10 primary phase. This supports a controller-owned transaction
counter and rejects the failed trial's 1,200-symbol wake and selector-2 pairing
reply channel as the routine control envelope.

The selector-6 stock commands contain marker pair `86 05`, whereas historical
selector-2 stock controls contain `82 85`. Local selector-2 reports contain
`82 05`. Offset 17 is therefore not a universal direction bit, and a validated
association must carry its command profile as a unit: branch marker, command
marker, carrier, wake, endpoints, transaction phase, and trailer. The exact
local selector-2 command marker remains a physical-test gate; the isolated
trial currently retains its locally observed `82 05` profile rather than
substituting the historical stock selector-2 marker.

An association-specific, offline-only close candidate builder now reproduces
the captured local `0x05` idle body. It requires the paired endpoints, current
five-bit sequence, zone, selector, repeat phase, and trailer residue explicitly.
It remains disconnected from the gateway API and radio firmware; the first RF
control trial is still an idempotent close on the dry test valve.

### HTV405FRF enrollment exchange

A second isolated enrollment captured the complete stock-gateway exchange.
The factory endpoint `14a98013` became `94a98013`, again by setting the high
bit of the first endpoint byte. The valve then exchanged messages `01` through
`09` with companion route `39840280`. The full request/reply transcript is
retained in `research/fixtures/htv405_gateway_pairing_replies.json`.

The initial assignment reply occupied a distinct channel near 433.506 MHz and
used tones near 433.471 and 433.541 MHz: approximately 70 kHz separation and
35 kHz deviation. Its upper tone was weaker, so a midpoint-only demodulator
missed the frame. Subsequent gateway replies moved near 434.351 MHz and used
the ordinary approximately 80 kHz tone separation, while valve requests were
near 433.142 MHz. Valve enrollment must therefore support a separate initial
reply profile rather than reusing the HCS026 sensor profile unchanged.

The first timing estimate used close timestamps from separate rtl_433
signal-grabber files. That method incorrectly placed the reply at the end of
the request because file-close scheduling is not a precise common clock. A
later continuous 90-second, 2.0 Msps recording measured the factory request at
26.917473--26.948703 seconds and the accepted stock assignment beginning at
26.999359 seconds. The stock gateway therefore waits 50.656 ms after receive
completion, or 81.886 ms from request start to reply start.

The first local 0.12.1 on-air trial decoded to the intended assignment frame
with the correct 320-symbol wake, polarity, and approximately 35 kHz
deviation, but its carrier was centered near 433.454 MHz instead of 433.506
MHz. In the same capture the valve announcement was within 46 Hz of the stock
reference, ruling out material SDR drift. The test node therefore transmitted
52,154 Hz below its requested center. HTV405 enrollment now applies a
node-specific +97,154 Hz correction to the compiled 433.461 MHz profile center;
the established +45 kHz HCS026 correction remains unchanged.

A follow-up 0.12.2 capture measured the corrected local reply near 433.507
MHz, within about 1.1 kHz of the stock assignment center. It also exposed a
remaining approximately 4.2 ms silent gap between the end of the valve request
and the beginning of the local reply. Firmware 0.12.3 therefore pre-initializes
the ESP32 RMT transmitter when the bounded pairing window is armed and defers
the redundant CC1101 receive recovery until after the time-critical reply.

The physical 0.12.3 trial decoded the complete local reply and measured its
carrier at 433.505786 MHz, only 244 Hz below the stock center, with the expected
70.007 kHz tone separation and 35.004 kHz deviation. The valve still rejected
it. The same capture showed that the turnaround gap fell to approximately 1.1
ms. CC1101 fast
frequency hopping permits calibration values to be measured ahead of time and
restored for a roughly 75 us PLL transition instead of recalibrating on every
hop. The 0.12.4 candidate caches both HTV405 reply-frequency calibrations when
the bounded pairing window is armed. Continuous stock timing subsequently
showed that these optimized candidates were rejected because they replied
about 50 ms too early, not because their optimized turnaround remained slow.

Three successful stock assignments also exposed at least two selector
branches. The original selector-6 assignment contains `03 06` and leads to
valve request marker `86` plus the upper routine-reply channel. Two later
selector-2 assignments contain `03 02`, lead to request marker `82`, and use a
different routine channel. Their differing clock-marker layouts are therefore
branch-specific and must not be mixed. Firmware 0.12.5 retains the captured
selector-6 transcript, supplies the current local clock without the HCS026
four-minute lead, and adds a 50 ms software delay before the cached hop.

The isolated 0.12.5 trial then measured about 51.4 ms between receive completion
and the local assignment, but the valve still repeated its factory announcement.
This rules out the large timing error while leaving selector choice as the
strongest observed difference. Firmware 0.12.6 therefore follows the complete
selector-2 branch from the two latest accepted stock enrollments: its assignment
markers, request marker `82`, initial reply channel, and routine reply channel
move together. Watering-command transmission remains disabled.

The recovered 0.12.6 assignment was otherwise structurally identical to the
accepted selector-2 form and appeared near 433.550 MHz, but its packed clock
decoded as 10:44:56 for an attempt made at approximately 10:40:56. The gateway
command was independently verified to contain the current wall clock. Firmware
0.12.7 therefore anchors the elapsed-time reference after CC1101 frequency
preparation rather than before it, leaving all RF and selector variables fixed.
The recovered 0.12.7 reply encoded 10:59:00 for the 10:59:00 physical attempt,
proving that correction. Its 38-byte frame differed from the accepted 09:55
selector-2 assignment only in the expected minute field and regenerated
trailer. The valve nevertheless repeated its factory announcement and the
local session stopped after step 1. The remaining leading hypothesis is the
sub-millisecond receive-to-transmit envelope; split signal-grabber files cannot
measure that accurately enough. A subsequent continuous local capture measured
83.2 ms from request start to reply start, compared with 81.9 ms for the
accepted stock exchange under the same detector. Firmware 0.12.8 therefore
reduces only the software delay from 50 ms to 49 ms; its expected physical
reply is within roughly 0.3 ms of stock.

The 0.12.8 physical trial still stopped after its first transmitted reply,
falsifying the small delay error as the primary rejection cause. Re-running the
same spectral analyzer on isolated local and accepted-stock selector-2 replies
then exposed a stronger error: local centered at 433.546375 MHz while stock
centered at 433.556430 MHz. The valve's own request differed by only 46 Hz
between those captures, ruling out meaningful SDR drift. Both replies retained
approximately 70.0 kHz tone separation and 35.0 kHz deviation. Firmware 0.12.9
therefore raises only the selector-2 initial assignment center by 10.055 kHz;
the independently observed routine channel remains unchanged.

The first routine replies mirror the request message counter in the low seven
bits of byte 13 and contain `41 01` in bytes 14--15. An isolated local pairing
on August 19 physically validated the selector-2 assignment and the first two
routine replies. The valve gave its white success flash and continued under
paired endpoint `94a98013` even though the selected node had advanced through
only three transmitted steps. The successful assignment decoded as:

```text
79f4882f2894a980133984028080c0858503027000bc8c930d01008000000000000000006d56
```

It centered at 433.556537 MHz in the same SDR, only 107 Hz above the accepted
stock selector-2 reference. The first two local routine replies centered at
433.476260 MHz and decoded exactly. This proves that the retained 18-row
transcript is useful for modeling but is not a minimum completion counter. A
strict paired-link frame observed by any receiver after the selected node
transmits reply 1 is sufficient session-scoped evidence of acceptance.
Historical registry presence must never complete a new pairing session.

Executable transcript modeling found one important exception to a naive
alternating-burst interpretation: the request labeled
`paired_message_2_repeat` is followed by another valve-routed frame, not a
gateway reply. A local pairing controller must advance that step without
transmitting. The experimental firmware profile therefore contains 18 observed
request steps but only 17 transmissions. Physical success may occur after the
first three transmissions; the remaining rows describe traffic observed in
the stock transcript rather than a required local completion threshold.

The candidate local-pairing implementation requires the factory endpoint,
valve route, and companion route to be supplied explicitly from the association
under test. It derives only the high-bit paired identity, changes CC1101
deviation from approximately 35 kHz on the initial assignment to the ordinary
approximately 41 kHz profile afterward, and exposes no valve-control command.
The fixture distinguishes measured on-air reply centers from the CC1101 command
centers: the latter are 45 kHz lower because the calibrated node offset is
applied by the authenticated pairing command at transmit time.

## HCS026FRF enrollment lifecycle

Two controlled sensors established the same receive-side enrollment sequence.
An unpaired sensor announces a factory identity through endpoint `80000000`.
The subsequent sequence uses a paired identity formed by setting bit 7 of the
factory identity's first byte:

| Sensor | Factory identity | Paired identity |
|---|---|---|
| Test Sensor A | `1bce0024` | `9bce0024` |
| Test Sensor B | `15a98024` | `95a98024` |

Both enrollments used sensor message types `01`, `02`, `02`, and `03` at the
same repeatable cadence. The sensor frames occupied a lower channel near
433.14 MHz. Each was followed by a roughly 31 ms burst on a second channel;
the normal decoder missed these because they use only a 320-symbol wake prefix.
Offline clock recovery extracted valid 38-byte frames with the established sync
word and trailer residues. Their endpoint direction is paired sensor identity
to `39840280`, confirming that they are stock RainPoint gateway replies.

The initial replies immediately following each factory announcement were:

| Sensor | Reply channel | Initial gateway reply |
|---|---:|---|
| A | ~433.471 MHz | `79f4882f289bce002439840280814088050304f000adf18a0d00808000000000000000004c41` |
| B | ~433.472 MHz | `79f4882f2895a98024398402808140880503847000f4730a0d008080000000000000000060a8` |

Subsequent gateway acknowledgements moved to a per-session channel: about
434.021 MHz for Sensor A and 433.912 MHz for Sensor B in the August 10
sessions. A second successful Sensor B enrollment on August 11 kept every
gateway reply at about 433.4715 MHz. All recovered first enrollment, repeat
enrollment, and rejoin frames are retained in
`research/fixtures/hcs026_gateway_pairing_replies.json`.

The channel is explicitly assigned during enrollment. Reply 1 encodes a
selector in bytes 18–19, and the sensor echoes it in bytes 16–17 of its next
message `01`. The observed channel plan is:

```text
frequency_hz = 433031500 + selector * 110000
```

Controlled local-gateway tests on August 12 assigned selector 4 (433.4715 MHz)
to Sensor B and selector 5 (433.5815 MHz) to Sensor A. Each sensor echoed the
requested selector, completed its full enrollment exchange, produced the long
blue success indication, and resumed telemetry with the stock gateway
unplugged. Sensor B had previously paired on selector 8, proving that selectors
are association parameters rather than fixed properties of device identity.

A subsequent controlled test paired Sensor A on selector 4 while Sensor B was
already paired and powered on selector 4. With the stock RainPoint gateway
unplugged, Sensor B reported 5% moisture and Sensor A immediately followed with
an 85% report. The local gateway decoded both as their distinct addressed
identities, and both frames echoed selector 4. This proves that selectors may
be shared by multiple associations and are not unique device slots. Longer
unattended observation remains useful for measuring collision and delivery
reliability, but local pairing must not enforce selector uniqueness.

Current [HWG023-family product literature](https://manuals.plus/asin/B0DS2FDP62.pdf)
advertises support for up to 39 timers or irrigation devices, so the earlier
eight-device inference from selectors 4–11 was incorrect.

### Automatic HCS026 identity adoption

The two stock first-enrollment transcripts have the same four reply payloads
after normalizing only the paired endpoint in bytes 5–8, the clock in bytes
21–24 of reply 1, the reply-1 channel selector, and the two-byte trailer. Their
factory announcements also share this strict body signature:

```text
message 01 00 83 82 7f a4 1e 80; endpoint association bit clear; suffix 24
```

The standard radio-node firmware implements the model-level profile
`hcs026_auto_v1`. The gateway supplies no RF identity. During an explicitly
armed window, the selected node accepts the first trailer-valid announcement
matching the signature above, derives the paired endpoint by setting the high
bit of the first endpoint byte, substitutes it into the common reply template,
assigns shared selector 4, rewrites the trailer, and locks the session to that
identity. Unrelated frames cannot select a target, and terminal message `03`
remains mandatory.

The common path has now completed physical pairing across independent test and
installed HCS026 identities. Known sensors can also repeat their strict factory
announcement after becoming dormant. The gateway recognizes the retained
factory-to-paired mapping, selects the existing ACK owner, and sends one bounded
rejoin reply; this restored ordinary telemetry on both test identities without
deleting their HA devices or removing batteries. Factory counters 1, 2, and 4
are the validated retry forms. Unknown identities still require an explicitly
opened pairing window.

### Related rtl_433 work

[`rtl_433_ESP`](https://github.com/NorthernMan54/rtl_433_ESP) ports the upstream
`rtl_433` demodulators and device decoders to
ESP32 radios. Its release-25.02 snapshot includes two older RainPoint OOK
decoders, but neither matches the HCS026FRF/HTV145FRF/HWG023WBRF-V2 generation
documented here. Current upstream `rtl_433` added a separate
[`bresser_garden.c`](https://github.com/merbanan/rtl_433/blob/master/src/devices/bresser_garden.c)
decoder in July 2026 for an older Fujian Baldr/HomGar/RainPoint FSK garden
family. It is not yet present in the reviewed `rtl_433_ESP` snapshot.

That related family independently confirms several useful architectural
patterns: 20 kbit/s FSK PCM, fixed-size addressed frames, request/reply message
types, bidirectional pairing, autonomous valve schedules, measured water usage,
run-duration reporting, and configurable RF channels. Its sync word, device
models, channel plan, payload layouts, and pairing data differ from our tested
generation, so its byte offsets cannot be imported as HCS026/HTV145 facts.
The upstream code is GPL-licensed while this project is MIT-licensed; use it as
a research reference or separate process, not copied implementation code.

The second Sensor B capture also identified the principal dynamic field in
the initial reply. Bytes 21--22 contain a little-endian FAT/DOS-style packed
local time (five hour bits, six minute bits, and five two-second units), while
bytes 23--24 contain a packed date whose seven-bit year is relative to 2020.
The old reply encoded August 10 at 14:31:40; the newly accepted reply encoded
August 11 at 14:55:56. Replaying the stale first reply was rejected even after
its carrier, polarity, envelope, power, and response delay matched the stock
gateway. The bench firmware now requires a fresh operator-supplied local time,
patches these four bytes, and regenerates the known `0x4f03` trailer residual.
Other changed initial-reply bits remain session/allocation candidates rather
than generalized fields.

The first ESP32/CC1101 exchange to assign a paired identity followed on August
11. A reply
using the Mac's current local time was ignored; using the stock RainPoint
gateway's observed clock, four minutes ahead, was accepted immediately. Sensor
B changed to paired identity `95a98024`, the prototype sent the two follow-up
acknowledgements, and emitted its short message `02`. The original firmware
then incorrectly treated three transmitted replies as completion and disarmed.
Unlike both stock enrollments, the sensor never emitted terminal message `03`
and produced no later moisture reports, including after a controlled change to
66%. This was a successful reply/identity-assignment milestone, but not a
complete enrollment. The exact locally transmitted sequence is preserved as
`sensor_b_local_enrollment_20260811` in the fixture. The four-minute correction
is an observed clock offset for this installation, not yet a universal
protocol constant; a publishable coordinator should obtain or configure its
target pairing clock instead of hard-coding it.

The paired sensor's stock message `01` and data message `02` set byte 20 to
`0x80`; the first local exchange set it to `0x00`. The first local reply encoded
15:13:42 for a factory announcement at 15:10:12—only 3 minutes 30 seconds
ahead—because the bench firmware froze the operator-supplied time while the
stock reply was exactly four minutes ahead. Firmware 0.3.2 advances the
supplied gateway clock with elapsed time.

A second local exchange encoded 15:55:02 exactly four minutes after its
15:51:02 factory announcement. The sensor then restored byte 20 to `0x80`,
matching stock, and gave a visibly longer blue flash. It nevertheless omitted
terminal message `03`. After its LCD was changed from 1% to 99%, a manual
button report produced no paired-endpoint frame on either the RTL-SDR or the
ESP32 receiver. Byte 19 was `0x00` in the second exchange while the LCD read
1%, compared with `0x05` in the stock exchange when the sensor read 5%; byte
19 is therefore more plausibly sensor data than an enrollment-status flag.
The first gateway reply is otherwise structurally identical to the successful
stock reply after accounting for its packed time and regenerated trailer.
Offline spectral comparison also placed its carrier within 600 Hz of stock
and matched deviation and occupied bandwidth. The remaining failure is not
explained by the previously suspected status byte or an obvious decoded RF
parameter.

Envelope comparison did expose one RF-layer difference: the prototype enabled
its PA about 140 microseconds before RMT began the alternating wake, while the
stock gateway's usable carrier began within about 30 microseconds of the wake
boundary. The prototype had entered TX directly from IDLE, leaving the first
data level static while the CC1101 synthesizer calibrated. Firmware 0.3.3 first
entered `FSTXON`, moving calibration and settling behind the gated PA, but an
SDR probe still measured a 110-microsecond lead. The remaining delay was the
firmware's MARCSTATE SPI polling after `STX`, during which the PA was already
active. Firmware 0.3.4 removed that poll, but two controlled probes emitted no
recoverable RF burst; starting synchronous RMT immediately after the strobe was
not a valid replacement. Firmware 0.3.5 instead starts the 320-symbol RMT wake
asynchronously with the PA gated, issues `STX` immediately, and then waits for
RMT completion. This overlaps only the expendable beginning of the long wake
with the STX-to-PA transition and avoids a static carrier lead. Physical SDR
validation recovered the exact 38-byte probe frame. Its carrier was 473 Hz
from stock, tone separation was within 152 Hz, and 95% occupied bandwidth was
within 91 Hz. Usable carrier began 10 microseconds before the nominal wake
boundary, versus 30 microseconds after it for stock: a 40-microsecond difference
smaller than one 50-microsecond symbol. Firmware 0.3.5 is therefore the first
probe to match both the decoded waveform and the stock envelope closely enough
for another controlled enrollment attempt.

That controlled attempt first ran while the stock RainPoint gateway was still
powered. The local node transmitted all three expected replies and the sensor
reached its short message `02`, but it did not emit terminal message `03`.
Independent SDR reception found an additional gateway frame immediately after
the short `02`:

```text
79f4882f2895a980243984028082c28082800000000000000000000000000000000000002a72
```

Its carrier and occupied bandwidth matched the stock gateway rather than the
ESP32/CC1101 node. The stock gateway can therefore interfere with a local
migration enrollment even after the sensor has been deleted from the vendor
app.

Repeating the experiment with the stock gateway disconnected completed the
entire local enrollment. Firmware 0.3.5 transmitted these three replies:

```text
79f4882f2895a98024398402808140880503827000d4830b0d01008000000000000000002baf
79f4882f2895a980243984028081c18200009f800000000000000000000000000000000077dc
79f4882f2895a980243984028082418100010000000000000000000000000000000000003622
```

Sensor B changed from factory identity `15a98024` to paired identity
`95a98024`, emitted the expected short message `02`, terminal message `03`, and
then messages `04`, `05`, and `06`. After the LCD was changed to 11%, the
locally paired sensor reported:

```text
79f4882f28b984028095a980240581820205c405800000000000000000000000000000006de1
79f4882f28b984028095a980240601820205c405800000000000000000000000000000007869
```

Both frames are trailer-valid and encode 11% as `0x05 * 2 + 1`. This verifies
physical local enrollment and subsequent local telemetry without the stock
gateway or cloud service. The sensor continued reporting without an observed
stock acknowledgement during the test, but its routine acknowledgement path
and long-term behavior still require validation.

The two first-enrollment sequences had the same cadence within measurement
error:

| Transition | Sensor A | Sensor B |
|---|---:|---:|
| factory `01` to paired `01` | 2.983 s | 2.992 s |
| paired `01` to paired data `02` | 5.915 s | 5.890 s |
| paired data `02` to short `02` | 1.942 s | 1.942 s |
| short `02` to paired data `03` | 3.878 s | 3.898 s |

These intervals are useful for recognizing a complete enrollment sequence but
are not treated as hard deadlines; RF packet loss must not create a false
association.

A battery power cycle caused Sensor A to announce its factory identity; the
stock RainPoint gateway replied with a rejoin frame and restored its paired
identity without an app action. Deleting Sensor B from the app produced no RF
frame. Until its next power cycle it continued transmitting on the paired
identity; after reboot it returned to factory announcements.

In a controlled local-only test, Sensor B emitted factory messages `01`, `02`,
and `04` six seconds apart while the RTL-SDR receiver remained healthy. It did
not emit the paired identity and never flashed blue because no gateway reply
was transmitted. Physical pairing therefore requires a transceiver; listening
alone can discover the factory identity but cannot complete enrollment.

The receive decoder recognizes this strict factory/paired structure and can
create a generic HCS026 device from a trailer-valid paired telemetry report.
The enrollment monitor opens an explicit learning window, reports the factory
candidate, and persists only a matching factory-to-paired transition. The
current receiver deliberately transmits nothing. The recovered stock-gateway
frames are transmit candidates for the future ESP32/CC1101 prototype, not yet
an enabled control path.

### Sensor B dry-run pairing reply plan

The executable prototype contains one deliberately narrow reply profile for
factory identity `15a98024` / paired identity `95a98024`. It advances only
after the matching sensor trigger has been observed:

| Step | Sensor trigger | Reply frequency |
|---:|---|---:|
| 1 | Factory message `01` | 433.4715 MHz |
| 2 | Paired message `01` | 433.4715 MHz |
| 3 | Paired data message `02` | 433.4715 MHz |

The stock repeat enrollment completed with these three gateway replies. The
sensor still emitted its short message `02` and terminal message `03`, but the stock
gateway did not answer either one. The earlier five-reply sequence remains
preserved as historical evidence rather than the active bench profile.

Three successful gateway replies are therefore necessary but not sufficient.
The coordinator must remain armed after reply 3, tolerate the intervening short
message `02`, and require terminal sensor message `03` before reporting
completion. If `03` never arrives, the session expires as an incomplete
enrollment rather than producing a false success.

Each planned waveform has a 320-symbol alternating wake (16 ms) and a 304-bit
frame (15.2 ms), or 31.2 ms of RF. Comparing fixed-length IQ buffers and their
nanosecond write times places the stock gateway reply start about 65 ms after
the triggering sensor frame ends; the prototype therefore waits 60 ms before
its roughly 4 ms radio transition and transmission. The provisional reply
deadline is 250 ms after the matching trigger;
this is a conservative engineering bound, not a measured protocol constant.
Duplicates are ignored, while timeout, out-of-order triggers, or interruption
fail the plan closed. Firmware 0.3.0 implements this exact profile as an
explicitly armed physical bench path using ESP32 RMT timing and CC1101
asynchronous serial TX. It starts disarmed, uses approximately 0 dBm output,
accepts no network command, and contains no valve frame path. Physical SDR
validation and an isolated end-to-end Sensor B enrollment now confirm its
timing, polarity, and three-reply sequence. The path remains a deliberately
fixed research profile rather than a generalized user-facing pairing
implementation.

Firmware 0.4.0 exposes that fixed profile through mutually authenticated radio
node protocol v2. `rainpointd` supplies the validated 240-second clock lead,
45 kHz correction, 10 dBm setting, and session timeout in one bounded command.
Home Assistant requires an explicitly selected node, terminal sensor message
`03`, and a matching node command ID before registry finalization. The protocol
has no generic RF or valve-command operation; protocol-v1 nodes remain
receive-only.

## HCS026FRF soil-moisture reports

### Product identity confidence

The moisture layout and enrollment signature establish compatibility with the
HCS02x RF protocol family, but do not alone establish an exact retail model.
New local enrollments are therefore stored as `HCS02x-compatible soil sensor`
until variant-level evidence identifies a catalogued product. Product code
`0x48` is shared by the catalogued HCS021FRF, HCS024FRF, and HCS026FRF sensors,
so it selects their common soil-sensor capability family without asserting a
retail model. Model code `0x013d` identifies HCS026FRF if observed in a future
frame. The gateway persists both codes and their evidence source and rejects
contradictory identifiers. Trusted cloud-migration metadata may also supply an
exact model, but remains distinguishable from RF-derived identification.

Data-rich HCS026FRF frames carry a packed moisture value at one of two body
positions. The decoder looks for a marker whose low seven bits equal `0x44`.
The following byte contains half the percentage and the high bit of the next
byte is the odd-value flag:

```text
percent = value * 2 + bool(odd_flag & 0x80)
```

The marker begins at normalized frame offset 18 or 20, depending on the report
layout. Detection is restricted to confirmed HCS026 endpoint IDs to prevent a
marker-like sequence in a valve frame from creating a false sensor reading.

Confirmed examples:

| Sensor endpoint | Relevant bytes | Result |
|---|---|---:|
| `ce628024` | `... c4 1d 80 ...` | 59% |
| `d1e28024` | `... c4 27 80 ...` | 79% |
| `c4e50024` | `... 44 1d 00 ...` | 58% |
| `c4e50024` | `... c4 06 00 ...` | 12% |
| `9ce58024` | `... 44 20 00 ...` | 64% |
| `9bce0024` | `... c4 00 80 ...` | 1% |
| `95a98024` | `... c4 05 00 ...` | 10% |
| `95a98024` | `... c4 05 80 ...` | 11% |

### Routine gateway acknowledgement

Direct IQ captures contain short gateway-originated frames after ordinary
lower-channel sensor reports. They are distinct from the sensor report but use
the same 38-byte framing and a 320-symbol wake. Across the retained pairs:

- the route reverses from `b9840280 -> sensor` to
  `sensor -> 39840280`;
- message byte 13 gains `0x80` and byte 14 gains `0x40`;
- bytes 15--17 become `81 00 01`, with the rest of the body zero;
- the reply preserves the triggering report's `0xc713` or `0x4f03` trailer
  residual; and
- reply sync appeared 177--188 ms after report sync in same-file IQ captures.

For example, the transformation below reproduces the captured reply exactly:

```text
report: 79f4882f28 b9840280 ce628024 17 01 82 03 05 c4 1a 80 ... 7833
reply:  79f4882f28 ce628024 39840280 97 41 81 00 01 00 00 00 ... 5242
```

The report is sent on telemetry channel 0 near 433.140 MHz. Segmented IQ from
the same exchange places the reply near 433.886 MHz, consistent with the
sensor's enrollment selector 8 nominal center of 433.9115 MHz plus oscillator
error. The first local prototype therefore replies on the selector negotiated
during enrollment rather than the telemetry channel.

Test Sensors A and B, which were initially enrolled only to the custom local
radio node, produced no corresponding reversed frames and eventually stopped
routine reporting. Adding the exact transformed reply restored sustained
telemetry and manual reports for both identities, physically confirming its
acknowledgement/liveness role.

The local gateway now persists exactly one custom ACK owner for each endpoint.
An owner holds at most eight authorizations, restores all assignments after a
reconnect or OTA reboot, stays on telemetry channel 0 between reports, hops to
the negotiated selector only for its bounded reply, and returns to receive.
Two independent sensor recoveries and six installed/test assignments have
produced local ACK transmissions with zero driver failures. Multi-day cadence
and explicit owner-reassignment testing remain operational qualification, not
protocol-format uncertainty.

### Authorized paired-sensor recovery

An already-paired HCS026 can request recovery without returning to its factory
endpoint. The observed sequence uses its paired endpoint and messages
`01 -> 02 data -> 02 short -> 03`. Test Sensor A emitted the first of these
frames immediately before becoming dormant while the stock RainPoint gateway
was also active. Older firmware excluded all messages `01`--`03` from routine
acknowledgement and therefore could not answer this path.

Firmware `0.13.0-sensor.1` recognizes this sequence only for an endpoint
already authorized to the receiving node. It reproduces the three captured
paired-state gateway replies locally and treats message `03` as completion.
It does not open enrollment, infer ownership, or respond to an unknown sensor.
The gateway records the owner, phase, transmit outcome, and completion counts
for controlled coexistence testing with the stock gateway.

### Confirmed marker-relative battery flag

The two newly enrolled sensors first exposed a battery flag through a
controlled three-cell to two-cell to three-cell transition on Test Sensor A.
That test correlated the stock app, the LCD low-battery icon, and bit `0x04`
in the byte immediately preceding the `44`/`c4` moisture marker:

```text
full: ... 03 01 82 04 85 c4 00 80 ...  # 1%, bit 0x04 set
low:  ... 03 01 82 04 81 c4 00 80 ...  # 1%, bit 0x04 clear
```

The marker occurs at offset 18 in five sensors and offset 20 in Right Bed, so
the battery byte shifts with it. Across 5,068 retained trailer-valid reports
from all six local sensors, this marker-relative bit is consistent with their
normal/full state. The only two apparent clear-bit exceptions were already
rejected frames with invalid trailers. Bit set maps to normal/`100%` and bit
clear maps to low/`10%`, matching the categorical values exposed by the stock
integration. The normalized transition corpus is stored in
`research/fixtures/hcs026_pairing_battery.json`.

### Product-code/TLV report

One Front Yard Sensor 2 transmission used `d1e28048` in endpoint B rather than
its ordinary `d1e28024`. The `0x48` suffix equals the HomGar product code for
the HCS021/HCS024/HCS026 soil-sensor family. Its body carried:

```text
2c 03 04 0f 0a 88 4f
                  ^^ 79%
               ^^ one-byte HomGar TLV header for type 10 / STA_RH
```

The ordinary `d1e28024` companion acknowledgement arrived 180 milliseconds
later, and surrounding independently decoded reports held steady at 79%.
`rainpointd` therefore canonicalizes a known HCS026 `...48` identity back to
its established `...24` endpoint and decodes `88 VV` as direct percentage
`VV`. It does not apply that rule to an unknown endpoint.

A compact-status family was observed three times within 0.835--1.040 seconds
of a normal Right Bed 57% report:

```text
... 0a 88 39 e0 b1 ...
       |  |  |  +---- signed type-32 RSSI: -79 dBm
       |  |  +------- moisture: 57%
       |  +---------- one-byte type-10 header
       +------------- field code 10 / STA_RH
```

All three carried moisture 57% and hub RSSI -79 dBm, matching the independently
observed Right Bed state. Two forms used a slot-like `0x0b` byte before the
same compact `88 39 e0 b1` TLVs instead of field code `0x0a`. Their routing
fields varied and did not provide a stable Right Bed identity, so the decoder
retains these as unassigned status fields rather than updating a device. The
repeatable timing and values associate the family with Right Bed, but more
samples are required before defining a safe automatic routing rule.

The controlled 12% sample was produced by removing the Left Bed probe from the
ground. Its display, independently observed reference entity, local decoder,
gateway API, and Home Assistant local entity all reported 12%. This validates
the field across a much wider range than the earlier 58--79% samples.

Example Left Bed frame:

```text
79f4882f28b9840280c4e500240981820385c406000000000000000000000000000000004cea
```

### Sensor fields not yet decoded

- The former companion-heartbeat battery hypothesis is withdrawn. Same-file IQ
  identifies frames containing `... 41 81 00 01 00 ...` as gateway-originated
  acknowledgements, so byte 17 is not promoted as sensor battery state.
  Supported battery state comes from the trailer-valid marker-relative flag
  above.
- Hub-reported RSSI is receiver-measured rather than generated by the sensor.
  It can appear in separate compact status traffic, but that traffic's device
  association is not yet decoded.
- The meaning of the first body byte and remaining acknowledgement fields
  remains provisional.

The gateway currently exposes SDR signal metadata separately as
`rf_rssi_db`; it must not be presented as the stock hub's RSSI value.

## HTV145FRF valve protocol

### Request and response roles

| Endpoint order | Body byte 1 | Meaning |
|---|---:|---|
| `b42d008f` to `b9840280` | `0x10` | Open request |
| `b9840280` to `b42d008f` | `0x50` | Open response |
| `b42d008f` to `b9840280` | `0x90` | Close request |
| `b9840280` to `b42d008f` | `0xd0` | Close response |

The first body byte is a transaction sequence. Observed watering cycles
advanced through `0x9b`, `0x9c`, `0x9d`, `0x9e`, `0x9f`, then `0x80`, strongly
indicating a five-bit counter with a fixed high bit. Every request and response
in one cycle echoes the same sequence value.

### Command bodies

The stable request bodies are:

```text
open:  SS 10 82 80 81 00 DD DD 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
close: SS 90 81 80 81 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

`SS` is the transaction sequence. `DD DD` starts with the watering duration in
two-second units, little-endian, but bit 7 of the low byte is forced on:

```text
units = duration_seconds / 2
DD DD = little_endian_16(units)
DD[0] = DD[0] OR 0x80
```

The forced bit makes arbitrary second values ambiguous. Every independently
correlated command used whole minutes, which resolves the ambiguity: of
`little_endian(DD DD) * 2` and `(little_endian(DD DD) & ~0x80) * 2`, exactly
one is a positive multiple of 60. Initial local construction is therefore
restricted to whole-minute durations.

Confirmed duration examples:

| Encoded | Requested duration |
|---|---:|
| `9e 00` | 60 seconds |
| `f8 00` | 240 seconds |
| `fe 01` | 1,020 seconds |

The 240- and 1,020-second values were independently confirmed in the Home
Assistant recorder at the corresponding RF timestamps. Treating `f8 00` as a
plain 16-bit value would incorrectly produce 496 seconds.

### Representative frames

```text
open request
79f4882f28b42d008fb98402809710828081009e000000000000000000000000000000003824

open response
79f4882f28b9840280b42d008f9750868010cf92800000409e00569e000000000000000044ce

close request
79f4882f28b42d008fb984028097908180810000000000000000000000000000000000006fcf

close response
79f4882f28b9840280b42d008f97d08680104f90800000408000569e00000000000000001f46
```

Exact requests were observed retransmitted without changes, including the
trailer. This proves there is no per-burst nonce. It does not yet prove that a
request from an older transaction can be replayed later.

Across 14 captured commands (seven opens and seven closes), 12 had a retained
reverse-route response within three seconds. Normal response latency was
0.372--0.380 seconds; two responses arrived at 1.062 and 1.083 seconds. This
supports a first acknowledgement timeout of at least 1.5 seconds and argues
against immediately retrying a non-idempotent open command. The two missing
responses were from the scheduled cycle and are consistent with missed RF
reception rather than proven valve non-response.

### Last-session water usage

Valve response frames use `0x4f` or `0xcf` as a marker at normalized frame
offset 20. The next two bytes encode usage in tenths of a liter:

```text
half_tenths = ((second & 0x7f) << 8) | (first & 0x7f)
tenths_liters = half_tenths * 2 + bool(second & 0x80)
liters = tenths_liters / 10
```

Confirmed examples:

| Packed bytes | Result |
|---|---:|
| `85 00` | 1.0 L |
| `84 80` | 0.9 L |
| `8e 00` | 2.8 L |
| `d3 00` | 16.6 L |
| `b3 00` | 10.2 L |
| `ec 03` | 175.2 L |

## Trailer status

For ordinary 38-byte frames, calculate CRC-CCITT with polynomial `0x1021` and
initial value zero over normalized bytes 0--35. XOR that result with the
big-endian trailer. In the retained corpus, 687 of 705 usable unique frames
(97.4%) produce one of exactly two residues:

```text
crc_ccitt(frame[0:36], init=0) XOR trailer in { 0xc713, 0x4f03 }
```

The remaining 18 frames visibly contain clipping, demodulation corruption, or
placeholder trailers. Re-demodulation of retained IQ reproduced both residues
with both short and long preambles, so preamble length is not the selector.
Both residues also occur in hub-to-valve command traffic. A scheduled 1,020
second open and its close used `0x4f03`; controlled short cycles used each
residue across different transaction sequence values.

An expanded passive analysis on 2026-08-07 found 1,456 unique clean frames:
732 used `0xc713` and 724 used `0x4f03`. Every established route contained
both. The best single transmitted-bit predictor was only 51.4% accurate, and
the best two-bit XOR predictor was 53.3%; neither is materially better than
chance for this balanced corpus. Collapsing exact retransmission bursts also
rejected a simple alternating selector. No identical 36-byte payload was
observed with conflicting trailers.

The selector is therefore not a simple exposed frame bit, pairwise parity,
route, message counter, or global toggle. It may depend on omitted transmitter
state or a nonlinear rule. Passive evidence can validate either residue but
cannot yet choose one when constructing a new payload.

Cloud/API correlation narrows this further. The legacy valve-control request
contains only hub/device identity, subdevice address, port, open/close mode,
duration, an empty parameter, and the hub ID. It contains no nonce, timestamp,
RF sequence, checksum mode, or trailer selector. The HTV145FRF product catalog
likewise describes `CTL_WATER` as a two-byte control on endpoint 7 but has no
CRC selector. Therefore the sequence and trailer are generated inside the
hub's RF stack. The two-residue choice is most plausibly hidden transmitter
state, an omitted lower-layer input, or two forms accepted by the receiver;
the cloud API does not provide a missing bit that can simply be copied.

This is sufficient to validate ordinary received frames and reject most
demodulation artifacts. It is not yet sufficient to generate arbitrary
commands because the rule selecting the two residues remains unknown. Compact
product-code/status frames are a separate family and do not satisfy this
ordinary-frame rule, so they must be retained rather than rejected globally.

## Receive and decode

Live receive:

```sh
rtl_433 -f 433700000 -s 2000000 -R 0 \
  -X 'n=RainPoint,m=FSK_PCM,s=50,l=50,r=50000,bits>=620,match={40}79f4882f28' \
  -M time:iso:usec -M level -M bits
```

Normalize saved CU8 captures:

```sh
python3 tools/decode_rainpoint_iq.py \
  --sample-rate 2000000 --frequency 433700000 capture.cu8
```

Measure FSK tones and occupied bandwidth from saved CU8 captures:

```sh
python3 tools/characterize_rainpoint_iq.py \
  --sample-rate 2000000 --frequency 433700000 capture.cu8
```

`rainpointd_addon/rainpointd/rf.py` is the executable specification for frame
normalization and confirmed field decoding. Regression examples live in
`test_rainpoint_rf.py`.

## Remaining protocol work

1. Determine by bounded active acceptance testing whether either ordinary
   trailer residue is accepted for a newly constructed payload, then
   characterize the compact-frame trailer family.
2. Validate the measured channel, rate, deviation, bandwidth, and sync profile
   on receive-only CC1101 hardware, including both RF channels.
3. Test whether a captured request is accepted outside its original sequence
   window.
4. Determine whether P1–P6 soil profile selection is transmitted, local-only,
   or cloud metadata.
5. Capture valve enrollment, association, and forgetting traffic.
6. Confirm valve retry timing, acknowledgement rules, and safe close behavior before
   enabling Home Assistant control.
7. Classify the four-zone test controller independently: determine whether it
   shares the HTV145 frame family, how it identifies ports, and whether state,
   counters, and close commands are per-zone or chassis-wide.

## Safety boundary

The current implementation transmits only validated, identity-bounded soil
sensor pairing/rejoin replies and acknowledgements. Valve transmission remains
absent. It must enforce a local maximum duration, start an independent watchdog
before opening, retry an idempotent close until idle is observed, and fail
closed after gateway, Home Assistant, network, or power loss.

## Evidence and references

The concise capture history is in
[`research/RF_CAPTURE_NOTES.md`](research/RF_CAPTURE_NOTES.md). Cloud-side
observations used only as a comparison oracle are isolated in
[`research/cloud/README.md`](research/cloud/README.md).

- Exact valve FCC filing: <https://fccid.io/2AWDBHTV145FRF>
- Community HCS021FRF FSK notes:
  <https://github.com/user-attachments/files/26152016/rainpoint_decoding.txt>
- `rtl_433`: <https://github.com/merbanan/rtl_433>
- TI CC1101: <https://www.ti.com/product/CC1101>

The [HCS026FRF manual](https://images.thdstatic.com/catalog/pdfImages/c4/c475eb70-03af-4afe-80ee-59718a4c47b6.pdf)
distinguishes measurement from reporting: automatic moisture detection occurs
every 3 minutes, while the app reading refreshes every 8 minutes, after a
manual detection, or when an automatic reading changes by more than 5%.
Therefore an unchanged sensor should still produce approximately eight-minute
gateway-visible updates; stable moisture is not expected to suppress all RF
traffic.
