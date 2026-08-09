# Local radio-node onboarding

## Product goal

Adding a custom local radio node should feel like adding a Zigbee coordinator
and then pairing Zigbee devices through it. Users should not need to understand
TCP ports, HMAC, or RF endpoint identifiers during normal setup.

There are two deliberately separate flows:

1. **Add a local radio node**: attach an ESP32/CC1101 receiver to the logical
   custom local RF gateway over the LAN.
2. **Pair a RainPoint device**: discover or associate a moisture sensor or
   valve through that gateway, choosing the closest node where appropriate.

The RainPoint gateway and our custom local radio node must always be named
explicitly so users do not confuse the vendor hardware with this project.

## Prototype flow available now

The current firmware derives a stable `rp-xxxxxxxxxxxx` node ID from the ESP32
and accepts Wi-Fi configuration over its USB serial connection. The user:

1. Flashes the receive-only firmware and runs `show_node` over USB.
2. Generates a unique 32-byte enrollment token.
3. Adds the node-ID/token pair to the `rainpointd` app configuration.
4. Sends the tab-separated `configure_wifi` command over USB and restarts.
5. Confirms that `/api/v1/nodes` shows the node authenticated and receiving.

This is intentionally a test harness, not the final consumer experience.

## Target Home Assistant experience

The integration exposes **Add local radio node**. Starting it opens a short
commissioning window, much like permitting joins on a Zigbee network.

1. The user powers a factory-new node near Home Assistant.
2. HA discovers it through Bluetooth or a temporary setup access point. A
   manual setup-code path remains available when discovery fails.
3. The user scans the QR code on the node or enters its short setup code.
4. HA securely supplies Wi-Fi credentials and issues a unique long-term node
   credential. The bootstrap setup code cannot be reused after commissioning.
5. The UI shows the stable node identity, firmware, connection quality, radios,
   and last report time, then asks for a friendly name such as “Back Garden.”
6. The node appears as a device beneath the single custom local RF gateway.

Adding another node repeats the same flow; it does not create another HA
integration entry or another logical device network.

The separate **Add RainPoint device** action then:

1. Opens a time-limited RF learning/pairing window.
2. Asks the user to press the physical pair button on the sensor or valve.
3. Shows the discovered model and signal observations from every radio node.
4. Lets the user confirm name and area.
5. For a valve, requires the user to select the closest transmitter node before
   local control can ever be enabled. Receive quality can recommend a node but
   cannot silently select or change it.

## Authentication model

Every node has its own credential. Compromising or removing one node must not
require changing every other node. HA/rainpointd stores credentials as secrets,
never in entity state, diagnostics, or logs.

The prototype uses a server nonce and HMAC-SHA256 proof, so the enrollment token
is not sent over the LAN and captured proofs cannot be replayed against a new
nonce. That authenticates the node to `rainpointd`, but plain TCP does not give
us confidentiality, server authentication, or per-message integrity.

Before a public release—and before any network transmit path—the commissioned
session should provide:

- mutual authentication or a node-pinned gateway identity,
- encrypted transport,
- monotonically increasing, integrity-protected message sequence numbers,
- credential rotation and explicit revocation from HA,
- a physical factory-reset path, and
- fail-closed behavior when identity or session state is uncertain.

Valve commands additionally require the central safety lease and local node
watchdog described in the full-stack architecture. Node enrollment alone never
authorizes irrigation control.

## Migration and recovery

- Replacing Wi-Fi credentials should not change the stable node identity.
- Removing a radio node should retain RainPoint device identity and history;
  affected valves remain unavailable until a new transmitter node is selected
  and validated.
- A factory reset revokes or abandons the old credential and returns the node
  to commissioning mode.
- A lost or stolen node can be revoked from HA without resetting RainPoint
  sensors or valves.
