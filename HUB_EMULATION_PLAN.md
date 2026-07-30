# Original-hub local emulation plan

Goal: keep the HWG023WBRF-V2 and its existing RF pairings while replacing
HomGar internet services with local services.

## Current evidence

- The hub exposes no confirmed local listening service in normal mode.
- It initiates a persistent TLS-wrapped MQTT connection on TCP 1883.
- It initiates short TLS 1.2 transactions to a HomGar service on TCP 1446.
- Soil and valve status appear inside Aliyun-style MQTT envelopes.
- Valve start and stop produce repeatable cloud-to-hub and hub-to-cloud packet
  size sequences.
- The original hub has distinct 433 MHz transmit and receive paths.

## Work permitted while unattended

These tasks do not alter hub behavior:

1. Passive UDM capture of existing hub traffic.
2. Home Assistant Recorder analysis of decoded valve and soil entities.
3. Offline decoding and regression tests.
4. Public FCC/app/source research.
5. Local implementation of a mock broker/API using synthetic fixtures only.

Do not perform remotely:

- Wi-Fi deauthentication or reconnect
- DNS, NAT, firewall, VLAN, or DHCP changes
- certificate interception
- provisioning-mode reset
- firmware update, flash dump, or serial access
- device re-pairing

## Later phase 1: identify every endpoint

When someone is present:

1. Begin simultaneous UDM and Home Assistant capture.
2. Briefly block only the hub's internet access, then restore it.
3. Record DNS, TCP, and complete TLS handshakes during reconnection.
4. Confirm broker hostname, secondary hostname, TLS versions, certificate
   chains, connection order, retry intervals, and recovery behavior.
5. Verify scheduled watering remains intact after reconnection.

No traffic redirection occurs in this phase.

## Later phase 2: certificate-validation test

Use an isolated VLAN and a reversible per-device redirect:

1. Redirect one HomGar hostname/port to a local TLS listener.
2. Present a controlled non-HomGar certificate.
3. Observe whether the hub rejects before application data.
4. Remove the redirect immediately and verify cloud reconnection.

Outcomes:

- **Certificate accepted:** implement the local endpoint directly.
- **Certificate rejected:** obtain firmware or trust-store access before
  attempting further interception.

## Later phase 3: receive-only local emulator

Before local control:

1. Implement a TLS endpoint and MQTT broker matching the captured connection.
2. Accept hub authentication without publishing commands.
3. Store raw sensor/status messages locally.
4. Decode HCS026FRF moisture and HTV145FRF state.
5. Expose read-only Home Assistant sensor entities.
6. Run cloud and local observations side-by-side to verify parity.

## Later phase 4: controlled valve operation

Only after read-only operation is stable:

1. Reproduce a 60-second valve command.
2. Require a maximum-duration guard.
3. Confirm open state from a returned HTV145FRF frame.
4. Publish close and confirm idle state.
5. Add a local watchdog that sends close after timeout.
6. Retain a reversible route back to the HomGar services during testing.

## Firmware branch if TLS blocks emulation

The hub uses an Espressif MAC allocation, but the exact MCU and flash-security
configuration are not yet proven. With physical access:

1. Inspect FCC photos and the board for labeled UART/test pads.
2. Identify MCU, external flash, and 433 MHz RF chipset.
3. Attempt a read-only serial boot log.
4. Determine whether secure boot or flash encryption is enabled.
5. If flash is readable, preserve two independent dumps and compare hashes.
6. Analyze NVS for hostnames, device credentials, CA certificates, and RF
   configuration.

Do not write or patch firmware until a recovery path and verified dump exist.

## Success definition

The hub is considered locally integrated when:

- internet access can be removed,
- all four soil sensors continue updating locally,
- valve open and close work with bounded durations,
- current state is confirmed from RF feedback,
- Home Assistant restarts do not leave watering active, and
- removing the local emulator does not destroy RF pairings.
