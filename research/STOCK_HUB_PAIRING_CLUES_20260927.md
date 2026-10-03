# Stock firmware clues about the observed pairing behavior

Scope: compare the privately retained stock application **1.1.1040** with our
capture-backed pairing findings. This is an evidence note, not a new pairing
implementation or project checklist. Work priority remains in
[the roadmap](../PROJECT_ROADMAP.md). No hardware was used for this comparison.

## What the dump currently adds

**Follow-up, Sep 28:** the mappings initially open in this note now have a
[native cross-device comparison](PAIRING_NATIVE_COMPARISON.md) and
[configuration-builder trace](STOCK_HUB_PAIRING_CONFIGURATION_TRACE.md).
Commands `05`, `06` and `59` read per-port settings, plans and parameters;
the delayed `20` contains configuration version/update kind. The body field
formerly called a channel in the channel-change note has been corrected.
The following clue inventory preserves the earlier investigation stage;
use the linked traces and device references for current qualified meanings.

The dump contains concrete radio-configuration code and diagnostic references
to connection confirmation, reconnect acknowledgement, parameter retry and
attribute synchronization. Those are useful places to investigate **why** the
captured exchanges have several phases. We have not yet mapped those diagnostic
paths to the normalized packets in our fixtures. They do not establish a new
successful enrollment recipe or justify altering a proven prefix.

| Our observed finding | Relevant stock-firmware clue | What is established, and what remains open |
| --- | --- | --- |
| A white flash can precede later configuration and parameter traffic. HTV145 controls work after a partial local transcript. | Diagnostics distinguish connection-confirmation ACK (`0x3C154840`), reconnect ACK (`0x3C1527C8`), parameter retry (`0x3C152720`), and attribute-sync activity (`0x3C1547C8`). | **Plausible explanation:** association and later parameter synchronization are separate phases. Exact code-to-packet mapping is still required; the names alone do not prove that our missing terminal row is optional configuration. |
| Both valves share framing and some request families but require different continuations. | Stock code has per-port controller parameter parsing, device capability parsing and product-code dispatch. Candidate entries: `0x4203DFD0`, `0x420409AC`, `0x4203F0F0`, `0x4203AE3C`. | This is consistent with model/port-specific configuration. It does not establish that HTV405's 18 observed rows mean 18 mandatory authorization steps, or that HTV145 can reuse its table. |
| Correct bytes alone did not produce a successful HTV145 long configuration; hardware-clocked FIFO transmission advanced the device. | The stock CMT2300A backend loads six configuration banks through a byte-write loop, and has a separately selected FIFO-write path. | We can now investigate the actual modem configuration and framing rather than infer everything from RF. Which mode is active during assignment versus configuration, and later register overrides, remain to be traced. FIFO existence alone does not prove our previous waveform mismatch's exact cause. |
| Factory sweep count is not assigned channel or app Device Address. | The connection-request handler calls a usage-based channel allocator; instruction evidence follows below. The later receive-channel notification path is separate. | Captures already prove the count/selector distinction. The allocation path strengthens the case for an independent hub decision, but internal channel numbers have not been mapped to assigned RF selector fields. |
| Battery/recovery behavior differs from fresh enrollment. | Stock has a named reconnect-ACK path and MCU-abnormal-restart handling. | This supports keeping lifecycle operations separate, but does not prove a valve battery-rejoin packet or counter-reset rule. The MCU-restart code may serve other products in the shared image. |

Firmware evidence and disassembly limitations:
[initial stock analysis](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md),
[implementation comparison](STOCK_HUB_IMPLEMENTATION_COMPARISON_20260927.md#stock-paths-worth-tracing-next),
[custom-firmware assessment](STOCK_HUB_CUSTOM_FIRMWARE_FEASIBILITY.md).
All hex addresses above are stock runtime addresses, not flash offsets.

## New instruction-backed clues

These bounded disassembly observations refer to the newer retained app; they
inherit the alignment/tool limitations in the stock analysis. No runtime
instrumentation or RF transmission was used.

### Connection setup calls a usage-based channel allocator

`_bd_sdev_comm_connect_req` is referenced inside the function starting at
`0x420473A8`. Its new-device path logs address allocation (`0x420475A9`,
diagnostic at `0x3C15435C`) and calls `_bd_sdev_comm_allocate_channel` at
`0x42047611`. The result is stored separately, then the handler calls the
default RF-heartbeat helper at `0x4204761D`.

The allocator (`0x420403D4`) first builds usage counts via `0x420402B8`, then
calls `0x420388D8`. That function compares entries at internal indices 3–14,
collects equally minimal entries, chooses one using a helper, and returns its
index plus one. The usage builder counts device-record and pending-list fields
and applies conditional weighting. The tie helper (`0x420AE4FC`) reduces a
value from an indirect function modulo the candidate count; its value source
has not been identified, so randomness is not established.

This is stronger than a suggestive name: a connection path really performs
occupancy-based selection. It could explain why assignments depend on hub
state rather than just which announcement was heard. It **does not** yet map
internal indices to on-air selector/subchannel values or prove that every
device/model takes this branch. Do not implement an allocator or change the
frozen local selector from this evidence alone.

### Request, confirmation and reconnect are distinct code paths

`_bd_sdev_comm_check_header_data` at `0x4204A170` has a connection-request
branch referencing `0x3C1547F4` and a different confirmation branch at
`0x4204A460` referencing `0x3C154840`. These operate on decoded structures;
their field offsets are not our normalized RF offsets.

`_bd_sdev_comm_pack_protocal_header_data` at `0x4203A4FC` has a branch
logging reconnect ACK (`0x4203A5BA`, diagnostic `0x3C1527C8`). That branch
copies an identity field from its input where the alternative uses a value
loaded from gateway context. This is concrete evidence of different header
construction for reconnect, not proof of a particular battery-rejoin exchange.
The caller conditions, identity roles and wire serialization must be mapped
before we can safely generate that response.

The connection handler also installs a deadline using the constant 10,000
and the previously traced time-add helper. This is **not** evidence that our
2.95-second configuration timing or HA pairing window should become ten
seconds: the timer's lifecycle purpose remains unresolved.

### App RF-channel selection: new correlation lead

On September 27 the user reported that the RainPoint app exposes an RF-channel
choice for the hub. Available values and the behavior of changing it have not
been captured. No setting was changed during this investigation.

The retained 1.1.1040 application contains a `ReciCH` JSON key at `0x3C1476B0`
and includes it in the gateway parameter-name array at `0x3C14CC9C`. References
at `0x4200F3F4` and `0x4200FBF5` lead to configuration parsing: the first reads
a numeric JSON value and compares/stores its low byte; the second reads the
key and a nested value. These are configuration-structure offsets, not RF
packet offsets.

Separately, `bd_sdev_comm_inform_change_main_recv_channel` (`0x4204BBC0`)
collects eligible device recipients and calls the notification builder at
`0x4204ABA0`. This makes a coordinated receive-channel change a concrete
investigation target, rather than assuming the app simply retunes the hub.
The call chain from `ReciCH` to that routine, the app-to-frequency mapping,
and the notification's serialized bytes are **not yet established**. Do not
apply this setting to production devices or change local pairing selectors
on the strength of the field name alone. Work status is in the roadmap.

### Remaining limits

The image is the hub's firmware, not the valve's. It cannot directly establish
the valve LED state machine. No exact six-stage/18-row correspondence, final
terminal-packet requirement, fresh/battery command-counter reset rule, or reason
for every historical failure has been recovered. Existing capture-backed
carrier, FIFO and receive-turnaround corrections remain valid evidence; the
stock code does not erase those findings.

## Capture-backed facts the firmware must explain

### Sweep count, selector, address and command counter are different

Two stock HTV145 captures with opposite arming order accepted factory counter
**0** and **2**, respectively, but both assigned selector **6**, response
subchannel **12**, and completed the same six-stage exchange family. This is
direct evidence against treating the factory counter as the selected channel
or app Device Address. The sweep alternates carriers; a lower-carrier-only
analyzer previously missed the real counter-1 announcement.

Sources: [app-first stock enrollment](fixtures/htv145_counter0_app_first_stock_enrollment_20260901.json),
[button-first stock enrollment](fixtures/htv145_counter2_stock_enrollment_20260901.json).
The separate valve command sequence must not be initialized from those pairing
or report counters; see [HTV145](../protocol_documentation/htv145frf.md#persistence-and-ha-boundary)
and [HTV405](../protocol_documentation/htv405frf.md#command-response-and-sequence).

### Association, full transcript and operation are different verdicts

- **HCS026:** three gateway replies, followed by observation-only short and
  terminal messages. Retained factory rejoin and authorized paired recovery
  are separate from a new unknown-device enrollment.
- **HTV405:** the stock fixture contains 18 observed valve rows and 17 gateway
  transmissions, including repeat variants and an observation-only row. A
  generated local association does not require the stock `9a` tail to operate.
- **HTV145:** six numbered rows plus an unsolicited delayed long-wake
  configuration. Local evidence establishes the prefix through 5/6 and
  operational controls, but not receipt of the final `2c/99` request.

These counts describe our capture-derived state tables, not recovered stock
source-code state counts. Sources: [sensor protocol](../protocol_documentation/hcs026frf.md),
[four-zone protocol](../protocol_documentation/htv405frf.md#new-enrollment),
[one-zone protocol](../protocol_documentation/htv145frf.md#enrollment),
[partial-association controls](fixtures/htv145_partial_pairing_control_acceptance_20260905.json).

### Timing and carrier corrections made different boundaries advance

HTV145 stage-0 success did not establish later replies were correct. In the
September 2 comparison, changing the ordinary reply's measured center from
about **434.382 MHz** to **434.3515 MHz** stopped stage-1 retries, while the
delayed configuration was still rejected. Later, two unchanged unclipped
FIFO-configuration trials produced the configuration response and subsequent
addressed requests, advancing to **5/6**. Improved short-reply waveform matching
did not subsequently prove the terminal request.

Sources: [stage-boundary comparison](fixtures/htv145_counter2_local_stage1_acceptance_20260902.json),
[FIFO acceptance and terminal trials](fixtures/htv145_fifo_configuration_acceptance_20260904.json).
The [playbook](PAIRING_REVERSE_ENGINEERING_PLAYBOOK.md#preserve-the-waveform-and-receive-turnaround)
also records the separate HTV405 receive-FIFO issue: a redundant recovery/flush
after a successful reply could discard the arriving continuation.

## Interpretation traps in the current implementation

The Python [valve pairing module](../rainpointd_addon/rainpointd/valve_pairing_protocol.py)
retains a complete stock **counter-0** HTV145 reference table. The production
C++ [HTV145 module](../firmware/rainpoint_bridge/include/rainpoint_htv145_pairing.h)
instead freezes the accepted **counter-2/selector-6** recipe. Its software start
delay also uses a different boundary from SDR timestamps normalized to a
320-symbol wake. Do not compare a Python constant directly to the on-air local
timestamp and call the difference a regression.

Similarly, generic stock `get param`, `ACK`, `restart`, or `ser` names are not
decoded valve commands. The strongest next offline discriminator is to trace
their request/response serializers to the already captured `01/07`, `81/02`,
`03/01` and terminal `2c/99` families. That could distinguish mandatory link
setup from optional parameter exchange without another round of speculative
timing changes. Any proposed change still needs a fixture and preservation of
the accepted prefix.
