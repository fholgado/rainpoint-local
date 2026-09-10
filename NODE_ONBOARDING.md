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

The trusted-LAN TCP prototype authenticates both parties but is not encrypted.
Publication requires encrypted sessions, replay-protected messages, credential
rotation/revocation, and gateway identity pinning.

## Placement and acceptance

Place nodes near the garden sections they serve while preserving reliable
Wi-Fi. Passive reception can use every node, but each paired sensor has exactly
one custom ACK owner. Every valve will require an explicitly selected nearest
transmitter before control is enabled.

Run the read-only acceptance checker after adoption or relocation:

```sh
python3 tools/check_radio_node.py \
  --gateway-url http://homeassistant.local:8787 \
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
After naming an HTV145, choose to verify controls now or finish without testing.
**Verify valve controls** returns to a paired valve's pending setup later.
Finishing without testing does not finish ACK/control-owner provisioning; if the
valve stops reporting before verification resumes, it may need to be woken or
paired again. The flow will not guess its state or send an open without evidence.

Verification requires explicit approval for two requested 60-second runs (or a
dry valve): automatic stop, then an early stop after at least 20 seconds. Keep
the flow open. The gateway derives the selected owner and RF parameters from
accepted pairing, confirms any old owner's revocation, and requires fresh owner
telemetry before the idle anchor. If that anchor fails, one fixed first-open
candidate may initialize this association; only its positive response supplies
counter authority. No failed open is retried automatically. Independent stop
reports must complete both tests before public controls become available.

Closing the flow stops subsequent test steps; a started bounded run may still
finish automatically. Failure, owner reconnect, expiry or gateway restart ends
the verification attempt without replay. Inspect the device before re-pairing
and granting fresh consent. An old flow cannot act on a newer pairing session.
The current HTV145 runtime supports one single-zone valve per custom gateway
identity and per node; onboarding refuses to displace a different valve's owner.
Existing qualified valves do not acquire a new test requirement on upgrade.
See the [roadmap](PROJECT_ROADMAP.md) for staged deployment and physical acceptance.
