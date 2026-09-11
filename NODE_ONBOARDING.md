# Local radio-node onboarding

For the complete first-install hardware, app and integration procedure, start
with [Getting started](GETTING_STARTED.md).

Adding a custom local radio node should feel like commissioning a Zigbee
coordinator: users supply Wi-Fi, identify the physical device, confirm it, and
give it a friendly name. They never copy ESP32 IDs, RF endpoints, ports, or
tokens during normal setup.

Always distinguish the vendor **RainPoint gateway** from a **RainPoint Local
radio node**.

## Normal flow

1. Flash the standard `rainpoint_bridge` firmware and power the node.
2. Join **RainPoint Local Setup xxxxxx** and enter home Wi-Fi credentials.
3. Home Assistant discovers the node under the existing RainPoint Local
   integration.
4. Choose a friendly name and area, use **Identify** if needed, and press the
   ESP32 BOOT button to confirm physical possession.
5. HA delivers a one-time gateway-issued credential. The node restarts,
   mutually authenticates, and appears as a device beneath the logical custom
   local gateway.

The flow auto-advances when confirmation/authentication is observed. Adding a
second node does not create another integration entry.
The management menu does not offer manual setup-code registration. Use the
discovered node's adoption flow rather than entering hardware IDs or tokens.

## Authentication and lifecycle

Every node receives an independent credential. The gateway stores it only
after the first successful mutual nonce/HMAC authentication. Public status,
entity attributes, diagnostics, and logs never expose it.

- Renaming or changing Wi-Fi does not change the stable hardware-derived node
  identity.
- Revoking/removing a node does not delete RainPoint sensors.
- Sensors assigned to a removed node must be explicitly reassigned.
- Holding BOOT for ten seconds factory-resets commissioning state.
- USB serial remains a recovery path through `show_node`, `configure_wifi`, and
  `clear_wifi`; it is not normal UX.

The candidate encrypts operational sessions with TLS-PSK using existing radio
credentials; the HA management interface and OTA downloads also use TLS.
There is no plaintext fallback. Initial HTTP adoption/Wi-Fi provisioning remains
a trusted-network operation; see [security details](SECURITY.md). Publisher
signing remains an alpha milestone, not something supplied by TLS.

## Placement and acceptance

Place nodes near the garden sections they serve while preserving reliable
Wi-Fi. Passive reception can use every node, but each paired sensor has exactly
one custom ACK owner. Every valve will require an explicitly selected nearest
transmitter before control is enabled.

Run the read-only acceptance checker after adoption or relocation:

```sh
python3 tools/check_radio_node.py \
  --gateway-url https://homeassistant.local:8787 \
  --token-file /path/to/private-management-token \
  --node-id rp-001122aabbcc \
  --save captures/node-acceptance/rp-001122aabbcc.json
```

It checks authentication, heartbeat freshness, Wi-Fi, heap, CC1101 health,
disarmed state, received RF traffic, and overlapping reception. Use the HA
**Identify** button separately to confirm the physical unit.

Useful placement targets:

- Wi-Fi RSSI better than roughly −75 dBm where possible;
- CC1101 antenna clear of soil, metal, USB supplies, and the ESP32 antenna;
- node assigned only to sensors it can hear consistently; and
- at least one independent passive receiver during protocol development.

## Pairing devices through a node

Use **RainPoint Local → Configure → Add a RainPoint device**, choose **Sensors**
or **Valves**, select a supported model, then choose the closest capable node.
**Next** advances to review without transmitting. Review offers **Back** to
change the radio/window, **Change device model**, and **Start pairing**. Close
the dialog with **X** to exit; only **Start pairing** arms a radio. The native
HA forms do not have footer Back buttons on every step.

Keep the stock RainPoint gateway powered off during the exchange so it cannot
race the selected transmitter. Long-term stock/local coexistence remains a
separate qualification gate in the [roadmap](PROJECT_ROADMAP.md). Do not delete
an existing HA device before reassociation; stable endpoint matching preserves
its entities and history.

HCS02x sensors, HTV405 four-zone valves and HTV145 single-zone valves appear in
the normal model picker. HTV145 automatic discovery requires firmware advertising
`htv145_auto_identity_pairing`; older nodes require an update, not manual IDs.
After naming an HTV145, finish radio setup. **Finish valve setup** resumes an
unfinished owner configuration later. This configures ACK/control ownership
without sending open/close commands. Leaving setup unfinished can leave the
valve without its report ACK owner, so complete this before putting it away.

The two-run qualification experiment no longer gates normal setup. Accepted
pairing supplies the selected owner and RF parameters; old ownership must still
be revoked and confirmed before replacement. Setup enables the control path
without claiming physical verification. Radio readiness,
fresh device state, counter synchronization and command-response checks remain.
Recommend a short run with a dry valve or direct visual confirmation of opening
and closing. No watering runs automatically as part of setup.

An old flow cannot act on a newer pairing session. Setup is resumable and does
not replay watering after a restart. The standalone research qualification
harness is separate from the user flow.

Confirmed fresh HTV145 pairing initializes counter 1 (`0x81`) once during owner
setup. Its source is explicitly pairing-derived until a matching positive command
reply confirms it. Initialization requires timestamped pairing evidence no more
than five minutes old; this is not a deadline for the first watering. A persisted
seed survives restarts. Repeated setup, passive reports and battery rejoin cannot
reseed it, and an unanswered first command invalidates counter readiness.
This remains an undeployed draft pending end-to-end acceptance.
HTV145 state is keyed by the full RF association, not the shared gateway endpoint.
Firmware advertising `htv145_multi_valve` holds up to eight independent single-zone
associations; older firmware retains one per radio. Counters, pending commands,
qualification and diagnostics remain independent. A busy radio rejects a second
valve command instead of interleaving transmissions or displacing an owner.
Existing qualified valves do not acquire a new test requirement on upgrade.
See the [roadmap](PROJECT_ROADMAP.md) for staged deployment and physical acceptance.
