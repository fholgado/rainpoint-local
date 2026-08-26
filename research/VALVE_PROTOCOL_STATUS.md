# Valve protocol status

This is an evidence ledger, not a project checklist. Active order and
completion status live only in `../PROJECT_ROADMAP.md`.

This is the concise evidence ledger for the two tested RainPoint valve
families. `PROTOCOL.md` remains the detailed wire reference; this document
separates confirmed behavior from the physical gates that keep supervised
HTV405 control in disabled-by-default beta and still block HTV145 control.

## Terminology

- **New enrollment** assigns an association and completes the model-specific
  enrollment exchange.
- **Retained-association rejoin** resumes a previously stored RF identity. It
  is not new enrollment, even if the valve gives the same visible success LED.
- **Logical command** is one requested operation. It may contain a bounded set
  of byte-identical RF attempts; those attempts are not separate opens.
- **Command response** authenticates the outbound command sequence.
- **State report** independently proves watering or idle state. Its telemetry
  sequence never supplies the next command counter.

## Evidence ledger

| Capability | HTV405FRF four-zone | HTV145FRF single-zone |
|---|---|---|
| Receive/state decode | Confirmed | Confirmed |
| Duration decode | Confirmed | Confirmed for whole-minute commands |
| Zone selection | Confirmed for Zones 1--4; association-profile-specific packing | One zone |
| Local new enrollment | 18-step exchange physically reproduced | Not yet reproduced locally |
| Local bounded open | Physically confirmed on Zones 1--4 | Constructed and compile-tested; physical acceptance pending |
| Immediate command response | Physically confirmed | Stock response structure and timing confirmed |
| Independent state fallback | Physically confirmed | Stock behavior confirmed |
| Automatic stop | Physically confirmed | Stock behavior confirmed; local acceptance pending |
| Early stop | Locally confirmed on Zone 1; stock-cloud confirmed on all zones | Frame family decoded; local acceptance pending |
| Battery | Unknown in RF; HA must remain unavailable | Categorical normal/low bit confirmed |
| Battery-cycle rejoin | Unresolved | Unresolved |

## HTV405 recurring liveness acknowledgement

The stock RainPoint gateway answers ordinary HTV405 paired-link traffic after
enrollment. Four retained report/reply pairs, including idle and watering
state, place the reply 69--84 ms after the received report. The gateway reverses
the route to valve -> association companion, ORs byte 13 with `0x80`, ORs byte
14 with `0x40`, writes `01 00 01` at bytes 15--17, and clears bytes 18--35.
The reply has no zone, duration, or operation marker and is therefore a
non-actuating liveness response, not a control command.

The compact pairs are frozen in
`fixtures/htv405_stock_routine_ack_20260824.json`. Firmware schedules the reply
in the ordinary 49.5 ms post-RX slot on the association's selector-2 routine
carrier with a 320-symbol wake. Authorization is restored only to the durable
HTV405 control-node owner; reassignment revokes the former node before the new
node can answer. Both captured CRC residual families occur, while the first
production candidate uses the captured-valid `0xc713` family pending an
over-air acceptance/soak result.

## HTV405 lifecycle findings

The retained cross-reference contains 11 attempts: three
retained-association rejoins, two assignment-followed-by-paired-traffic cases,
two assignment-only failures, two cold-boot sweep-only cases, one explicit
sweep-only failure, and one invalid-methodology trial. Only the controlled
20:17 capture proves acceptance of a new assignment.

`0x7f` identifies the observed battery/cold-boot sweep and `0xff` identifies
the explicit long-press enrollment sweep. The valve can retain its paired
identity across battery removal, but neither a boot sweep, a transmitted first
reply, nor a white LED proves that it rejoined. The unchanged 18-step exchange
after a `0x7f` trigger stopped at step 1/18. No further local rejoin hypothesis
should replace it until a continuous stock-gateway battery-rejoin capture
establishes the actual reply count, carriers, payloads, and terminal evidence.

On August 24, the stock gateway was powered off and a custom node running the
known-good `0.14.0-combined.1` pairing image answered an explicit long press.
The node completed 3/18 fresh-enrollment replies, after which the valve gave a
white flash and resumed a complete stream of authenticated paired idle reports.
This is retained-association local takeover evidence, not a new assignment.
The redacted frames are frozen in
`research/fixtures/htv405_retained_takeover_20260824.json`. A migration path
may accept that outcome only for a previously known association whose existing
controller identity is being preserved; unknown devices still require 18/18.

Run the retained lifecycle classifier with:

```sh
python3 tools/valve_trial_analysis.py htv405-lifecycle \
  research/fixtures/htv405_pairing_cross_reference_20260820.json
```

## Transaction evidence

`tools/valve_trial_analysis.py transactions` correlates commands, bounded RF
attempts, immediate responses, and independent state reports for either model.
It understands both HTV405 command-zone layouts rather than treating the
association branch as only a frequency choice.

The retained HTV145 evidence resolves two logical opens from four RF attempts.
The 1,200-second open used three identical attempts at offsets 0, 729.210, and
1,668.479 ms, followed by a matching response 50.825 ms after the last attempt.
The 600-second open has no valid captured response but is positively confirmed
by its independent watering report. Their telemetry sequences differ from
their command sequences, confirming that the counters are independent.

## Acceptance boundary

`rainpointd.htv145_acceptance.Htv145DryValveAcceptance` is the isolated,
disabled-by-default acceptance harness. The gateway imports it only when the
temporary `htv145_dry_acceptance` option is enabled and exposes it through a
token-protected `/api/v1/research/htv145-acceptance/*` boundary; Home Assistant
does not expose these controls. `tools/run_htv145_acceptance.py` derives fresh
idle evidence and the next independent command counter from the retained event
journal, enforces a stock-controller RF-silence window, and requires an
explicit `--execute` switch. The harness allows exactly one duration-bounded
logical open and passes only after positive open evidence and an independent
automatic-idle report within the expected window.

The candidate node reports enough audit detail to distinguish nothing
transmitted, response-receiver failure, no matching response, a corrupt or
foreign matching-route frame, a missed fallback state confirmation, gateway
loss, and an ambiguous outbound counter. Standard firmware compiles the entire
HTV145 transmit candidate out.

### First isolated transmit result — 2026-08-25

The first unattended dry-valve trial exposed a carrier-selection defect before
it exposed a valve result: the retained stock command was explicitly received
on RainPoint channel 11, whose CC1101 center is 434.239594 MHz, while the first
runner invocation used a 433.920 MHz default. That attempt produced no valve
evidence and is discarded as an off-channel trial.

The corrected run inferred channel 11 from the positively confirmed stock
command and sent one logical 60-second open as three byte-identical attempts.
Both the SDR and another radio node received the constructed ordinary frame;
the second node reported approximately -57.5 dBm, the trailer residue was the
association-evidenced `0xc713`, and the long wake prefix was 1,200 symbols. No
valve response, active report, physical actuation, or later idle report was
observed. The selected node had recently received the valve itself around
-70 dBm, so the run establishes a clean local transmission but not valve
acceptance.

The valve's last independently confirmed pre-trial report already carried the
categorical low-battery flag, and its routine heartbeat stopped during the
acceptance window. It later resumed valve-originated traffic and produced a
valid idle/low-battery report about 26 minutes after the corrected command.
That late idle proves the radio was not completely dead, but it cannot confirm
an open because there was no immediate response, active report, actuation, or
expected 60-second idle transition. Low-voltage command/actuator lockout is
therefore the leading blocker, not a protocol conclusion. Further transmit
trials are blocked until fresh batteries produce a new valve-originated report
and a new stock command is positively confirmed by a matching response or
state transition. The runner now rejects low or unknown battery state, derives
the carrier only from retained channel evidence, and refuses to reuse command
evidence from before a prior local attempt.

The trial also proved an important receive-side boundary: a receiver can hear
the local controller request even when the valve does not accept it. Controller
requests are now retained only as command intent and never update valve state,
availability, or device-report cadence; only reverse-route response or state
traffic can do so.

## Unresolved physical evidence summary

1. Replace the isolated HTV145 batteries, obtain fresh valve-originated idle
   and positively confirmed stock-command evidence, then repeat exactly one
   correct-channel dry-valve acceptance run.
2. Validate explicit HTV145 early stop and the 15-second hardware interval.
3. Capture stock battery rejoin for each valve family, then reproduce it
   locally without changing the proven new-enrollment paths.
4. Correlate a controlled HTV405 normal-to-low battery transition.
5. Repeat association/control acceptance on another specimen before promoting
   HTV405 control from beta or enabling a Home Assistant migration flow.
