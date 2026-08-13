# Revision A PCBWay assembly quote

Quote this as a **turnkey mixed assembly**. PCBWay supplies and installs the
three through-hole female sockets and the two bottom-side 0805 capacitors.

Do not source or install the ESP32 development board or CC1101 radio module.
Those are removable customer-installed modules that plug into J1/J2 and J3
after the completed carrier has passed continuity and power checks.

## Quote settings

- PCB quantity: 5
- Assembly quantity: 5
- Assembly type: mixed SMT and through-hole
- Board type: single pieces
- Assembly sides: both sides
- Parts sourcing: turnkey / PCBWay supplies parts
- Sensitive parts: no
- Accept Chinese alternatives/substitutes: yes, subject to the BOM constraints
- Number of unique parts: 4
- Number of SMD parts per PCB: 2
- Number of BGA/QFP parts per PCB: 0
- Number of through-hole parts per PCB: 3
- Conformal coating: no
- Functional testing: no
- Stencil: assembly-required stencil only; do not order a separate customer stencil

For **Detailed information of assembly**, use:

> Turnkey mixed assembly. Populate J1, J2 and J3 on top; C1 and C2 on bottom.
> Do not source or install the ESP32 or CC1101 modules. J1/J2 are two separate
> 1x15 female sockets. Substitutions are permitted only within the mechanical
> and electrical constraints in the supplied BOM and assembly instructions.

## Placement and orientation

- J1, J2 and J3 are fitted on the **top** side.
- C1 and C2 are fitted on the **bottom** side.
- All three connectors are vertical, unshrouded female sockets.
- J1 and J2 are separate 1x15 sockets, not one 2x15 connector.
- J3 is one 2x4 socket with 2.54 mm pitch in both axes.
- Connector pin 1 is identified by the rectangular pad and silkscreen marking.
- C1 and C2 are non-polar ceramic capacitors.

## Acceptable substitutions

PCBWay may substitute mechanically identical connector parts, but it must
honor the pitch, row count, body height, vertical orientation, female contact,
post compatibility and PCB-hole constraints recorded in the BOM. Generic
capacitor substitutions are acceptable when their value, dielectric, voltage
rating and 0805 package meet or exceed the BOM.

## Files

- `pcbway_bom.csv`: turnkey mixed-assembly BOM with preferred parts.
- `pcbway_cpl.csv`: bottom-side SMT centroid data for C1 and C2.
- `rainpoint_carrier-B_Paste.gbp`: bottom solder-paste Gerber.
- The board Gerbers and drill files are in the companion PCBA Gerber ZIP.

PCBWay's centroid requirement applies to surface-mount parts. The through-hole
socket locations and orientations are unambiguous in the fabrication data,
silkscreen and assembly preview.
