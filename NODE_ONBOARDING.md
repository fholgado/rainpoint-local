# Local radio-node onboarding

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

Use **RainPoint Local → Configure → Pair sensor**, select the closest node, and
follow the progress modal. The stock RainPoint gateway must be powered off only
during the brief exchange so it cannot race the selected transmitter. Do not
delete an existing HA device before reassociation; stable endpoint matching
preserves its entities and history.

Valve onboarding will use the same node selection model only after the isolated
test-valve pairing and close-first safety sequence are physically validated.
