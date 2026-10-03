# Rev A defect and salvage

**Do not plug a CC1101 directly into Rev A. Disconnect USB before any rework.**
The module in the September 14 test has pins 1/2 at the top and 7/8 at the
bottom (top view, ESP32 USB down, radio antenna right). Rev A reverses the four
rows but not the columns. Pin 1 therefore reaches GPIO19 instead of ground;
pin 2 reaches GPIO25 instead of 3V3. This matches the measured continuity and
`cc1101_not_found` startup error. Whether either module was damaged is unknown.

## Why the checks missed it

The August 12 coordinate table used a bottom-left origin but placed 1/2 at the
lowest Y. The generator and manufacturing files copied it, contradicting the
correct README pinout. Hole-fit checks cannot distinguish a row reversal; ERC
and DRC only validate the incorrectly numbered footprint against the schematic.
Physical pin-orientation acceptance was never completed. Rev B reverses the
radio rows, reroutes their nets and labels each row. Artifact-level regression
tests independently compare physical pad locations with the photographed module.

## Salvage without trace cutting

Remove the radio from its carrier socket. Use eight short jumper wires or a
small crossover adapter between the empty socket and the radio's male pins.
Do not connect the radio directly at the same time. A male-to-female harness
fits female carrier sockets and male radio headers; adapt to your actual headers.
Keep the radio supported, insulated and away from exposed solder joints.

Identify socket holes by position, NOT the module's numbers or an underside
view. With the carrier TOP facing you, USB down, antenna outline right:

| Rev A socket position | Existing net | Wire to actual radio pin |
|---|---|---|
| Top left | GPIO19 / MISO | 7 |
| Top right | GPIO25 / GDO2 | 8 |
| Second row left | GPIO18 / SCK | 5 |
| Second row right | GPIO23 / MOSI | 6 |
| Third row left | GPIO26 / GDO0 | 3 |
| Third row right | GPIO27 / CSN | 4 |
| Bottom left (square pad) | GND | 1 |
| Bottom right | 3V3 | 2 |

Do not rotate the radio 180 degrees: that also swaps the columns. Do not try
to fix this by remapping firmware GPIOs; VCC/GND are misplaced too. The capacitors
are still on the carrier's proper 3V3/GND nets, but a harness lengthens the supply
path. Keep wires short; a successful bench test does not qualify permanent RF
performance or outdoor use. No trace-cutting recipe is qualified.

## What these boards can verify

1. **Mechanical, unpowered:** ESP32/socket fit and insertion, radio clearance,
   USB access, mounting holes, standoffs and enclosure dimensions. Do not treat
   the Rev A radio orientation mark as electrical approval.
2. **Continuity, unpowered, modules removed:** meter every socket-to-ESP32 net
   against the table above and `pinout.csv`; test the completed harness separately.
   Check that neither the socket nor capacitors short 3V3 to ground. A capacitor
   charging transient is not a sustained short. Continuity does not verify
   capacitance or power quality.
3. **Power, radio removed:** after continuity passes, fit the ESP32, power via
   USB, and measure about +3.3 V between the Rev A bottom-right socket hole and
   bottom-left GND. Use insulated probes carefully; never continuity mode on a
   powered board. Unplug again before attaching the harness or radio.
4. **Radio via checked harness:** attach its antenna, power up, require
   `radio_ready` without initialization failure, gateway connection and fresh
   received packets. Keep production ACK ownership and firmware unchanged.
5. **Later functional checks:** stability on USB power, coverage and a specifically
   authorized pairing test with a test sensor. These cannot certify direct-plug
   Rev B until a corrected board is manufactured and metered.

For fault isolation, a known-good direct ESP32-to-radio jumper setup bypasses
the carrier. Test a spare radio only after power/mapping checks pass. Photograph
and label any reworked board **REV A - CROSSOVER REQUIRED** so it is never reused
as a direct-plug carrier. No power or RF tests are implied by this document.
