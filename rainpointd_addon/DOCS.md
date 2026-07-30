# RainPoint Local Gateway

This experimental app runs the read-only `rainpointd` API used by the
**RainPoint Local** Home Assistant integration.

## Current behavior

Version 0.1.0 replays captured, synthetic device observations. It does not
connect to the RainPoint hub, the internet, or RF hardware. Every HTTP POST
request is rejected.

Installing this app does not make the physical irrigation system work offline.
Its purpose is to validate the persistent gateway-to-Home-Assistant boundary
before adding a receive-only 433 MHz transport.

## Configuration

### Replay interval

Number of seconds between fixture observations. The default is 5 seconds.

## Home Assistant integration

The app exposes its read-only API on TCP port 8787. Configure the
**RainPoint Local** integration with:

- Host: the IP address of the Home Assistant host
- Port: `8787`

The integration will create simulated soil-moisture, battery, signal, valve
status, water-usage, and watering-status entities.

## Safety

This release has no RF transmitter, cloud transport, valve entity, or control
API. It cannot operate the physical valve.
