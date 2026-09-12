# Device and association recovery

For existing devices, prefer recovering the current association over deleting
and recreating it. Start by checking node connectivity, fresh device reports and
pending control/sync status. Unknown watering state is not proof that water is off.
Wait for an active bounded run to finish before changing ownership or removing
equipment; inspect the valve if its state cannot be confirmed.

## Choose the right operation

| Operation | What it changes | Recovery / limit |
|---|---|---|
| Restart HA or the gateway | Connections, not saved associations/counters | Keep the same database and credentials; wait for node authentication and fresh reports. Startup does not replay watering. |
| Reboot a radio | Its connection and runtime session | Keep commissioning state; verify reconnection and restored ACK ownership. Do not factory-reset just to recover Wi-Fi. |
| Re-pair an existing device | Its RF association and possibly its assigned endpoint | Use Add a RainPoint device without first deleting the HA device. Stable identity matching is implemented; verify one device/history and fresh reporting afterward. |
| Forget/remove a sensor in HA | Local metadata/enrollment, ACK assignment and suppression of its old endpoint | It is not a radio factory-reset command. Re-add with an explicit pairing flow; ordinary old packets should not recreate the forgotten device. |
| Forget/remove a valve | Local registration/control route, subject to pending-command and owner guards | Finish/cancel pending work and complete required owner revocation. If HA refuses deletion, resolve the reported condition; do not bypass it by editing the database. Re-pair and verify controls afterward. |
| Remove a radio node | Its gateway credential/registration, not its RainPoint devices | Restore/adopt a node and explicitly restore or transfer ownership. Revoking network access does not prove an old node has stopped local RF ACKs; keep it powered off if it cannot confirm revocation. |
| Factory-reset a radio | Commissioning state | Use only deliberately: provision Wi-Fi and adopt again through HA. Check each saved device's owner before resuming use. |
| Restore a gateway backup | Identity, credentials, counters and transactions from that backup | Restore matching gateway software/database together. Do not reuse a stale backup's counter as proof the physical valve is synchronized now. |

Removal may leave the browser on a now-invalid device detail page. Navigate back
to the integration's device list; automatic return is still a roadmap item.

## Re-pair and change owners

1. Keep the existing HA device when possible and turn off the stock RainPoint
   gateway during pairing.
2. In Configure → Add a RainPoint device, choose its model and intended radio.
3. Start pairing, perform the device gesture and wait for finalization.
4. Finish radio setup when offered. An ownership transfer must revoke the old
   transmitter before enabling the replacement; a transmitting old node must
   not be ignored merely because it is offline in HA.
5. Verify the device has one identity, the intended owner and a fresh reading.
   For valves, request a short dry/visually observed run to confirm actual
   opening and closing. Pairing/setup itself does not water.

If a removed sensor does not automatically appear again, use explicit pairing;
suppression is intentional. If ownership cannot be revoked or a pending action
cannot be resolved, retain diagnostics and stop rather than erasing state.

## Batteries and dormant devices

Known sensor recovery is implemented only for assigned identities and validated
rejoin messages. Replacing batteries is not equivalent to a proven fresh pairing
and must not blindly reset a valve counter. Observe fresh reports first. Sensor
and valve battery-change recovery, including stock/custom coexistence, still
needs the physical matrix in the [roadmap](../PROJECT_ROADMAP.md).

If reporting does not resume, check batteries/reception and use an explicit
re-pair when needed. Neither long-press nor battery reinstallation is a universal
guaranteed recovery procedure for every supported model yet. Keep the existing
HA record until those checks are exhausted.

## Before destructive maintenance

Back up the gateway database and HA configuration/source with their versions;
keep credentials private. After recovery, confirm node authentication, device
identity, ACK owner, availability and counter readiness. Never delete databases,
clear counters or trigger speculative watering merely to dismiss an error.
See [node setup](../NODE_ONBOARDING.md) and [firmware rollback](ALPHA_BUNDLE.md).

Implementation references: gateway forget/revoke guards, integration removal
hook, and registry/ownership regressions. This guide describes current behavior
and recovery limits; it does not certify every destructive transition on hardware.
