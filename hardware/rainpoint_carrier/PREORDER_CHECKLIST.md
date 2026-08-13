# Revision A preorder checklist

Do not upload fabrication files until every required item is checked against
the same physical modules that will be installed.

## Mechanical fit

- [ ] Print `../../output/pdf/rainpoint_carrier_rev_a_fit_check.pdf` at
      **Actual Size / 100%**, with Fit, Shrink, and Scale to printable area
      disabled.
- [ ] Confirm the 100 mm calibration ruler measures exactly 100 mm on paper.
- [ ] Confirm the 1-inch calibration square measures exactly 25.4 x 25.4 mm.
- [ ] If either calibration mark is wrong, correct printer scaling before
      judging module fit.
- [ ] Confirm the ELEGOO board has 15 pins on each side (30 pins total).
- [ ] Confirm the ELEGOO header-row center spacing matches the drawing.
- [ ] Confirm all 15 pins on both sides fall on the printed pad centers, with
      no carrier socket positions extending into the Wi-Fi antenna end.
- [ ] Confirm the USB-C receptacle faces and clears the bottom carrier edge.
- [ ] Confirm the CC1101 module is approximately 28 x 15 mm.
- [ ] Confirm its connector is 2x4 at 2.54 mm pitch.
- [ ] Confirm all eight radio pins fall on the printed pad centers.
- [ ] Confirm the radio antenna connector clears the right carrier edge and the
      selected antenna can be installed without fouling the enclosure.

## Pin orientation

- [ ] With the module oriented as drawn, CC1101 pin 1 is labeled GND.
- [ ] Pin 2 is VCC and the module is explicitly rated for 3.3 V operation.
- [ ] Pins 3 through 8 read GDO0, CSN, SCK, MOSI, MISO/GDO1, GDO2 in order.
- [ ] The ESP32 pin labels match `pinout.csv` on the actual board.
- [ ] A continuity review confirms there is no connection from USB 5 V/VIN to
      CC1101 VCC.

## Layout and fabrication review

- [ ] KiCad electrical-rules and design-rules checks pass with no unexplained
      errors.
- [ ] ESP32 PCB-antenna keepout exists on both copper layers.
- [ ] C1 and C2 are adjacent to the CC1101 VCC/GND socket pins.
- [ ] Silkscreen clearly marks ESP32 orientation, radio orientation, pin 1,
      `3V3 ONLY`, USB, Wi-Fi antenna, and 433 MHz antenna.
- [ ] Gerbers and drill files have been opened in an independent viewer.
- [ ] Board outline is 68 x 66 mm and all four mounting holes are NPTH.

## First-board power-up

- [ ] Install the ESP32 only and verify normal USB boot.
- [ ] Measure approximately 3.3 V, with correct polarity, at the empty radio
      socket.
- [ ] Remove USB power before inserting the CC1101.
- [ ] Attach the correct 433 MHz antenna before enabling transmit tests.
- [ ] Run the firmware radio self-test and compare reception with the known-good
      breadboard node.
