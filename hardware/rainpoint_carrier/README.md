# RainPoint radio-node carrier

This directory defines the first passive carrier PCB for the validated
RainPoint radio-node prototype. It converts the working Dupont-wire build into
a socketed assembly without replacing either module.

## Design status

**Revision A is an engineering prototype.** Its electrical mapping follows the
working bridge exactly. The ESP32 mechanical dimensions are taken from the
ELEGOO EL-SM-012 drawing. Before ordering, print the generated Letter-size fit
check PDF at **Actual Size / 100%**, place the actual ESP32 and CC1101 modules
over it, and complete the checklist in `PREORDER_CHECKLIST.md`. That physical
fit check is deliberately required
because inexpensive CC1101 modules are sold under several mechanically
different board revisions.

## Design goals

- Socket the existing ELEGOO ESP-WROOM-32 USB-C development board.
- Socket one 433 MHz CC1101 module with a 2x4, 2.54 mm header.
- Power the entire node through the ESP32's existing USB-C connector.
- Power the CC1101 from the ESP32's regulated 3.3 V output.
- Retain the ESP32's onboard GPIO2 LED and GPIO0 BOOT button as the only local
  user interface.
- Leave both USB-C and the CC1101 antenna connector accessible at board edges.
- Keep the ESP32 PCB antenna clear of carrier copper and the 433 MHz module.
- Use a two-layer PCB and only through-hole module sockets for easy hand
  assembly.

## Deliberately omitted

The carrier has no USB connector, regulator, 5 V input, level shifter, power
LED, status LED, reset switch, pairing switch, or configuration jumpers. Those
functions already exist on the ESP32 development board or in firmware.

The only components other than the two sockets are local CC1101 supply
decoupling:

- C1: 100 nF ceramic
- C2: 10 uF ceramic

C1 is the high-frequency bypass recommended at the radio supply. C2 provides a
small local reservoir for transmit-current steps. They do not participate in
the user interface.

Firmware therefore continues to use:

| User interaction | ESP32 resource | Carrier connection |
|---|---|---|
| Status / identify indication | Onboard LED, GPIO2 | None |
| Pairing confirmation | Onboard BOOT button, GPIO0 | None |
| Reset / recovery | Onboard EN button | None |

## Electrical mapping

| CC1101 signal | ESP32 signal | Firmware use |
|---|---|---|
| VCC | 3V3 | Radio power; never connect to 5 V |
| GND | GND | Common return |
| SCK | GPIO18 | VSPI clock |
| MISO / GDO1 | GPIO19 | VSPI input |
| MOSI | GPIO23 | VSPI output |
| CSN | GPIO27 | Primary-radio chip select |
| GDO0 | GPIO26 | Receive interrupt and asynchronous pairing TX data |
| GDO2 | GPIO25 | Reserved/diagnostic |

The connector pin numbering used by this design, viewed from the top of the
carrier with the radio antenna pointing away from the ESP32, is:

```text
ESP32 side                         antenna side

       +-------------------------------+
 GND  1 o  o 2  3V3                   |
GDO0  3 o  o 4  CSN       CC1101      |---- antenna
 SCK  5 o  o 6  MOSI                  |
MISO  7 o  o 8  GDO2                  |
       +-------------------------------+
```

This is the common 28 x 15 mm CC1101 module pinout. Do not order the PCB until
the labels on the actual module have been compared with this diagram.

## Mechanical arrangement

- Carrier outline target: 68 x 66 mm, two layers, 1.6 mm FR-4.
- ESP32 USB-C faces the bottom edge.
- ESP32 PCB antenna faces the top edge.
- CC1101 antenna connector faces the right edge.
- No copper or module body is placed under or immediately beyond the ESP32 PCB
  antenna.
- Four M3 mounting holes support an enclosure or standoffs.
- Female sockets on the carrier accept the modules' male 2.54 mm headers.

The orthogonal antenna placement is intentional: it separates the CC1101
module and antenna feed from the ESP32's 2.4 GHz PCB antenna while keeping both
external interfaces reachable after the carrier is installed in a case.

## Files

- `bom.csv`: prototype bill of materials.
- `pinout.csv`: machine-readable net mapping.
- `placement.svg`: 1:1 top-view assembly and fit-check drawing.
- `generate_fit_check_pdf.py`: generator for the print-calibrated Letter PDF.
- `../../output/pdf/rainpoint_carrier_rev_a_fit_check.pdf`: preferred printable
  fit-check sheet, including independent metric and inch calibration marks.
- `LAYOUT.md`: placement coordinates, stackup, routing, and enclosure rules.
- `PREORDER_CHECKLIST.md`: physical, electrical, and manufacturing gates.

KiCad schematic and PCB files should not be released for fabrication until the
1:1 fit check confirms the actual CC1101 header orientation and the ESP32
header-row measurement. The documentation here is the frozen input to that
layout rather than an invitation to infer missing dimensions.

## Mechanical references

- [ELEGOO EL-SM-012 manual and dimension drawing](https://manuals.plus/asin/B0D8T53CQ5)
- [Common 28 x 15 mm CC1101 module specification](https://manuals.plus/ae/1005009185963141)

The second reference describes the module family, not proof of the particular
seller revision in hand; this is why the printed fit and pin-label check remains
a release gate.
