# Revision A layout specification

All coordinates below are in millimetres, measured from the upper-left corner
of the finished PCB in the top assembly view. This document is the source of
truth for the first KiCad layout.

## Board and stackup

| Property | Value |
|---|---:|
| Finished outline | 68 x 66 mm |
| Layers | 2 |
| Thickness | 1.6 mm |
| Copper | 1 oz |
| Minimum track / clearance | 0.25 / 0.20 mm |
| Signal track target | 0.30 mm |
| 3V3 and GND track target | 0.50 mm |
| Via drill / diameter | 0.30 / 0.60 mm |
| Surface finish | HASL lead-free or ENIG |

Use rounded 0.8 mm outline corners. Put four 3.2 mm non-plated mounting holes
at `(3.5, 3.5)`, `(64.5, 3.5)`, `(3.5, 62.5)`, and `(64.5, 62.5)`.

## ESP32 placement

The ELEGOO board body is 29 x 51.74 mm. Place its upper-left corner at
`(8, 7)`, with the Wi-Fi antenna toward the top edge and USB-C toward the bottom
edge.

The two 1x19 socket centerlines are:

- left: X = 9.68 mm
- right: X = 35.32 mm
- first pin: Y = 10.01 mm
- pitch: 2.54 mm
- last pin: Y = 55.73 mm

The 25.64 mm socket-row separation intentionally follows the exact ELEGOO
product drawing rather than assuming the more common 25.4 mm value. The printed
fit check must resolve this 0.24 mm difference before routing is frozen.

Reserve `(7, 0.5)` through `(38, 18.5)` as a keepout on both copper layers. Do
not route traces, pour copper, or place the CC1101 inside that region. The
carrier may remain beneath the antenna mechanically; electrically it must be
empty.

## CC1101 placement

Place the 28 x 15 mm radio body at `(39, 25.5)` with its antenna connector
toward the right edge. The antenna connector and attached antenna may overhang
the carrier.

Place the 2x4 socket pad centers as follows:

| Pin | Signal | X | Y |
|---:|---|---:|---:|
| 1 | GND | 41.00 | 29.19 |
| 2 | 3V3 | 43.54 | 29.19 |
| 3 | GDO0 | 41.00 | 31.73 |
| 4 | CSN | 43.54 | 31.73 |
| 5 | SCK | 41.00 | 34.27 |
| 6 | MOSI | 43.54 | 34.27 |
| 7 | MISO/GDO1 | 41.00 | 36.81 |
| 8 | GDO2 | 43.54 | 36.81 |

The table is a **top carrier view**, with the radio plugged into female sockets.
Confirm that this produces the intended signal order on the actual module; a
bottom-view vendor diagram can otherwise mirror the footprint.

Place C1 and C2 on the carrier underside immediately beside pins 1 and 2 so the
radio can sit flat in its socket. Their ground and 3V3 connections should be as
short as practical.

## Routing priorities

1. Route GND and 3V3 first, including both decoupling capacitors.
2. Route SCK with a short, direct path and keep it away from the antenna edge.
3. Route MOSI and MISO alongside SCK without unnecessary loops.
4. Route GDO0 directly; this line carries timing-sensitive asynchronous TX data
   during pairing.
5. Route CSN, then reserved GDO2.
6. Add a ground pour to both layers everywhere except the Wi-Fi antenna keepout.
7. Stitch the pours with vias around the radio-side digital routing, but do not
   create a via fence under either antenna.

No trace is intentionally routed to ESP32 GPIO0 or GPIO2. They remain connected
only to the development board's onboard BOOT button and status LED.

## Silkscreen

The top side must show:

- `RAINPOINT RADIO NODE — REV A`
- `USB / POWER` at the ESP32 USB-C edge
- `Wi-Fi ANTENNA — NO COPPER` at the top
- `433 MHz ANTENNA` at the radio edge
- `3V3 ONLY` beside CC1101 pin 2
- pin-1 markers for the ESP32 and CC1101
- ESP32 and CC1101 outlines and orientation arrows

The underside must show the repository URL, revision, and a blank box for a
node/enclosure label. Do not put a fixed node ID in copper or silkscreen; node
identity is provisioned from the ESP32 hardware ID.

## Enclosure constraints

- Leave at least 10 mm of clearance around the ESP32 PCB antenna.
- Prefer plastic near both antennas; do not place a metal fastener or cable
  directly alongside the antenna elements.
- Expose USB-C without opening the radio compartment if practical.
- Provide strain relief for the USB cable in permanent installations.
- The PCB is not weatherproof. Use a ventilated indoor enclosure or a suitably
  rated outdoor enclosure with condensation control.
