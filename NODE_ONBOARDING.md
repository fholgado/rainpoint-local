# Local radio-node onboarding

## Implementation status

Home Assistant can now register a provisioned ESP32/CC1101 radio node beneath
the existing custom local RF gateway. Legacy add-on `node_tokens` entries
migrate once into the same private SQLite registry. Registered nodes remain
visible while offline and expose connection, firmware, RF, memory, network,
temperature, and watchdog-oriented diagnostics as HA devices.

Commissioning still begins over USB in firmware 0.5: factory firmware generates
a private setup token, `show_node` displays it only while unconfigured, and the
user enters the stable ID/token before sending `configure_wifi`. This remains a
recovery and development path while the zero-copy flow below is implemented;
it is not the target product experience.

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

1. Flashes the radio-node firmware and runs `show_node` over USB. Pairing TX
   remains disarmed after boot.
2. Reads the firmware-generated 32-byte setup token.
3. Registers the node ID/token, name, and area from the HA Configure flow.
4. Sends the tab-separated `configure_wifi` command over USB and restarts.
5. Confirms that `/api/v1/nodes` shows the node authenticated and receiving.

This is a functional, physically bounded commissioning path, but not the final
wireless consumer experience.

## Target Home Assistant experience

The integration exposes **Add local radio node**. Starting it opens a short
commissioning window, much like permitting joins on a Zigbee network.

1. The user powers a factory-new node near Home Assistant.
2. The node exposes a temporary captive portal named **RainPoint Local Setup**.
   The user supplies only the home Wi-Fi credentials; ESP32 IDs, gateway
   addresses, ports, and tokens never appear in the normal UI.
3. Once on the LAN, the node advertises an adoptable service. HA discovers it
   and offers **Adopt radio node** beneath the existing custom local RF gateway.
4. HA requests identification. The selected node blinks its status LED and the
   user presses its physical BOOT button to confirm possession.
5. The custom local gateway creates a unique long-term node credential and HA
   delivers it to the physically confirmed node through the one-time adoption
   session. The secret is never shown to the user or exposed as entity state.
6. The UI asks only for a friendly name such as “Back Garden” and an optional
   area, then waits for the node's first authenticated connection.
7. The node appears as a device beneath the single custom local RF gateway.

The manual USB setup-code path remains available only as an advanced recovery
path when captive-portal or LAN discovery fails.

### Implemented adoption contract

The custom local gateway now owns the credential boundary required by this
flow. An authenticated HA request can create a five-minute adoption session
for one discovered ESP32 identity. The response gives HA a one-time credential
to deliver to the physically confirmed node; public node and adoption status
never expose it. The gateway accepts that credential only for the named node
and persists it in the managed registry only after the first successful mutual
authentication. Cancellation or expiry invalidates an uncommitted credential.

The temporary setup portal, LAN advertisement, BOOT-button confirmation, and
HA discovery UI remain the next implementation slice. Until those pieces are
verified together, the manual USB flow remains available and visible.

Adding another node repeats the same flow; it does not create another HA
integration entry or another logical device network.

### Required implementation boundary

The **Add local radio node** action should not appear until these pieces work
end to end:

1. `rainpointd` owns a persistent node registry instead of parsing the
   `node_tokens` JSON app option.
2. Its authenticated management API can open and cancel a time-limited
   commissioning session, issue one node credential, track physical
   confirmation, and revoke or rotate an existing node independently.
3. Factory firmware exposes a bounded commissioning transport—temporary setup
   access point, Bluetooth, or USB—with a one-time setup code and physical
   reset path.
4. The HA options flow starts commissioning, identifies the selected node,
   waits for its physical confirmation, and auto-advances after authentication
   before asking for its friendly name and area.
5. The connected node is registered beneath the existing custom local RF
   gateway as an HA device with firmware, connection, radio health, and last
   report diagnostics.
6. Removing a node revokes its credential without deleting RainPoint sensors;
   valves assigned to it become unavailable until explicitly reassigned and
   validated.

The first publishable commissioning path uses a temporary setup access point
for Wi-Fi and LAN discovery for adoption. BLE provisioning may later replace
the captive portal without changing the gateway registry or HA flow contract.

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
