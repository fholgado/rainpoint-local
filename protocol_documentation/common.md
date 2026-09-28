# Common RainPoint RF protocol

These rules apply to the tested HCS02x sensors and HTV145/HTV405 valves unless
a device file explicitly overrides them.

## Radio layer

| Property | Current definition |
|---|---|
| Band | 433/434 MHz ISM |
| Modulation | 2-FSK, PCM |
| Symbol period | 50 microseconds (20 ksymbol/s) |
| Sync word | `79 f4 88 2f 28` |
| Normalized frame | 38 bytes / 304 payload bits after wake-up preamble |
| Observed wake-up lengths | 320, 1,200, and 2,400 symbols |
| Average tone separation | Approximately 80 kHz (about +/-40 kHz deviation) |
| Ordinary receive bandwidth | 203.125 kHz is the conservative validated CC1101 setting |

The two recurring carrier groups are approximately 433.14 MHz and 434.24 MHz,
about 1.1 MHz apart. Exact carriers can be association-profile-specific. A
broad discovery capture uses 2.0 Msps centered at 433.7 MHz; observed energy
spans roughly 433.08--434.38 MHz.

An `rtl_433` flex decoder for normalized frames is:

```text
n=RainPoint,m=FSK_PCM,s=50,l=50,r=50000,bits>=620,match={40}79f4882f28
```

## Frame representations

There is one radio protocol with two representations. Existing runtime codecs
and fixture offsets use the **normalized 38-byte capture** `N`. Stock firmware
uses a **32-byte native payload** `P` after hardware sync `f3 e9 10 5e`.
The normalized view starts one bit before that hardware sync:

```text
P[i] = ((N[i + 4] << 1) | (N[i + 5] >> 7)) & 0xff   # i = 0..31
```

The native envelope is:

| Native offset | Meaning |
| --- | --- |
| `P[0]` | Header `51` |
| `P[1..4]`, `P[5..8]` | Association identities; roles depend on direction/family |
| `P[9] & 0x3f` | Full six-bit phase/sequence |
| `P[10] & 0x7f` | Command family |
| `P[10] & 0x80` | Response flag for the captured request/reply families |
| `P[11] & 0x1f` | Declared data length, at most 20 bytes in this envelope |
| `P[12..]` | Command-specific data, followed by padding |

Upper bits of `P[9]` and `P[11]` are not universally defined. A response flag
does not establish success or identify the sender: devices also answer
gateway-originated requests. Match association, full phase, command and
command-specific result/state. The normalized five-bit field alone is not the
whole phase: `phase = ((N[13] & 31) << 1) | (N[14] >> 7)`.

The historical normalized layout remains:

```text
offset  length  meaning
0       5       sync: 79 f4 88 2f 28
5       4       endpoint A
9       4       endpoint B
13      23      message body
36      2       integrity trailer
```

Endpoint A and endpoint B are protocol roles, not universal source and
destination fields. Their direction reverses in several acknowledgements. A
paired endpoint is commonly the corresponding factory endpoint with bit `0x80`
set in its first byte, but each device definition states the validated rule.

Integers are little-endian unless stated otherwise. Unqualified `frame` offsets
in device documents mean normalized `N`; native offsets are explicitly `P`.
This interpretation does not change the proven wire bytes, radio settings or
runtime framing. The legacy capture window omits the final physical CRC bit;
do not construct a new hardware trailer merely by shifting it.

See the [stock/capture boundary evidence](../research/STOCK_HUB_VALVE_STATE_TRACE.md)
and [cross-device pairing comparison](../research/PAIRING_NATIVE_COMPARISON.md).

## Integrity trailer

Compute CRC-CCITT over bytes `0..35`, initial value `0x0000`, then XOR the
received two-byte trailer. Every accepted frame seen so far produces one of
these legacy residues:

```text
0xc713
0x4f03
```

Both arise from native CRC-CCITT seeded `0xa8a8` over the 32-byte payload.
The old window includes the last payload bit in its apparent trailer and
retains only 15 hardware CRC bits. Changing just the legacy residue can change
that last payload bit; the residues are not two proven device-specific CRC keys.
The native interpretation matches 516 valid public fixture frames' observable
CRC bits, not 516 independent trials. See the
[radio boundary evidence](../research/STOCK_HUB_RADIO_PATH_TRACE.md).

Transmitters must retain the bytes/residue proven by the association profile
and captured transcript until the complete physical tail is qualified. Never
select a residue by trial and error while controlling a valve.

## Association selectors and carriers

An association can assign a radio selector used to derive a routine carrier.
For HCS02x sensors, the validated mapping is:

```text
frequency_hz = 433031500 + selector * 110000
```

Selectors are association parameters. They may be shared by multiple devices
and are not equivalent to the app's Device Address or to a unique device slot.
Valve profiles use their own captured carrier/selector combinations as defined
in their device files.

## CC1101 receive profile

The validated single-radio receive profile uses:

| Register | Value | Meaning |
|---|---:|---|
| `MDMCFG4` | `0x89` | 203.125 kHz RX bandwidth |
| `MDMCFG3` | `0x93` | approximately 20 ksymbol/s |
| `MDMCFG2` | `0x02` | 2-FSK, no hardware sync qualification |
| `DEVIATN` | `0x45` | approximately 40 kHz deviation |
| `FREQ2..0` | `10 a8 c3` | lower receive base |
| `MDMCFG1` | channel exponent 1 | selector spacing support |
| `MDMCFG0` | `0xf8` | channel spacing mantissa |
| `PKTLEN` | `0x24` | 36 bytes after the two sync bytes handled in software |
| `PKTCTRL0` | `0x00` | fixed packet mode, no hardware CRC |

The gateway retunes between association channels. Receiver RSSI is local
metadata measured by the receiving radio; it is not a field transmitted by
the RainPoint device.

## State and command invariants

- Pairing phases and incoming report phases do not authenticate the next local
  valve-control counter. The stock hub can use a shared generator for its own
  controls and configuration notifications; do not assume each traffic family
  has an independent stock generator.
- A valve command counter is advanced only by its authenticated command
  response, never by periodic telemetry.
- Routine device reports may require an acknowledgement to keep the device
  associated and reporting.
- Exactly one custom radio node owns each device's acknowledgement or control
  assignment. Other nodes may receive and forward duplicates but must not
  transmit competing replies.
- A command request remains pending until a matching response arrives or its
  bounded retry policy fails. Home Assistant state is never inferred from the
  outbound request alone.

## Executable specification

The normative implementation is split by responsibility:

- `rainpointd_addon/rainpointd/rf.py`: normalization, integrity validation,
  telemetry decoding, and common RF helpers.
- `rainpointd_addon/rainpointd/pairing_protocol.py`: sensor enrollment.
- `rainpointd_addon/rainpointd/valve_protocol.py`: valve telemetry and control.
- `rainpointd_addon/rainpointd/valve_pairing_protocol.py`: valve enrollment.

Captured fixtures under [`research/fixtures/`](../research/fixtures/) freeze
the byte-level evidence used by those implementations.
