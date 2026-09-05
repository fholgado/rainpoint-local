# Home Assistant radio-frequency building block and RainPoint Local

Research snapshot: 2026-09-01, against Home Assistant 2026.8 documentation and
the then-current `dev` source. Retained during the 2026-09-05 workspace
consolidation; this is not a fresh upstream compatibility check. Project status
and implementation order live only in [the roadmap](../PROJECT_ROADMAP.md).
This note evaluates the Home Assistant
`radio_frequency` building block, not RF support in Home Assistant generally.

## Conclusion

RainPoint Local should **not implement or consume Home Assistant's
`radio_frequency` entity platform in its current form**. The platform is a
useful hardware/device decoupling pattern, but its executable contract is
transmit-only and OOK-only. RainPoint uses addressed, bidirectional 2-FSK PCM,
multiple RF channels, protocol-managed pairing and acknowledgements, and
safety-gated transmitter ownership. Representing a RainPoint node as a generic
Home Assistant RF transmitter would therefore be inaccurate and would weaken
the repository's deliberate command-authority boundary.

Two ideas are worth retaining:

1. Preserve the existing separation between the RainPoint device integration
   and the physical radio-node transport. Home Assistant's provider/consumer
   split validates that architectural direction.
2. Consider the platform's adapter inventory UX -- availability, location,
   supported bands, and last-used time -- for RainPoint's own radio-node
   diagnostics. Do not inherit its generic-send semantics.

Reassess direct integration only after Home Assistant supports FSK and receive
or transceiver workflows with enough parameters and lifecycle semantics to
express the RainPoint exchange safely.

## What the Home Assistant integration is

`radio_frequency` is an internal building-block integration introduced in Home
Assistant 2026.5. A user does not add it directly. A hardware integration
provides one entity per RF transmitter; a device-specific consumer integration
selects one of those transmitters and sends its protocol-specific commands
through it. Home Assistant describes the intent as decoupling transmitter
hardware from controlled devices, analogous to its infrared platform.
([user documentation](https://www.home-assistant.io/integrations/radio_frequency/),
[developer announcement](https://developers.home-assistant.io/blog/2026/04/24/radio-frequency-entity-platform/),
[2026.5 release notes](https://www.home-assistant.io/blog/2026/05/06/release-20265/#radio-frequency-joins-infrared-as-a-first-class-citizen))

The entity represents a transmitter, not an RF-controlled appliance and not a
radio receiver. Its normal state is the UTC timestamp of the last successful
send; `unknown` and `unavailable` are the other meaningful states. The base
class restores the timestamp after restart and writes a new one only after the
provider's send method returns. Passing the Home Assistant action context into
the transmitter lets the logbook identify the integration or automation that
caused a transmission.
([documentation](https://www.home-assistant.io/integrations/radio_frequency/#about-the-state-of-a-radio-frequency-entity),
[entity source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/entity.py),
[send helper source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/helpers.py))

The integration also registers an administrator-only WebSocket command,
`radio_frequency/list`. It reports each transmitter's entity, device and config
entry IDs, supported frequency ranges, and supported modulations. This powers a
central Radio frequency settings panel that shows online adapters and their
last-used times.
([WebSocket source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/websocket_api.py),
[adapter-panel documentation](https://www.home-assistant.io/integrations/radio_frequency/#viewing-your-radio-frequency-remote-adapters))

There is no generic user-facing `radio_frequency.send` action in the component.
Device integrations call its Python helper; this intentionally keeps protocol
and device semantics above the transmitter abstraction.
([component tree](https://github.com/home-assistant/core/tree/dev/homeassistant/components/radio_frequency),
[developer documentation](https://developers.home-assistant.io/blog/2026/04/24/radio-frequency-entity-platform/#building-a-consumer-integration))

## Command and capability model

The Home Assistant component pins `rf-protocols==4.3.0`. Its command abstraction
contains:

| Field | Meaning |
|---|---|
| `frequency: int` | Carrier frequency in hertz |
| `modulation: ModulationType` | Currently only `OOK` exists |
| `repeat_count: int` | Additional sends after the first |
| `symbol_rate: int | None` | Optional baud rate metadata |
| `output_power: float | None` | Optional dBm metadata |
| `get_raw_timings() -> list[int]` | Alternating signed pulse/space durations in microseconds |

Positive even-indexed durations are carrier-on pulses and negative odd-indexed
durations are carrier-off spaces, matching Flipper RAW timing format. The
library also provides `OOKCommand` as a direct raw-timing implementation.
([Home Assistant manifest](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/manifest.json),
[`RadioFrequencyCommand` source](https://github.com/home-assistant-libs/rf-protocols/blob/main/rf_protocols/commands/__init__.py),
[`OOKCommand` source](https://github.com/home-assistant-libs/rf-protocols/blob/main/rf_protocols/commands/ook.py))

Despite the forward-looking fields, the Home Assistant transmitter base class
hard-codes modulation support to OOK. `async_get_transmitters()` filters entities
by inclusive frequency ranges and modulation. `async_send_command()` resolves
an entity ID or registry UUID, repeats the same capability checks, propagates
context, and invokes the provider. A consumer base entity added in 2026.8 tracks
transmitter availability and follows entity-ID renames.
([component source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/__init__.py),
[entity source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/entity.py),
[consumer helper source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/helpers.py),
[2026.8 changelog](https://github.com/home-assistant/home-assistant.io/blob/current/source/changelogs/core-2026.8.markdown))

## Documented providers and consumers

The documented transmitter providers are:

| Provider | Current scope |
|---|---|
| ESPHome | Exposes configured RF transmit-capable proxy entities through its native API. Home Assistant filters out receive-only ESPHome RF entities and maps only OOK commands. |
| Broadlink | Exposes RF entities for RM pro and RM4 pro hardware. Current source advertises 433.05--434.79 MHz and 314.95--315.25 MHz OOK bands and quantizes raw timings to 32.84-microsecond device ticks. Existing Broadlink `remote.learn_command` and `remote.send_command` remain separate from this building block. |

Sources: [ESPHome provider source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/esphome/radio_frequency.py),
[Broadlink provider source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/broadlink/radio_frequency.py),
[Broadlink documentation](https://www.home-assistant.io/integrations/broadlink/#radio-frequency).

ESPHome's own RF API can describe transmitter and receiver capabilities, and
its experimental proxy can forward received raw timings to API clients.
However, Home Assistant's provider currently creates entities only when the
ESPHome capability includes `TRANSMITTER`; the Home Assistant building block
has no receive entity or receive callback. ESPHome likewise documents that the
proxy's raw timing representation is suitable for OOK and that additional
modulations such as FSK are future work.
([ESPHome RF component](https://esphome.io/components/radio_frequency/),
[ESPHome IR/RF proxy](https://esphome.io/components/ir_rf_proxy/),
[Home Assistant ESPHome provider source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/esphome/radio_frequency.py))

Documented device-specific consumers as of this snapshot are:

| Integration | Function | RF/state behavior |
|---|---|---|
| Honeywell String Lights | Light on/off | 433.92 MHz OOK; assumed state |
| Novy Cooker Hood | Four-speed fan and light | 433.92 MHz OOK; assumed/restored state |
| KlikAanKlikUit | Self-learning outlets, built-in devices, dimmers, and compatible Intertechno/Nexa/Telldus products | 433.92 MHz OOK; one-way assumed state |

Sources: [Honeywell String Lights](https://www.home-assistant.io/integrations/honeywell_string_lights/),
[Novy Cooker Hood](https://www.home-assistant.io/integrations/novy_cooker_hood/),
[KlikAanKlikUit](https://www.home-assistant.io/integrations/klik_aan_klik_uit/).

The external `rf-protocols` repository contains more encoders than Home
Assistant has device integrations, including CAME, EV1527, Harbor Breeze A25,
Hormann, KlikAanKlikUit, Marantec, Novy, Pilota Casa, PT2262, and Somfy RTS.
Library presence alone does not make a protocol or device configurable in Home
Assistant; a consumer integration and config flow are still required.
([encoder directory](https://github.com/home-assistant-libs/rf-protocols/tree/main/rf_protocols/commands),
[developer guidance](https://developers.home-assistant.io/blog/2026/04/24/radio-frequency-entity-platform/#rf-protocols-and-codes))

## Extension mechanism

A new transmitter integration:

1. Provides the `radio_frequency` platform.
2. Subclasses `RadioFrequencyTransmitterEntity`.
3. Declares one or more `(min_hz, max_hz)` ranges.
4. Implements `async_send_command()` and translates the common command into its
   hardware API, raising `HomeAssistantError` on failure.

A new device consumer:

1. Declares `radio_frequency` as a manifest dependency.
2. Encodes device commands using `rf-protocols` or a separate third-party
   library for niche/proprietary protocols.
3. Uses a representative command with `async_get_transmitters()` during config
   flow, so the user sees only frequency/modulation-compatible transmitters.
4. Stores the selected entity ID or registry UUID and sends commands with the
   common helper, preferably via `RadioFrequencyTransmitterConsumerEntity` so
   availability and transmitter renames are handled consistently.

Sources: [developer guide](https://developers.home-assistant.io/blog/2026/04/24/radio-frequency-entity-platform/),
[public exports and filtering](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/__init__.py),
[consumer helper](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/helpers.py).

## Maturity and caveats

- The Home Assistant entity was introduced only in 2026.5 and is marked
  `quality_scale: internal`, appropriate to a core building block rather than a
  user integration with a normal quality-scale score. It is maintained by the
  Home Assistant core team.
  ([manifest](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/manifest.json),
  [documentation](https://www.home-assistant.io/integrations/radio_frequency/))
- The ESPHome RF entity/proxy is explicitly experimental and outside its normal
  breaking-change policy. Its general RF component says dedicated platform
  implementations are planned and currently exposes only OOK.
  ([ESPHome RF component](https://esphome.io/components/radio_frequency/),
  [ESPHome proxy](https://esphome.io/components/ir_rf_proxy/))
- The platform sends but does not learn, receive, decode, await an RF reply, or
  confirm appliance state. Existing consumers consequently document one-way,
  assumed state. Broadlink's legacy learning/sending functions are a separate
  `remote` entity API.
  ([Home Assistant entity source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/entity.py),
  [Broadlink documentation](https://www.home-assistant.io/integrations/broadlink/#radio-frequency),
  [Honeywell limitations](https://www.home-assistant.io/integrations/honeywell_string_lights/#assumed-state))
- Frequency and modulation compatibility filtering is intentionally shallow.
  It does not verify deviation, receiver bandwidth, sync/framing, channel
  sequence, turnaround timing, protocol identity, or whether an adapter is
  authorized to control a particular paired device.
  ([command model](https://github.com/home-assistant-libs/rf-protocols/blob/main/rf_protocols/commands/__init__.py),
  [filter source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/radio_frequency/__init__.py))
- Although commands carry optional symbol-rate and output-power fields, the
  current ESPHome and Broadlink Home Assistant providers do not pass either to
  their hardware send calls.
  ([ESPHome provider](https://github.com/home-assistant/core/blob/dev/homeassistant/components/esphome/radio_frequency.py),
  [Broadlink provider](https://github.com/home-assistant/core/blob/dev/homeassistant/components/broadlink/radio_frequency.py))

## Comparison with RainPoint Local

| Concern | Home Assistant building block | RainPoint Local |
|---|---|---|
| Modulation | OOK only | 2-FSK PCM at 20 ksymbol/s |
| Payload model | Alternating carrier-on/off microsecond timings | Fixed addressed frames with sync, data, and trailer validation |
| Direction | Send-only | Continuous receive plus tightly bounded pairing/rejoin and ACK transmission |
| Frequencies | One carrier per command, filtered against ranges | Multiple measured request/reply channels and selector-dependent channel changes |
| Completion | Provider send returned; entity records timestamp | Protocol evidence may require replies, confirmations, terminal pairing messages, and observed valve state |
| State | Transmitter last-used timestamp; appliance consumers often assume state | Received soil/valve state, association state, link diagnostics, and multi-receiver evidence |
| Authority | User selects any compatible transmitter | ACK ownership is single-node and persistent; reassignment revokes the old owner; valve control is separately gated |

RainPoint physical and safety facts are documented in
[`../PROTOCOL.md`](../PROTOCOL.md), especially the physical layer, pairing,
authorized sensor recovery, remaining protocol work, and safety boundary. The
runtime separation and authority constraints are summarized in
[`../HARDENING_INVENTORY.md`](../HARDENING_INVENTORY.md).

The current command object cannot represent RainPoint's 2-FSK tones or
frequency deviation at all. Even if `FSK` were added to the enum, the present
contract still lacks the receive/response lifecycle, channel and turnaround
sequence, packet/symbol representation, receiver configuration, and ownership
semantics needed by this protocol. Its `symbol_rate` and `output_power` fields
are not enough.

## Recommended disposition

### RainPoint integration boundary

- Keep `rainpoint_local` as a `local_push` hub integration backed by
  `rainpointd`; do not add `radio_frequency` to its manifest.
- Keep protocol framing, association, ACK ownership, and safety policy below
  Home Assistant's device entities, as they are now.
- If improved HA visibility is desired, expose RainPoint-specific radio-node
  diagnostics such as online status, last successful authorized transmission,
  coverage/receiver evidence, selected owner, and firmware capability. These
  are truthful domain diagnostics; a generic RF transmitter entity is not.
- Preserve the conceptual provider/consumer seam when the protocol core is
  eventually extracted: device intent should remain separate from the
  selected physical node, but node selection must pass through RainPoint's
  association and authorization rules.

### Unsupported mappings

- Do not advertise the ESP32/CC1101 node as OOK merely to make it appear in the
  Radio frequency panel.
- Do not add an unrestricted raw RF send path. The supported firmware
  exposes authorized, identity-bounded sensor and HTV405 operations. HTV145
  qualification remains separately gated. See the current
  [firmware contract](../firmware/rainpoint_bridge/README.md).
- Do not model RainPoint commands as static learned remote codes. Their
  endpoints, counters, acknowledgements, association state, and safe valve
  lifecycle are protocol state, not just waveforms.
- Do not let a generic transmitter selector bypass persistent ACK ownership or
  the separate valve-control gate.

### Compatibility criteria for a future upstream reassessment

1. 2-FSK with deviation/tone and receiver-bandwidth parameters.
2. Packet bytes or binary symbol streams, not OOK mark/space timings only.
3. Receive events and request/reply correlation.
4. Per-exchange channel changes and bounded receive-to-transmit turnaround.
5. A provider result richer than "send returned", so acknowledgements and
   confirmed state remain distinct from attempted transmission.
6. A way for a consumer to restrict eligible transmitters by protocol
   capability and persistent device ownership, not frequency/modulation alone.

Until then, using the building block would add UI consistency at the cost of a
false capability model. The architectural idea is sound; the current API is
the wrong protocol layer for RainPoint Local.
