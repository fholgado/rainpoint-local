# Stock radio profile and frame-boundary trace

Offline research, 2026-09-27. Baseline: retained stock **1.1.1040**, ESP32-S3,
HWG023WBRF-V2. Addresses are runtime virtual addresses in that image. No hub,
node, RF setting or runtime codec was changed. Status and prioritization belong
in [the roadmap](../PROJECT_ROADMAP.md), not this evidence note.

## Principal result: the normalized frame starts one bit early

**Static plus cross-device capture corroboration.** The stock packet-radio
tables select a four-byte hardware sync, **`f3 e9 10 5e`**, a **32-byte payload**
and hardware CRC-CCITT with seed **`a8a8`**. Our familiar 38-byte representation
starts one bit before that hardware sync. Consequently:

```text
hardware:    [32 sync bits][256 payload bits][16 CRC bits]
normalized: 0[32 sync bits][256 payload bits][15 CRC bits]
```

Both views contain 304 bits. The normalized view lacks the final hardware CRC
bit. Its five-byte `79 f4 88 2f 28` match spans the leading zero, all hardware
sync bits and the first seven bits of the stock payload header `51`.
This is a representation distinction, not evidence that existing reception or
transmission stopped working, nor a reason to change a proven live path.

For normalized bytes `n[0..37]`, all 32 native payload bytes are recoverable:

```text
p[i] = ((n[i + 4] << 1) & 255) | (n[i + 5] >> 7), i = 0..31
```

In particular, `p[31]` uses **bit 7 of `n[36]`**. What the normalized definition
calls its two-byte trailer therefore includes one payload bit and 15 CRC bits;
it is not simply the stock chip's 16-bit CRC.

This aligns with the independently traced stock header/valve analysis: internal
byte 9 is a six-bit sequence field, while the normalized view distributes it
across bytes. Fields that look like packed or split values can instead be
ordinary native byte fields. Do not generalize every old unknown bit from this
fact; each field still needs its owning serializer and capture correlation.

### CRC evidence and important residue caveat

An offline scan of `research/fixtures/*.json` found **518 unique** complete
38-byte frames with the normalized prefix. **516** match the upper 15 bits of
CRC-CCITT over the recovered 32 bytes, seed `a8a8`. Matching examples include
both valves and HCS026 sensor pairing, reports and ACKs. The two exceptions
are retained deliberately:

- `htv145_stock_command_counter_20260824.json`: explicitly rejected
  `corrupted_response_candidate`.
- `htv145_hardware_clocked_configuration_calibration_20260904.json`: the
  arbitrary-address `deadc0de`/`f00dcafe` transmitter calibration, not a
  stock-valid protocol exchange. Exact RF recovery did not establish protocol
  checksum validity.

The match does **not** independently observe the missing final CRC bit. It
verifies all observable CRC bits; computing the omitted bit is a prediction.
The corpus includes generated local frames as well as stock captures, so 516
is not a count of independent stock experiments.

Synthetic packets explain both existing normalized residues using one hardware
CRC configuration: construct `f3e9105e + payload32 + CRC(payload32, a8a8)` and
shift that 304-bit value right by one. The legacy checksum calculation over
the resulting first 36 bytes gives residue `4f03` when the hardware CRC's least
significant bit is zero, and `c713` when it is one.

**Neither residue is inherently invalid.** Holding normalized bytes 0–35 fixed
and choosing the other residue changes the recovered final payload bit and
still yields a valid observable hardware CRC prefix. The difference `8810`
contains that payload bit and the corresponding checksum adjustment. Therefore
the old association-specific residue practice is not evidence of two hardware
CRC seeds, and this result does not justify replacing it blindly. First map
the last payload byte's meaning and verify complete on-air frames. Existing
successful profiles remain frozen.

Reproducible, firmware-independent checks:

```sh
python3 -m unittest tests.test_stock_radio_frame_reference -v
```

The three tests cover the public corpus with explicit negative controls, 100
deterministic synthetic packets exercising both residues, and the final-payload
bit caveat. These are research oracles, not a new production codec.

## Static profile evidence

The six-bank loader `0x4205DDF4` writes bytes through register wrapper
`0x42015BF0`. The following baseband table addresses belong to separate
branches; the labels here are descriptive, not recovered symbol names:

| Baseband address | Load path | Preamble register count |
| --- | --- | ---: |
| `0x3C149734` | OOK function `0x42015E90` | 8 |
| `0x3C149798` | Normal `0x42015F9C`, context mode 0 plus nonzero helper `0x42045910` | 1250 |
| `0x3C149860` | Normal mode 0 alternate / mode 2, and alternate-loader branches | 40 |
| `0x3C1496D0` | Normal mode 1 | 40 |
| `0x3C1497FC` | Alternate `0x42016148`, selected argument-1 branches | 300 |
| `0x3C14966C` | Alternate mode 1 / argument 1 | 300 |

All five non-OOK tables above have register `38=22`, `3C=06`, `45=00`,
`46=1F`, `4C=01`, `4D=A8`, `4E=A8`. Registers `41..44` contain
`5E 10 E9 F3`; `3D..40` are zero. The sync uses the high four registers.
`38` selects packet mode and eight-bit preamble units, so the 40/300 counts
correspond to 320/2400 symbols. Fixed payload length is register value plus
one: **`1F` means 32 bytes, not 31**. `4C=01` selects whole-payload CCITT-16
without inversion, high byte first. These meanings are manufacturer-defined.
[HOPERF AN192, pp. 9–13 and Table 3](https://hoperf.com/uploads/AN192_CMT2300A_Register_Description_EN_V0.6_20250624_1751591473.pdf).

The constants corroborate observed short and long wakes, but the table alone
does not establish the active profile of every captured exchange. In
particular, the 1250-unit branch is not evidence that ordinary valve pairing
needs a 10,000-symbol wake. Overrides and branch applicability matter.

### OOK is a separate branch, not the normal packet profile

At `0x42016AE8`, a branch checks input bytes `A5 6C` and length 11 before
calling `0x42015E90` at `0x42016B35`. Its cleanup routine `0x42016BDC` restores
the normal loader at `0x42016C12`. Normal initialization `0x420150E0` also
calls `0x42015F9C` at `0x420150F4`.

This separates the OOK table previously discovered from the normal packet
tables. It does not identify the retail devices using the A5/6C branch or prove
that every shared-image feature is enabled on this board.

Normal profile selection reads context `0x3FCA4B90[0]`. Initialization
`0x42015B50` stores the return of `0x42016D10` there. That helper reads candidate
GPIOs 38 and 37. Thus the mode is hardware-input-dependent in this code path,
not automatically the app's channel choice. Actual board levels and physical
wiring were not measured.

## Channel selection is an explicit transformation

Wrapper `0x42015F60` truncates its caller's selector to a byte, subtracts one,
and calls `0x4205DD3C`. That setter:

1. Exchanges index 1 and index 14; other indices are unchanged.
2. Adds 66 if context mode `0x3FCA4B90[0]` equals 1.
3. Writes the resulting byte to register `0x63` at `0x4205DD66`.

Helper `0x4205DD6C` writes its byte argument to register `0x64`. Normal-loader
branches supply 44, 32 or 88 (`0x42016035`, `0x4201607F`, `0x420160C9`);
the alternate loader has corresponding calls. The manufacturer identifies
`63` as hopping-channel index and `64` as hopping step. Its documented formula
adds `2.5 kHz × step × index` to the configured base frequency; step 44 thus
corresponds to 110 kHz increments. This is not a recovered absolute base
frequency or proof that app Device Address equals either index.
[HOPERF AN197, pp. 3–5](https://hoperf.com/uploads/AN197-CMT2300A-CMT2119B-CMT2219B_Fast_Manual_Frequemcy_Hopping_EN_V0.8_1757312889.pdf).

RX setup uses context byte +20 at `0x420164A9`; TX setup uses +8 at
`0x42016718`, both through the selector wrapper. These separate sources must
be traced to their application owners before interpreting app `ReciCH` or
changing local assignment logic. They are not interchangeable with factory
sweep counters or command sequences.

## Internal buffer to FIFO

`0x42016A28` zeros a 32-byte staging area at `0x3FCA4BDC`, then copies the
caller's internal frame. It extracts:

| Internal byte / expression | Destination / check |
| --- | --- |
| byte 9, low six bits | context +11, at `0x42016A50..59` |
| inverted byte 10, bit 7 | context +9, at `0x42016A5C..67` |
| byte 11, low five bits, plus 12 | expected caller length, at `0x42016A6A..75` |

Only matching lengths proceed. `0x420169DC` passes staging address and that
length to `0x420163E4`, which records TX pointer/length and enters radio state
5. Dispatch `0x4201641F..22` reaches the TX branch at `0x42016705`. Context
+9 may trigger alternate-profile loading; then TX selector +8 is applied.
At `0x420167AF..B8`, the saved pointer and length reach FIFO wrapper
`0x42015C10`, then FIFO writer `0x42016F48`.

This is a bounded serializer-to-FIFO seam and a corroboration of the six-bit
internal sequence field. It is not a full proof of zero-padding behavior in
all FIFO lengths: software length, staged capacity and hardware fixed length
are distinct. The normalized trailer can carry the final payload bit, so no
all-zero-padding assumption should be made from bytes 0–35 alone.

## Reproduction and boundaries

Analysis used the separately installed official ESP32-S3 decoder described in
[tool qualification](STOCK_HUB_DECODER_TOOLING.md), with the retained private
`analysis/rainpoint-stock-irom.elf` and `app-ota_1.bin`. Exact entry points and
branch targets were decoded independently where padding confused linear
output. Table offsets use the image's DROM load address, not flash addresses.
Raw firmware, table dumps and disassembly stay private; only necessary
constants, conclusions and public-fixture tests appear here.

Useful follow-through is a reviewed native/normalized codec boundary, stock
field serializers, and captured full-CRC-bit validation. It is not a live
retune, experiment, hardware port, replacement of working packet builders, or
claim that every previous pairing failure is now explained. Preserve existing
pairing prefixes until byte-exact tests and controlled qualification support
any implementation change.
