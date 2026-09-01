# HWG023WBRF-V2 stock RainPoint gateway behavior

This document defines the RF behavior of the stock RainPoint gateway that
matters to local interoperability. It is a reference peer, not a component of
the custom local gateway.

## Association identity

The stock gateway uses association-specific controller, route, and companion
endpoints. A common controller/companion relationship is:

```text
controller = companion with first-byte bit 0x80 set
companion  = controller with first-byte bit 0x80 clear
```

This is not a universal source/destination rule. Some valve exchanges use an
additional association route, and endpoint roles reverse in acknowledgements.
The custom gateway must store the full device association rather than derive
all routes from one address at send time.

## Device Address and RF selector

The app's Device Address is a gateway-assigned list/slot value, not a universal
RF channel selector. Confirmed counterexamples include:

- an HCS026 sensor shown as Device Address `2` while using RF selector `4`;
- an HTV405 valve shown as Device Address `6` while using a selector-6 stock
  association;
- an HTV145 valve shown as Device Address `1` while using selector `6`.

Device Address may increment as devices are added to one stock gateway, but it
must not be used to construct RF carriers or pairing replies.

## Pairing behavior

The stock gateway runs a device-family-specific exchange:

- HCS02x sensor: three gateway replies and a terminal sensor confirmation;
- HTV405: an 18-stage observed valve transcript with 17 gateway transmissions;
- HTV145: a six-stage exchange plus a delayed long-wake configuration frame.

The device files define those exchanges. There is no single generic RainPoint
pairing handshake.

Product literature reports support for up to 39 subdevices. That capacity does
not prove 39 RF selectors: selectors are shareable association parameters.

## Routine acknowledgement behavior

The stock gateway acknowledges routine reports from paired sensors and valves.
Those replies are required for durable liveness even though the uplink report
itself can be decoded passively. The custom gateway reproduces the relevant
device-specific ACK and assigns exactly one transmitting radio-node owner per
device.

## Coexistence constraints

Two gateways that believe they own the same device can transmit overlapping
pairing replies or routine ACKs. Confirmed consequences include intermittent
pairing, sensors becoming dormant, and ambiguous association ownership.

Rules for the current local implementation:

- power off the stock gateway during new local enrollment;
- use a generated custom-gateway identity, not a copied stock identity;
- retain one ACK/control owner within the custom node mesh;
- treat stock-gateway traffic as an independent peer when coexistence is being
  tested;
- do not infer successful migration merely because both gateways can hear the
  same uplink.

Deleting a device from the RainPoint app has not been shown to transmit a
radio-level factory reset. A device can retain its RF association after app
deletion, and a battery cycle can attempt retained-association recovery before
or alongside factory enrollment behavior.

## Cloud/app metadata

The app exposes useful correlation metadata such as Device ID, Device Model,
Device Address, categorical Battery Level, gateway-measured RSSI, and firmware
version. These values are evidence aids, not necessarily over-the-air fields:

- RSSI is measured by the stock receiver;
- exact retail model and firmware may come from cloud product metadata;
- water volume and session duration may be cloud TLV values rather than raw RF
  positions;
- local runtime must not depend on cloud availability or silently substitute a
  cloud value for an undecoded RF value.

Cloud payload observations are kept separately in
[`../research/cloud/README.md`](../research/cloud/README.md).

## Evidence

- Device-specific pairing and communication definitions:
  [`README.md`](README.md)
- Capture chronology:
  [`../research/RF_CAPTURE_NOTES.md`](../research/RF_CAPTURE_NOTES.md)
- Raw/canonical fixtures: [`../research/fixtures/`](../research/fixtures/)
