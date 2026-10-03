# HTV213FRF stock-hub capture findings

September 28, 2026. Offline decoding of two stock-owned, dry two-zone valve
automatic-stop trials, a subsequent early-stop trial, and two post-idle controls.
An additional hub-only restart trial retains the powered valve's association.
The subsequent valve-only battery cycle exercises known-device rejoin without
putting the stock hub into pairing mode.
The user identifies
the model as **HTV213FRF** and the valve as used.
This is stock-protocol evidence, not qualification of local two-zone support.
Execution status belongs in [the roadmap](../PROJECT_ROADMAP.md); the procedure
is [the two-zone capture plan](TWO_ZONE_STOCK_CAPTURE_PLAN.md).

## Evidence and limits

Private, Git-ignored sources beneath `captures/two-zone-stock-20260928/`:

| Capture directory | Nominal UTC start | IQ duration | Experiment |
| --- | --- | --- | --- |
| `20260928-152849` | 19:28:49 | 900 s / 3.6 GB | Hub startup, unsuccessful battery-start attempt, successful long press, Zone 1 automatic stop |
| `20260928-154645` | 19:46:45 | 600 s / 2.4 GB | Zone 2 through HA cloud integration, automatic stop |
| `20260928-161333` | 20:13:33 | 300 s / 1.2 GB | Zone 1 120-second request, explicitly stopped after about 35 seconds |
| `20260928-165339` | 20:53:39 | 300 s / 1.2 GB | Zone 1 60-second request after more than 30 minutes idle, automatic stop |
| `20260928-200502` | September 29, 00:05:02 | 300 s / 1.2 GB | Zone 2 60-second request after more than three hours idle, automatic stop |
| `20260928-205336` | September 29, 00:53:36 | 300 s / 1.2 GB | Stock hub RST restart, valve left powered; first post-boot Zone 1 open and automatic stop |
| `20260928-210235` | September 29, 01:02:35 | 600 s / 2.4 GB | Valve-only battery cycle, stock hub left on and not pairing; Zone 2 control after retained rejoin |

All captures use CU8, 2 Msps and 0.9 dB tuner gain. The first six use a
433.7 MHz center; the battery-cycle capture moves to **433.9 MHz** to include
the previously aliased factory sweep leg. All times
below identify the **normalized sync start in the capture**, not command-send
timestamps or precise physical movement. Session wall clocks bracket recording;
do not add their second-resolution start to RF offsets for subsecond cloud/RF
latency claims. The gap between captures is unobserved RF.

The private analysis under `analysis-htv213/` scans overlapping eight-second
windows, all 100 clock phases, and 36 decision centers from 433.08 to 434.48 MHz.
It validates the established 38-byte legacy integrity residues and native `51`
header/data length. Threshold/clock duplicates are collapsed by identical frame
and sync time within 4 ms. It recovered **70 distinct frames** in the first
capture, **22** in the second, and **28** in the third. The fourth capture uses
the same bounded method at three already-qualified decision centers
(433.14, 434.24, 434.35 MHz), recovering **24** frames across the complete
300 seconds. The fifth capture uses those same three centers and recovers
**26 distinct frames** after removing two overlapping-window duplicates.
The sixth capture uses the same three centers, recovering **24 distinct
frames** after removing two overlapping-window duplicates.
The seventh capture uses the corrected 433.9 MHz center and five decision
centers listed in its battery-cycle section, recovering **48 distinct frames**
after removing two overlapping-window duplicates across all 600 seconds.
No whole-capture IQ array is allocated.
Raw routes and full packets remain private. The legacy integrity window is not
a newly validated complete physical CRC tail; see [common framing](../protocol_documentation/common.md).

These are successful decoded observations, not a completeness proof:

- Representative hub wake windows have **29–33% I/Q samples at the ADC rails**
  (`<=1` or `>=254`). Valve examples have 0%. Clipping prevents reliable stock
  waveform/amplitude comparisons and may hide other frames, even where a
  particular frame validates and decodes consistently.
- The valve's second factory sweep leg straddles the capture's upper Nyquist
  edge. One tone aliases; the capture is not complete, clean RF coverage of
  every factory channel. Future factory trials should move the capture center
  to cover both tones with margin, and reduce hub signal at the SDR antenna.
- Generic `rtl_433` decoding missed most lower-carrier traffic and all second
  capture events. Its lack of output was a decoder limitation, not absent RF.
- No native `59`/`d9` was recovered. That does not prove this model never uses
  it or that a missing exchange is unnecessary for every association branch.

## Carriers and framing

Bounded FFT measurements of alternating wake windows, uncorrected for SDR
oscillator error:

| Observed leg | Approximate FSK center | Evidence |
| --- | --- | --- |
| Factory phases 1, 4, 7 and addressed valve reports | 433.1434 MHz | Tones 433.1034 / 433.1834 MHz |
| Factory phases 2, 5, 8 | Candidate 434.6834 MHz | 434.6434 MHz tone plus 432.7234 MHz aliased tone; the latter is consistent with 434.7234 MHz outside Nyquist |
| Factory phases 3, 6, 9 | 433.3634 MHz | Tones 433.3234 / 433.4034 MHz |
| Stock initial assignment `81` | 434.3516 MHz | Tones 434.3116 / 434.3916 MHz |
| Accepted-association hub replies/controls | 434.2416 MHz | Tones 434.2016 / 434.2816 MHz |

The aliased carrier is an inference from sampled frequencies and the 2 MHz
wrap, not an independently measured out-of-band RF frequency. Decision-center
thresholds that decode a frame are **not** precise carrier measurements.
Native `20` and `21` hub transmissions have a dominant **2,400-symbol wake**;
their `a0`/`a1` device replies have a dominant **320-symbol wake**. Symbol rate,
native envelopes and approximately 80 kHz tone separation match the existing
device family.

## Battery-start attempt versus successful long press

The first attempt is not radio-silent. At 61.471–77.395 s it emits native `01`
at phases **1 through 9**, about two seconds apart. Stock `81` replies are
observed for phases **1, 4 and 7**, but the valve continues announcing rather
than producing an addressed `02` report. These observations explain why a hub
reply alone cannot establish successful association.

The second attempt begins at 96.868 s with the same eight-byte announcement
body, `0c ff 20 05 01 04 3e 05`, and phases **1, 2, 3, 4**. Stock `81` replies
occur at phases 1 and 4. After the phase-4 assignment at 103.006 s, the valve
advances to addressed reports and per-port configuration. Its accepted selector
is **11**, appearing as `0b` in subsequent device requests. Initial unsuccessful
assignment bodies proposed different selectors; do not freeze one assignment
from another sweep into a presumed universal reply.

The user reports that the first sequence followed battery insertion and the
successful sequence followed a long press. **A previous association remains
unproven**: being used, failing at boot, or emitting the same announcement body
does not establish what the valve retained internally. No reset procedure was
performed or inferred by this analysis.

### Recovered successful enrollment

| First-capture sync time (s) | Sender / native family | Phase | Qualified fields |
| --- | --- | --- | --- |
| 104.860 / 104.965 | Valve `02` / hub `82` | 5 | Port 1 state; ACK `00 01` |
| 106.898 / 106.975 | Valve `02` / hub `82` | 6 | Port 2 state; ACK `00 01` |
| 108.055 / 108.350 | Hub `20` / valve `a0` | 2 | Configuration revision 2, kind 0; result `00` |
| 110.857 / 110.926 | Valve `05` / hub `85` | 7 | Selector 11, port 1; fourteen-byte settings |
| 112.866 / 112.936 | Valve `05` / hub `85` | 8 | Selector 11, port 2; same settings |
| 114.877 / 114.945 | Valve `06` / hub `86` | 9 | Selector 11, port 1, page 0; response `00` |
| 116.868 / 116.935 | Valve `06` / hub `86` | 10 | Selector 11, port 2, page 0; response `00` |

Both `85` data bodies are `00 58 02 0a 00 1e 00 00 00 00 00 00 00 00 00`.
Excluding the result byte, the recovered stock configuration structure gives
raw work time **600**, mist-open **10**, interval **30**, and remaining fields
zero. The captured one-/two-minute run settings do not rewrite these initial
default bytes; operation duration is independently explicit in `21`.
See the [fourteen-byte field reference](STOCK_HUB_CONFIGURATION_LIFECYCLE.md#fourteen-byte-valve-configuration-layout)
for which units and labels are qualified.

This is a two-port variant of the shared request families: **two state reports,
two settings reads, two plan reads**, not a requirement to replay the four-zone
valve's eighteen historical transcript rows. Direct replies echo the device
phase; hub-originated `20` uses the hub's independent phase.

## Zone control and automatic stops

### Zone 1: one minute, stock app

| First-capture time (s) | Native observation |
| --- | --- |
| 331.198445 | Hub `21`, phase **3**, data `01 02 01 3c 00`: port 1, open, unsigned LE **60 seconds** |
| 331.511201 | Valve `a1`, phase **3**, result 0, open-state marker `21`, remaining 61, requested total 60 |
| 337.900 | Valve `02`, phase 11, port 1 open, remaining 55, total 60; hub `82` echoes phase 11 |
| 372.890 | Valve `02`, phase 12, port 1 open, remaining 20, total 60; matched `82` |
| 393.860 | Valve `02`, phase 13, port 1 idle, remaining/total zero; matched `82` |
| 403.893739 | Valve `04`, phase 14, port 1 session summary, final duration **60**; matched `84` |

No native close command was recovered. Operator reported automatic stop. First
observed idle is about 62.7 s after open-command sync, which includes reporting
delay and must not replace the 60-second encoded/summary duration.

### Zone 2: two minutes, HA cloud integration

| Second-capture time (s) | Native observation |
| --- | --- |
| 370.572979 | Hub `21`, phase **4**, data `02 02 01 78 00`: port 2, open, unsigned LE **120 seconds** |
| 370.886945 | Valve `a1`, phase **4**, result 0, open marker `21`, remaining 121, total 120 |
| 376.880 | Valve `02`, phase 30, port 2 open, remaining 115, total 120; matched `82` |
| 415.930 | Valve `02`, phase 31, port 2 open, remaining 76; matched `82` |
| 435.860 | Valve `02`, phase 32, **port 1 idle** while port 2 remains in its requested run; matched `82` |
| 475.840 | Valve `02`, phase 33, port 2 open, remaining 16; matched `82` |
| 491.920 | Valve `02`, phase 34, port 2 idle; matched `82` |
| 526.868143 | Valve `04`, phase 36, port 2 summary, final duration **120**; matched `84` |

The HA trial journal records one open service call, no retries/manual close,
and a fresh final idle MQTT update. The RF request and valve-originated response,
countdowns and final summary independently support the cloud observations.
The first RF idle report follows command sync by about **121.35 seconds**.

For these shapes, `02` data bytes **10..11** are remaining seconds and **13..14**
are requested total seconds. In `a1`, result-inclusive data bytes **8..9** and
**11..12** carry those values. The initial remaining value is requested+1 in
both runs; do not subtract an arbitrary constant from subsequent fields or
reinterpret the command as half-duration. Observed command duration is ordinary
LE seconds, matching HTV145/HTV405. Actual hydraulic flow was not measured:
this valve is dry. Dry zero usage cannot establish presence/absence or units
of a water-volume field.

### Zone 1: explicit early stop

The third capture records a stock-cloud 120-second open and one subsequent
close, not a guessed-counter probe:

| Third-capture time (s) | Native observation |
| --- | --- |
| 55.267264 | Hub `21`, phase **5**, data `01 02 01 78 00`: port 1, 120 seconds |
| 55.580014 | Valve `a1`, phase **5**, result 0, mode `21`, remaining 121, total 120 |
| 88.100234 | Valve `02`, phase 53, port 1 open, remaining 89, total 120; matched `82` |
| 90.700322 | Hub `21`, phase **6**, data `01 02 00`: explicit port-1 close, **35.433058 s** after open sync |
| 91.009981 | Valve `a1`, phase **6**, result 0, mode **`20`**, remaining 0, retained requested total 120 |
| 97.022521 | Valve `02`, phase 54, port 1 idle with remaining/total zero; matched `82` |
| 99.031430 | Valve `04`, phase 55, port 1 summary, final elapsed **34 seconds**; matched `84` |

The close-result mode `20` is **not byte-for-byte ordinary idle mode `00`**.
The request-correlated positive result/remaining zero is followed by an
independent idle report and elapsed summary. A future model decoder must not
require the close result to equal the later periodic-idle body. Conversely,
observing an outbound close alone cannot establish that the valve stopped.
The elapsed summary need not equal rounded RF command-to-command spacing.

The [redacted fixture](fixtures/htv213_stock_pairing_controls_20260928.json)
preserves 44 selected frames across enrollment and all three control trials.
It replaces routes with synthetic aliases and zeroes device-clock fields,
recomputing legacy checksums while retaining observed command/phase/port/state
and duration fields. Six tests in
[`test_htv213_stock_capture.py`](../tests/test_htv213_stock_capture.py) qualify
full-phase correlation, two-port structure, automatic-stop durations, early
close state differences, and redaction. This is an offline regression fixture,
not a local pairing/control recipe or a reconstructed full RF waveform.

### Zone 1 after more than 30 minutes idle

The main controller's private quiet-period journal records exactly one
60-second stock-cloud open at **20:53:53.853331 UTC**, after the preceding
early-stop trial's confirmed idle at **20:15:05.476 UTC**: approximately
**38 minutes 48 seconds** without another test control. There was no requested
hub/valve restart or re-pairing. The gap was not continuously recorded in RF;
ordinary reports and other non-control traffic may have continued.

| Fourth-capture time (s) | Native observation |
| --- | --- |
| 13.929443 | Hub `21`, phase **7**, data `01 02 01 3c 00`: port 1, 60 seconds |
| 14.237636 | Valve `a1`, phase **7**, result 0, mode `21`, remaining 61, total 60 |
| 20.328875 | Valve `02`, phase 12, port 1 open, remaining 55; matched `82` |
| 41.368444 | Valve `02`, phase 13, port 1 open, remaining 34; matched `82` |
| 61.291390 | Valve `02`, phase 14, port 2 idle; matched `82` |
| 76.339387 | Valve `02`, phase 15, port 1 idle; matched `82` |
| 82.319400 | Valve `04`, phase 16, port 1 summary, final duration **60 seconds**; matched `84` |

The observed hub control phase therefore progresses **6 → 7** across this
idle interval, with a positive response and automatic-stop evidence. This
qualifies one stock-owned HTV213 quiet-period trial, not overnight durability
or the existing models' acceptance rules. Valve report phases 12–16 after an
unrecorded gap do not identify a reset versus wrap; do not reconstruct missing
reports by guessing. Across the full fourth capture, decoding recovers exactly
one `21` open, its `a1`, ten `02`/`82` report pairs, and one `04`/`84` summary
pair. No other control or close is decoded. Idle reports continue through
281.149 seconds, with matched ACKs. The completed raw file is exactly
**1,200,000,000 bytes** and its independently recomputed SHA-256 matches the
private capture manifest. Clipping and selective demodulation still prevent
claiming absence of every possible RF packet.

### Zone 2 after more than three hours idle

The private `quiet3h-trial.json` journal records one 60-second Zone 2 open at
**September 29, 00:05:21.150104 UTC**. The previous quiet-period trial reached
confirmed idle at **September 28, 20:54:58.071542 UTC**: approximately
**3 hours 10 minutes 23 seconds** between that confirmation and the new open
request. Both outlets reported closed before the command. No hub/valve restart,
re-pairing, guessed counter, local RF probe, retry open or manual close was
requested for this trial. First HA-observed open is not substituted for the
actual service-call timestamp.

| Fifth-capture time (s) | Native observation |
| --- | --- |
| 20.105283 | Hub `21`, phase **8**, data `02 02 01 3c 00`: port 2, 60 seconds |
| 20.418206 | Valve `a1`, phase **8**, result 0, mode `21`, remaining 61, total 60 |
| 26.910084 | Valve `02`, phase 57, port 2 open, remaining 55; matched `82` |
| 58.940145 | Valve `02`, phase 58, port 2 open, remaining 23; matched `82` |
| 78.969606 | Valve `02`, phase 59, port 1 idle; matched `82` |
| 81.911332 | Valve `02`, phase 60, port 2 idle; matched `82` |
| 119.920629 | Valve `04`, phase 62, port 2 summary, final duration **60 seconds**; matched `84` |
| 158.970994 / 179.304944 | Valve idle `02` reports use phases **63**, then **1**, each acknowledged at the same full phase |

The first port-2 idle report follows the open-command sync by **61.806049 s**;
that includes reporting latency, not evidence that the LE 60-second command
means a different duration. The journal confirms both outlets idle at
00:06:26.850497 UTC. Across the complete five-minute capture, the decoder
recovers one `21`/`a1` pair, eleven `02`/`82` report pairs, and one `04`/`84`
summary pair. No other control or close is decoded. Idle reports continue
through **278.646353 s** with matched ACKs. Capture completed normally at
**1,200,000,000 bytes**, owner-only permissions; the main controller independently
verified SHA-256 against the private manifest.

The observed stock-hub control sequence advances **7 → 8** across the
three-hour-plus idle gap and is immediately acknowledged. This shows successful
control without an observed resynchronization exchange for this **stock-owned
HTV213 under this trial's conditions**. It does not establish whether the
valve's internal counter state persisted, reset, or accepts a wider range of
fresh phases; nor does it prove overnight behavior, the local implementation,
or other models.
Continuous RF was not retained throughout the quiet interval, so its internal
traffic/sequence consumption cannot be reconstructed completely.

The recorded **device report** sequence crosses **63 → 1**, with no phase-0
report decoded in between. Treat this as the observed device sequence, not a
new definition of the stock hub's separate generator and not proof that every
possible phase-0 packet was absent. The source-traced hub generator and device
report progression must remain separate even when both fit six wire bits.

### Hub-only RST restart with valve left powered

The private `hub-restart-trial.json` journal records a user-approved
**RTS-to-RST pulse on the stock hub**, with BOOT ungrounded, at
**September 29, 00:53:58.249497 UTC**. This is a hub MCU reset, not a valve
battery cycle or a hub power-disconnect test. The valve stayed powered, dry
and paired. Normal boot was monitored through private UART output; the reset
helper finished at 00:54:23.661133 UTC. The main controller issued exactly one
60-second Zone 1 open at **00:54:25.789620 UTC**, without repeated pairing,
counter guesses, retries or a manual close.

| Sixth-capture time (s) | Native observation |
| --- | --- |
| 33.530193 | Hub `20`, phase **2**, data **`02 01`**: configuration revision 2, update kind 1 |
| 33.820143 | Valve `a0`, phase **2**, result `00` |
| 35.531074 / 37.550381 | Valve idle `02` reports for ports 1 and 2, phases **20 / 21**, selector 11; matching `82` replies |
| 48.987340 | Hub `21`, phase **3**, data `01 02 01 3c 00`: port 1, 60 seconds |
| 49.295452 | Valve `a1`, phase **3**, result 0, mode `21`, remaining 61, total 60 |
| 55.589650 | Valve `02`, phase 22, port 1 open, remaining 55; matched `82` |
| 84.571378 | Valve `02`, phase 23, port 1 open, remaining 26; matched `82` |
| 111.619478 | Valve `02`, phase 24, port 1 idle; matched `82` |
| 115.551209 | Valve `04`, phase 25, port 1 summary, final duration **60 seconds**; matched `84` |

The actual controller and valve routes match the preceding pre-reset control
capture, and selector 11 is retained in the addressed reports. No native
`01`/`81` enrollment is decoded. The post-reset control uses phase **3**, not
the previous accepted control phase 8 plus one, and receives a positive reply,
countdown, idle and final-duration evidence. The cloud journal separately
confirms both outlets idle at **00:55:30.884979 UTC**. The first RF idle report
follows open-command sync by **62.632138 s**, including reporting delay.

This is a concrete captured startup exchange to compare with our firmware:
**`20` kind 1 → `a0` → retained-device reports → accepted lower-phase control**.
It fits the source-traced startup notifier `4204BBC0(2)` and its shared master
sequence generator, documented in
[post-boot behavior](STOCK_HUB_POSTBOOT_TRACE.md) and
[configuration lifecycle](STOCK_HUB_CONFIGURATION_LIFECYCLE.md).
It does **not** prove that kind 1 itself resets or synchronizes the valve's
accepted control phase. The valve may apply another freshness rule; ordinary
state traffic, time-bearing acknowledgements and unobserved traffic remain
possible contributors. Proving the notifier's causal role needs a separately
designed trial, not an automatic live probe or production implementation.

Across all 300 seconds there is one `20`/`a0` pair, one `21`/`a1` pair, nine
`02`/`82` report pairs and one `04`/`84` summary pair. Idle reporting continues
through **264.760137 s**, with matched ACKs. No additional control is decoded.
Recording completed normally at **1,200,000,000 bytes**, owner-only permissions;
the main controller independently verified its SHA-256 manifest. Qualified
three-center decoding and previously measured clipping do not establish
complete reception on every possible channel. Native phase 1 consumption is
not recovered here and must not be invented from the first observed phase 2.
This qualifies one stock hub RST restart, not valve battery rejoin, local-node
restart handling, overnight behavior or all hub firmware versions.

### Valve-only battery cycle with the hub outside pairing mode

The user confirms batteries reinserted in a message observed at approximately
**September 29, 01:03:56 UTC**. Actual reinsertion precedes that confirmation;
do not use the message timestamp as the RF boot origin or infer an exact
battery-out duration. The stock hub remained powered and **not in pairing
mode**. No valve pairing button was pressed. The previously verified
controller/valve association remains the comparison baseline.

The seventh capture explicitly uses **433.9 MHz center**, with decision
centers 433.14, 433.36, 434.24, 434.35 and 434.68 MHz. Bounded FFT now directly
resolves factory phase-2 tones **434.643835 / 434.723853 MHz**, center about
**434.683844 MHz**, with 0% sampled ADC rails in the measured wake window.
That corroborates the earlier alias interpretation without relying on an
out-of-band inference. The example retained hub assignment is still clipped
(about 19.4% rail samples); wider carrier coverage does not remove that limit.

| Seventh-capture time (s) | Native observation |
| --- | --- |
| 5.610830 / 44.991692 | Pre-cycle ordinary idle `02` reports, phases 36 / 37, with matching `82` |
| 63.480041, 65.519385, 67.523841, 69.522252 | Boot `01` announcements restart at phases **1, 2, 3, 4**, on lower / upper / middle / lower sweep legs |
| 63.553573 / 69.603599 | Hub `81` replies echo phases **1 / 4**, using the retained reply carrier near 434.24 MHz |
| 70.848337 / 72.867741 | Valve addressed `02` reports for ports 1 / 2, phases **5 / 6**, selector 11; both `82` replies carry `00 02` |
| 75.884068 / 77.893774 | `05` settings reads for ports 1 / 2, phases **7 / 8**; matched `85` returns the previous fourteen-byte settings |
| 79.904506 / 81.894889 | `06` plan page-0 reads for ports 1 / 2, phases **9 / 10**; matched `86`, data `00` |

This is **retained-association rejoin through a factory-family announcement**,
followed by addressed reports and configuration reads; it is neither silence
nor a single status-only recovery. The accepted selector stays 11 and the
configuration revision remains **2**. In contrast, first enrollment advertised
revision 1 before the captured kind-0 notification of revision 2.

The boot announcement body is `0b ff 20 05 01 04 3e 03`, compared with
`0c ff 20 05 01 04 3e 05` in the initial long-press attempt. Rejoin assignment
bodies begin `00 02 0b` and end `01 02`, unlike the initial new-assignment
prefix `0a 02` and ending `01 01`; intervening clock/identity fields remain
private. These are qualified byte differences, not unproven labels for a
new model number, software update, authorization token or reset command.

The main controller then issued exactly one 60-second Zone 2 command at
**01:06:10.198228 UTC**, after RF rejoin was confirmed:

| Seventh-capture time (s) | Native observation |
| --- | --- |
| 214.689870 | Hub `21`, phase **4**, data `02 02 01 3c 00`: port 2, 60 seconds |
| 215.003716 | Valve `a1`, phase **4**, result 0, mode `21`, remaining 61, total 60 |
| 220.890307 / 246.111040 | Valve `02` port 2 open, phases **11 / 12**, remaining 55 / 30; matched `82` |
| 275.910928 | Valve `02`, phase **13**, port 2 idle; matched `82` |
| 316.891101 | Valve `04`, phase **15**, port 2 summary, final duration **60 seconds**; matched `84` |

The hub control sequence continues **3 → 4 across the valve battery cycle**,
while the valve's report/enrollment sequence restarts from 1. The first RF
idle report follows the open sync by **61.221058 s**; cloud independently
reports both zones idle at 01:07:15.365377 UTC. No `20`/`a0` notification or
manual close is decoded anywhere in the complete 600-second capture. Thus this retained rejoin
does not require replaying the observed new-enrollment kind-0 notification
before the accepted control in this trial. It does not establish the exact
valve-side counter acceptance mechanism, universal battery-rejoin reliability,
other models or local gateway support.

The final recording contains four native `01` announcements and two `81`
replies, fifteen `02`/`82` report pairs (including two pre-cycle pairs), two
`05`/`85` settings pairs, two `06`/`86` plan pairs, one `21`/`a1` control pair
and one `04`/`84` session-summary pair: **48 distinct validated frames**.
Idle reports continue through **585.144479 s**, with ACKs, and the same
controller/valve routes are retained. The recording completed normally at
**2,400,000,000 bytes**, owner-only permissions; the main controller independently
verified SHA-256 against its manifest. No `59`/`d9`, additional control or
explicit close is decoded. Wider factory coverage resolves the prior aliasing
issue, but clipping and finite decoder sensitivity still limit absence claims.

## Counter ledger: what this proves

| Traffic | Observed sequence |
| --- | --- |
| Valve successful enrollment | 1–4 announcements, then 5–10 addressed/configuration requests |
| Hub configuration notification | **2**, echoed by valve `a0` |
| Hub Zone 1 open | **3**, echoed by valve `a1` |
| Valve reporting/summary stream in first recording | **11–28**, echoed by `82`/`84` |
| Valve report early in second recording | **29**, echoed by `82` |
| Hub Zone 2 open | **4**, echoed by valve `a1` |
| Later valve reporting/summary stream | **30–38**, echoed by `82`/`84` |
| Hub early-stop trial open / close | **5 → 6**, echoed by valve `a1` |
| Valve early-stop trial reports / summary | **52–55**, echoed by `82`/`84` |
| Hub post-idle Zone 1 open | **7**, echoed by valve `a1`; later `02` idle and `04` final duration 60 |
| Hub three-hour-plus post-idle Zone 2 open | **8**, echoed by valve `a1`; later `02` idle and `04` final duration 60 |
| Device reports in that same fifth capture | **57–63 → 1–5**, echoed by `82`/`84`; no phase 0 decoded |
| Hub-only restart notification / first open | **2 → 3**, lower than pre-reset control 8; matching `a0` / `a1` and automatic-stop evidence |
| Device reports in that sixth capture | **20–29**, echoed by `82`/`84`, without decoded enrollment |
| Valve-only battery cycle | Device sequence restarts **1–4 → 5–10** through retained rejoin; subsequent hub open advances **3 → 4** and is accepted |

The hub's two opens occur about **19 minutes apart** according to nominal
capture start times, with many device-originated reports and matching hub ACKs
between them. Hub controls progress **2 → 3 → 4** across configuration and both
opens; the report stream has its own advancing phases. This is direct support
for keeping response echoing distinct from the shared master-request generator:
ordinary report ACKs must not reseed our next control counter. The third
recording extends hub control phases to **5 → 6** while contemporaneous device
reports use **52–55**; the gap before it remains unobserved RF.

All observed direct pairs match their full six-bit phase, including device
phases 32–38. No decoded control retry is present in either run. The gap between
recordings and clipped/aliased coverage mean this is not proof of every hub
generator call, no hidden traffic, overnight durability, a universal
device-side reset mechanism, or a valve's complete acceptance rule. The two bounded idle trials
above are qualified individually; longer and overnight outcomes are not
assumed from them.

## Scope for implementation

These captures support a **separate HTV213FRF model profile** using shared
native envelope, per-port request, LE duration, result and state primitives.
They do not authorize copying stock identities, selector 11, captured phase
numbers, or complete reply bodies into a local transmit path. Preserve the
known-working HTV145/HTV405 enrollment prefixes. Local pairing, stop behavior,
battery categorization, volume semantics and restart recovery require their own
qualified evidence before claiming support.

### Implementation implications

The immediate gap is **model-specific retained rejoin**, not another generic
pairing retry. The stock HTV213 preserves its association, answers `01` with
`81`, then services `02`, `05` and `06` for both ports. Implementing this locally
would require persisted association/channel/configuration state and a separate
retained-rejoin path; it should not replay a fixed fresh-enrollment transcript.
This observation is HTV213 evidence, not proof that HTV405 follows identical
steps. The current HTV405 cold-boot matcher feeds its existing transcript;
the proven HCS026 one-reply recovery is a different implementation.
Sources: [`rainpoint_valve_pairing.h`](../firmware/rainpoint_bridge/include/rainpoint_valve_pairing.h)
(`htv405RetainedRejoinRequestMatches`, `Htv405PairingSession::claimReply`),
[`rainpoint_pairing.h`](../firmware/rainpoint_bridge/include/rainpoint_pairing.h).

Automatic recovery currently enters through the sensor-only
`_maybe_start_known_sensor_rejoin`; valve `known_rejoin` dispatch is restricted
to HTV405, and firmware has no HTV213 pairing profile. A typed known-device
recovery dispatcher could reuse ownership, removal suppression, authentication
and cooldown checks while selecting model-specific replies. Success should
require addressed progress and a verified control, not merely an assignment
reply or an app showing the old closed state. Sources:
[`gateway.py`](../rainpointd_addon/rainpointd/gateway.py)
(`_maybe_start_known_sensor_rejoin`, `pairing_start`),
[`main.cpp`](../firmware/rainpoint_bridge/src/main.cpp) (`pairing_start` dispatch).

Keep master commands and device-originated phases independent: the battery
trial restarts device phases while the next accepted hub command advances
`3 → 4`. Do not reset the local command generator merely because a valve
reboots, or reseed it from report ACKs. That independence is already represented
in [`valve_protocol.py`](../rainpointd_addon/rainpointd/valve_protocol.py)
(`htv405_phase_state`, `decode_htv145_gateway_command`,
`build_htv145_report_ack`); the new capture strengthens its evidence rather
than demonstrating a new decoder defect.

Hub restart's native `20` kind-1 notification followed by accepted lower phase
`3` is a **synchronization candidate, not a proven reset instruction**. Preserve
the existing working pairing paths while adding offline lifecycle fixtures;
then distinguish notification causality in a separately authorized dry-valve
experiment before changing production startup or counter recovery behavior.

## Redacted lifecycle regression evidence

[`htv213_stock_lifecycle_20260928.json`](fixtures/htv213_stock_lifecycle_20260928.json)
preserves **64 selected validated frames** from the two quiet trials, hub-only
restart and valve-only battery cycle. Routes use the same synthetic identities
as the earlier control fixture; broadcast addressing is retained. Device clocks
in `81`, extended `82` and `04` are zeroed, and the legacy integrity residue is
recomputed. Originals remain private; this is not a production transmit recipe.

[`test_htv213_stock_lifecycle.py`](../tests/test_htv213_stock_lifecycle.py)
checks full six-bit response matching (including rejection of a truncated phase
63 reply), both-port revision/settings/plan progression, retained assignment
phases, confirmed 60-second controls and automatic-stop summaries, and the
separate report/master sequences. It preserves startup notification ordering
without asserting that `20` kind 1 causes a counter reset. Eight lifecycle tests
and the six earlier stock-capture tests pass together. Selected fixtures and
finite RF observations cannot establish an absent exchange universally.
