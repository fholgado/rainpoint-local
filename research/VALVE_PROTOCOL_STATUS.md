# Valve protocol status

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
disabled-by-default acceptance harness. It is not imported by the gateway,
HTTP server, or Home Assistant integration. An explicit bench caller must
inject the authenticated selected-node sender, provide a valid passive command
for counter synchronization, and provide confirmed idle evidence. The harness
allows exactly one duration-bounded logical open and passes only after positive
open evidence and an independent automatic-idle report within the expected
window.

The candidate node reports enough audit detail to distinguish nothing
transmitted, response-receiver failure, no matching response, a corrupt or
foreign matching-route frame, a missed fallback state confirmation, gateway
loss, and an ambiguous outbound counter. Standard firmware compiles the entire
HTV145 transmit candidate out.

## Remaining physical gates

1. Run the HTV145 dry-valve acceptance harness against the isolated valve.
2. Validate explicit HTV145 early stop and the 15-second hardware interval.
3. Capture stock battery rejoin for each valve family, then reproduce it
   locally without changing the proven new-enrollment paths.
4. Correlate a controlled HTV405 normal-to-low battery transition.
5. Repeat association/control acceptance on another specimen before promoting
   HTV405 control from beta or enabling a Home Assistant migration flow.
