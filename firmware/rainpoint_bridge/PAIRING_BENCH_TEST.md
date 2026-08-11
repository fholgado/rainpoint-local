# Sensor B pairing bench test

This procedure validates the first real ESP32/CC1101 transmission against the
independent RTL-SDR before attempting enrollment. It applies only to Test
Sensor B factory endpoint `15a98024`; it cannot control a valve.

## Hardware

- ESP32 development board powered by USB
- One 433 MHz CC1101 module with its antenna attached
- 100 nF ceramic capacitor at the CC1101 VCC/GND pins
- Existing RTL-SDR running independently as the reference receiver

Wire the primary module exactly as shown in `README.md`. GDO0 to ESP32 GPIO26
is mandatory for TX. Use 3.3 V only. Attach the antenna before powering the
radio.

The implementation follows the [TI CC1101 datasheet](https://www.ti.com/lit/ds/symlink/cc1101.pdf):
asynchronous serial mode disables FIFO packet handling, samples TX data from
GDO0, and requires the MCU bit timing to remain within one eighth of the
configured bit period.

Keep Sensor B batteries removed until the receive path and two probe signals
have been checked. Leave the working irrigation valves alone. The stock
RainPoint gateway may stay online, but do not put it into app pairing mode.

## 1. Build, flash, and inspect boot

```sh
python3 -m platformio run --project-dir firmware/rainpoint_bridge \
  --environment esp32dev_single --target upload
python3 -m platformio device monitor --baud 115200
```

Expect a `boot` record with `mode` set to `pairing_tx_bench`, followed by
`radio_ready` and healthy configuration records. Run `pairing_status`; it must
say `state: disarmed` and `tx_armed: false`.

## 2. Verify receive before transmitting

With the board near the garden, confirm that ordinary `rainpoint_rf` records
arrive. Do not continue if `radio_error`, `fatal`, or a configuration mismatch
appears.

## 3. Capture two deliberate probes

Start a short broad RTL-SDR capture covering the known reply frequencies. Then
send these commands one at a time:

```text
pairing_probe_b 1 15a98024
pairing_probe_b 2 15a98024
```

Each command makes one approximately 31.2 ms, 0 dBm transmission. Both current
steps are near 433.4715 MHz. The serial response must report
`success:true`.

Before involving the sensor, analyze the SDR recording and confirm:

- 20,000 symbols/s and approximately +/-40 kHz deviation
- a 320-symbol alternating wake that starts low, without inverting the frame
- the correct 38-byte frame and ordinary trailer
- center frequency close enough to the captured stock reply
- reply start approximately 65 ms after the triggering sensor frame ends

If the decoded bits are inverted, run `pairing_invert on` and repeat both
probes. If the carrier is offset, set a correction between -100,000 and +100,000
Hz with `pairing_offset_hz N`, then repeat. Calibrate each radio node against
the same receiver used for the stock-gateway reference because module crystal
error is hardware-specific. These settings are volatile and
reset on reboot.

If range is still suspect, select a TI-supported 433 MHz bench level with
`pairing_power_dbm 0`, `5`, `7`, or `10`. Start at 0 dBm and increase only
between disarmed attempts.

## 4. Attempt Sensor B enrollment

Start the independent SDR capture first. Then enter:

```text
pairing_clock_local 20260811145556
pairing_arm_b 15a98024
```

Replace the example with the target RainPoint gateway clock in
`YYYYMMDDhhmmss` form. In the first successful local test that clock was four
minutes ahead of the Mac, so the supplied value was Mac local time plus four
minutes. This is an observed installation-specific correction, not a protocol
constant. The first reply is rebuilt with the packed value and a regenerated
trailer; arming fails closed unless the time has been supplied since boot.

Confirm `tx_armed:true`, install Sensor B batteries, and press its pairing
button if it does not announce automatically. The coordinator should report
three successful replies in this order:

1. factory message 1
2. paired message 1
3. paired data message 2
Success is `state: completed` with `completed_steps:3`, followed by ordinary
reports from paired endpoint `95a98024`. The sensor's blue indication is useful
corroboration but the RF frames are authoritative.

Enter `pairing_cancel` at any time to stop. The session also fails closed after
two minutes, an unexpected future trigger, transmission failure, or loss of a
gateway connection that was active when it was armed. Rebooting always returns
to disarmed state.

## 5. Preserve evidence

Keep the SDR capture and serial log from every attempt, including failures.
Record the applied frequency offset, polarity, antenna separation, and whether
each reply decoded. Do not begin valve transmission work until this fixed
Sensor B sequence succeeds end to end.
