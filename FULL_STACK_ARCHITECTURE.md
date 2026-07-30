# RainPoint full local stack architecture

## Objective

Replace every cloud-dependent software function while preserving a reversible
migration path:

- receive soil-moisture and valve telemetry locally,
- control watering locally with hard safety limits,
- discover, pair, name, and forget devices without the HomGar app,
- retain device identity and configuration across Home Assistant restarts, and
- allow either the original hub or an open replacement gateway to provide the
  radio link.

The Home Assistant integration must not know which physical gateway is in use.
That boundary lets us deliver local telemetry first and replace the remaining
parts incrementally.

## Target shape

```text
HCS026 sensors      HTV145 valve
       \              /
        \-- 433 MHz --/
               |
      interchangeable radio backend
       - receive-only SDR
       - open CC1101 gateway
       - original hub emulator
       - custom original-hub firmware
               |
          rainpointd
   protocol + registry + safety
               |
      versioned local WebSocket/API
               |
   Home Assistant rainpoint_local
```

### Protocol core

A dependency-light library owns frame parsing and encoding. It should:

- preserve every raw frame alongside decoded values,
- distinguish observations from hypotheses,
- validate lengths, checksums, counters, and timestamps,
- expose typed device events rather than Home Assistant entities, and
- use captured fixtures as regression tests.

`rainpointd_addon/rainpoint_protocol.py` and
`rainpointd_addon/fixtures.json` are the beginning of this layer.

### Local gateway service (`rainpointd`)

The gateway service owns the radio timing and state that must survive a Home
Assistant restart:

- radio input/output adapters,
- device registry and capability model,
- learn/pairing sessions,
- command correlation and acknowledgements,
- replay/counter state if the protocol requires it,
- valve watchdogs and maximum run times,
- an append-only local event/audit log, and
- a versioned local WebSocket/REST API.

Home Assistant should not directly bit-bang a radio or own the valve watchdog.
It is a client of this service.

### Home Assistant integration (`rainpoint_local`)

The integration should provide:

- Config Flow and local gateway discovery,
- soil-moisture, battery, signal, and last-seen sensors,
- valve state and bounded-duration controls,
- diagnostic raw-frame/event information,
- repair warnings for stale or unreachable devices, and
- explicit learn, accept, rename, and forget actions.

It should work with a replay backend before any live RF hardware is attached.

## Interchangeable transport backends

| Backend | Local telemetry | Local control | Local pairing | Main tradeoff |
| --- | --- | --- | --- | --- |
| Replay fixtures | Yes, synthetic | Yes, synthetic | Synthetic | Development and tests only |
| Cloud observer | No | Existing cloud path | Existing app | Useful only as a temporary comparison oracle |
| RTL-SDR / `rtl_433` receive-only | Yes | No | Learn broadcasts only | Safest first genuinely local milestone |
| Open ESP32 + CC1101 gateway | Yes | Yes, after RF decoding | Yes, after handshake decoding | Cleanest long-term ownership; requires RF reverse engineering |
| Original hub + local service emulator | Yes | Likely | Potentially | Reuses paired hardware but depends on TLS/auth/service emulation |
| Custom firmware on original hub | Yes | Yes | Yes | Elegant hardware reuse but highest brick/recovery effort |

The open CC1101 gateway should be the reference implementation. Supporting the
stock hub can remain a valuable compatibility backend rather than becoming a
prerequisite for the local integration.

## Pairing without the vendor app

“Pairing” needs two separate meanings:

1. **Registry enrollment:** learn a stable over-the-air device identity and add
   it to the local registry.
2. **RF association:** perform any bidirectional key, address, channel, or
   counter exchange required by the device.

Battery soil sensors may simply broadcast a stable identity. If confirmed, the
local workflow is a timed learn window: activate or refresh the sensor, show the
unknown device and its recent readings, then let the user accept and name it.
Forgetting it would remove the registry entry; it would not alter the sensor.

The valve is more likely to require a real association handshake. We should
capture one complete stock-hub pairing and unpairing sequence later, using a
spare or deliberately reset device rather than risking the working garden
setup. The registry should be able to retain:

- protocol/device ID and model,
- RF address/channel,
- capabilities,
- keys, counters, or session material if discovered,
- friendly name and area,
- last-seen and health information, and
- the raw evidence used to infer the record.

Local operations should be explicit:

- `start_learning(timeout)`
- `list_candidates()`
- `accept_device(candidate, name)`
- `rename_device(device_id, name)`
- `forget_device(device_id, local_only=true)`
- `factory_unpair(device_id)` only when the RF procedure is proven

Deleting a Home Assistant entity must never silently transmit a factory-reset or
unpair command.

## Phased migration

### Phase A — protocol core and simulator

Status: started.

- Keep adding labeled RF and application-layer fixtures.
- Build replayable device timelines.
- Specify the local event and command API.
- Exercise the future HA integration entirely from fixtures.

This work is safe while away because it cannot affect the garden.

### Phase B — receive-only local telemetry

This is the first true local Home Assistant milestone.

1. Add a 433 MHz receiver without changing the stock hub.
2. Capture HCS026 and HTV145 broadcasts.
3. Determine modulation, framing, identity, checksum, and report cadence.
4. Feed decoded events to `rainpointd`.
5. Run `rainpoint_local` beside the cloud integration in shadow mode.
6. Compare values, timestamps, missing reports, and battery status for at least
   one normal watering cycle and several days of sensor traffic.

The existing HomGar integration displaying data in HA is not itself local; it
remains a useful comparison oracle during this phase.

### Phase C — open registry and sensor enrollment

- Implement the timed learning workflow.
- Confirm stable identity after battery replacement and gateway restart.
- Support naming, area assignment, export, backup, and local forgetting.
- Keep the stock hub paired and operational.

### Phase D — valve protocol and bounded local control

- Capture stock-hub valve commands, acknowledgements, retries, and pairing.
- Reproduce only known frames, initially into a controlled test setup.
- Require a command ID and positive state acknowledgement.
- Enforce a conservative configured maximum and an independent absolute limit.
- Start the watchdog before transmitting open.
- Make close idempotent and retry it until idle is observed or a fault is raised.
- Keep manual valve operation and the stock path available during validation.

No arbitrary RF fuzzing should be performed against the installed valve.

### Phase E — fully local operation

- Move schedules to Home Assistant or the local gateway.
- Remove the vendor app from provisioning and daily operation.
- Block internet access for the RainPoint stack during a supervised test.
- Verify telemetry, watering, restart recovery, clock behavior, and failure
  handling.
- Retain a documented rollback until a full growing season or an agreed
  confidence period has passed.

## Valve safety contract

The gateway, not merely Home Assistant, must guarantee:

- fail-closed behavior,
- a user maximum run duration and a non-bypassable absolute maximum,
- automatic close after loss of the controlling client,
- confirmation from returned valve state rather than transmit success,
- repeated, idempotent close attempts,
- no open command without a running local watchdog,
- persistent audit records for open, close, timeout, and failed acknowledgement,
- safe startup after power loss with no restoration of an old open command.

Scheduling can live in Home Assistant, but this safety contract must continue to
work when Home Assistant is stopped.

## Choosing the final hardware path

### Prefer no firmware change first

An open replacement gateway is the lowest-risk route to full independence
because the stock hub remains untouched and available as a fallback. It also
gives us unrestricted local APIs and recovery tooling. The price is learning
the RF control and association protocol.

### Retain the stock hub through service emulation

This is attractive if its TLS validation and device authentication can be
reproduced locally. It preserves existing pairings and needs no extra radio
hardware. It may nevertheless require emulating several cloud services, time
and provisioning behavior, and possibly certificates or per-device
credentials. It should be treated as a transport adapter, not as the core
architecture.

### Flash the stock hub only with a recovery path

Custom firmware could produce the neatest single-box result, but only after:

1. identifying the MCU, flash, RF chipset, and test pads,
2. recording a read-only boot log,
3. checking secure boot and flash encryption,
4. producing and hash-verifying two independent flash dumps,
5. proving a physical recovery procedure, and
6. preserving RF calibration and device association data.

Firmware work should not begin on the only working irrigation hub. A second hub
is strongly preferred.

## Near-term implementation order

While the installed system must remain undisturbed:

1. define the gateway event/API schema,
2. scaffold `rainpointd` with replay transport,
3. scaffold the HA integration against replay,
4. continue passive network capture and history correlation, and
5. select and prepare receive-only RF hardware.

When someone is home:

1. attach the receiver and capture normal sensor reports,
2. identify stable device IDs and checksums,
3. validate local telemetry in shadow mode,
4. obtain a spare sensor/valve or hub for pairing captures, and
5. only then begin local transmit experiments.

## Definition of complete independence

The replacement is complete when a clean installation can, without HomGar
services or the vendor app:

- commission the local gateway,
- learn every supported sensor and valve,
- persist and back up its registry,
- report all telemetry locally,
- safely open and close a valve for bounded durations,
- recover safely across HA, gateway, network, and power failures, and
- restore the setup from documented local backups.
