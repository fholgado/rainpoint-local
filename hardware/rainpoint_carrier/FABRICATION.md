# Revision B fabrication package

**Rev A is withdrawn: its CC1101 rows are reversed. Do not order the old ZIPs.**
Git history preserves the original files for defect analysis. Existing boards
require the verified crossover described in `REV_A_REWORK.md`.

Revision B is a passive carrier for the physically verified 30-pin ESP32 board
and the tested 2x4 CC1101 radio module. The PCB supplies no independent power;
the completed node is powered through the ESP32 USB-C connector.

## Validation status

Mechanical alignment does not certify pin orientation. Rev B requires all
physical pin, continuity and power checks in `PREORDER_CHECKLIST.md` before
direct-plug functional acceptance. CAD validation results must be regenerated
for this revision, not inherited from Rev A.

- ESP32 footprint physically overlaid at 1:1 scale: **passed**
- ESP32 sockets: two 1x15 rows, 2.54 mm pitch, 25.40 mm row spacing
- CC1101 hole overlay: **passed mechanically only**; Rev B numbered orientation review required
- KiCad 10.0.6 ERC: **0 violations** (Rev B, Sep 14)
- KiCad 10.0.6 DRC: **0 violations, 0 unconnected pads, 0 footprint errors**
- KiCad 10.0.6 schematic-to-PCB parity: **0 issues**
- Four physical-position/net regression tests: **passed**, including exported IPC-D-356
- Finished board outline reported by KiCad: **68.00 x 66.00 mm**
- Drill inventory: 38 x 1.00 mm PTH, 6 x 0.30 mm vias, 4 x 3.20 mm NPTH

`fabrication/rev_b_validation.json` records the CAD version and SHA-256 hashes
of the source board and order artifacts. `build.py` regenerates these only after
ERC, DRC/parity and physical-pin tests pass. It does not authorize ordering.

## PCBWay/JLCPCB order settings

| Setting | Value |
|---|---|
| Board type | Single design |
| Layers | 2 |
| Dimensions | 68 x 66 mm |
| Material | FR-4 |
| Thickness | 1.6 mm |
| Copper weight | 1 oz |
| Minimum track / spacing | 0.30 / 0.20 mm or better |
| Solder mask | Any color; green is the baseline |
| Silkscreen | White |
| Surface finish | Lead-free HASL or ENIG |
| Via treatment | Tented is acceptable |
| Castellated holes | No |
| Edge plating | No |
| Impedance control | No |
| Assembly | No; hand assemble sockets and capacitors |

The four 3.20 mm mounting holes are intentionally non-plated. The ESP32 Wi-Fi
antenna region is a rule-enforced copper keepout on both layers.

## Package contents

The order archive contains front/back copper, mask, and silkscreen Gerbers;
the board outline; separate plated and non-plated Excellon drill files; and the
KiCad Gerber job file. The human-readable drill maps, statistics, IPC-D-356
netlist, and validation reports remain next to the source but are intentionally
excluded from the upload archive to avoid confusing automated fab ingestion.

## Assembly orientation

- ESP32 USB-C connector faces the carrier's `USB / POWER` edge.
- ESP32 PCB antenna faces the `WI-FI ANTENNA - NO COPPER` edge.
- CC1101 antenna connector faces the `433 MHz ANTENNA ->` edge.
- Install C1 and C2 on the carrier underside.
- CC1101 VCC is **3.3 V only**. Never connect it to VIN or USB 5 V.

Before populating a received board, perform the continuity and power checks in
`PREORDER_CHECKLIST.md`.
