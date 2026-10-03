# Stock hub firmware: first offline analysis

Scope: privately retained HWG023WBRF-V2 flash backup, read twice on
2026-09-27. Both 8 MiB reads match. No firmware, eFuses, configuration, pairing,
or RF behavior was changed for this analysis. The hub was returned to normal
boot after readout. Raw firmware, configuration partitions, extracted images,
and analysis artifacts remain in Git-ignored `captures/stock-hub-firmware/`.

This is evidence, not a completed recovery implementation or a new checklist.
Current work stays in [the roadmap](../PROJECT_ROADMAP.md). Format definitions
and primary-source citations are in [the reference note](STOCK_HUB_FIRMWARE_REFERENCES.md).

## Validated image inventory

The private readout manifest records `secure_boot_enabled=false` and
`flash_encryption_enabled=false`. This is a readout-time security snapshot,
not a demonstrated restore or a backup of eFuses; recheck before any write.

The partition table is at flash `0xA000`, not the usual default `0x8000`.

| Partition | Flash offset | Allocated size |
| --- | --- | --- |
| NVS | `0xB000` | 200 KiB |
| OTA selection | `0x3D000` | 8 KiB |
| `ota_0` | `0x40000` | 3 MiB |
| `ota_1` | `0x340000` | 3 MiB |
| FAT storage | `0x640000` | 1 MiB |
| Vendor storage | `0x7F8000` | 32 KiB |

Both application images pass esptool 4.11.0's image checksum and appended hash
validation. Both identify ESP32-S3, project `HWG009WB`, ESP-IDF
`v5.1.6-dirty`. The internal project name is not a retail-model identification.

| Slot | Version | Build time in descriptor | Validated image SHA-256 |
| --- | --- | --- | --- |
| `ota_0` | 1.1.1032 | 2025-09-16 14:14:45 | `5d97e4b2c3ec7554fa89627c3a7e9727518e9d1cf02cac1f53d4076bb9fca7ec` |
| `ota_1` | 1.1.1040 | 2026-05-21 18:40:46 | `e596ca60c238ccf639a896c6489014746a42387d000751656e345b7e3f5a041f` |

These are esptool's validated image hashes, not hashes of the padded 3 MiB
partition files or the original ELF. OTA selection records contain sequence
1/state 2 and sequence 2/state 2. Both sequence CRCs match Espressif's algorithm;
state 2 is valid. Standard IDF rules select sequence 2, hence `ota_1` for two OTA
slots. This establishes the metadata-selected boot candidate, not a separate
runtime version observation or proof that no fallback/custom boot path exists.
See the reference note's OTA-selection section for sources and caveats.

## Heartbeat/offline policy: instruction-backed finding

All following addresses refer to **1.1.1040 runtime addresses**, not flash
offsets. The DROM data starts at `0x3C140020`; IROM at `0x42000020`.

The diagnostic identifier `bd_sdev_comm_get_heart_and_off_inv` resolves through
literal `0x420044EC` to loads inside the function at `0x4203FFE4`:

- `0x4203FFEE..0x4203FFF6` initializes two output bytes to **8** and **60**.
- `0x4204002D..0x4204003E` permits nonzero low/high bytes of a retrieved
  configuration value to override the respective defaults.
- `0x42040094..0x4204009B` has a conditional policy that replaces the second
  byte with **2 × (first byte + 1)**. The controlling device field is not yet
  decoded; do not describe this as a confirmed low-battery rule.
- Its diagnostic text at `0x3C153654` labels the fields `heart` and `off`.
- Caller `0x420400E0`, specifically `0x42040100..0x42040106`, multiplies
  the second byte by **60,000** before passing it to a deadline helper.
- The helper at `0x420AC074` adds that interval to a 64-bit time value;
  its time source at `0x420AE4A0` includes a division-helper call with 1,000.
- `bd_sdev_comm_get_default_rf_heart_inv` at `0x4203FF60` separately returns
  a fallback **480**, or multiplies a nonzero configured low byte by **60**.

Together these strongly support an **8-minute heartbeat / 60-minute offline
default**, with device/configuration-dependent overrides. This is not a
measurement of the currently configured interval for a particular sensor.
The time-source helper's full SDK binding and every caller are not yet traced.

Both interval diagnostic names occur in 1.1.1040 and not in 1.1.1032. That is
evidence of a changed diagnostic/code surface, **not proof that the older
firmware lacked equivalent functionality**.

### Consequence for dormant sensors

Offline classification and RF wake/rejoin are different mechanisms. This code
does not establish that a silent sensor remains listening, that the hub sends a
wake command, or that the sensor periodically retries forever. It therefore
does not overturn the field observation that our recovery handler needs a
device-originated packet and an available ACK owner.

The useful investigation is to trace how these configuration values reach the
device and how failed ACKs affect its reporting mode, then correlate with a
controlled outage capture. Copying the numeric defaults into local recovery
code would not be an evidence-based fix.

## Receive-channel change: concrete code path, incomplete wire mapping

`bd_sdev_comm_inform_change_main_recv_channel` at `0x4204BBC0` references
diagnostics for a receive-channel change and informing subdevices. Its early
branches include factory-mode and lack-of-bidirectional-RF checks. Later code
iterates device records with a comparison against **39**, builds a recipient
list, maps input values `1 -> 4` and `2 -> 1`, and calls `0x4204ABA0`.

The existence of a device-notification path is established. The numeric values
are **not yet proven to be RF selectors, frequencies, or command counters**.
Likewise, the comparison with 39 corroborates a bounded device traversal but
is not, by itself, a complete proof of the advertised pairing capacity.
Capture-backed packet construction and the call's execution conditions remain
necessary before using it for channel reassignment or recovery.

## ACKs, counters, and restart: leads with important boundaries

- `BD_RF_MasterRCV_Send` and `BD_RF_Mastersend_deal` have code references near
  `0x420158F0` and `0x4201555C`. These are useful entry points for tracing
  radio receive/send scheduling; their names do not establish ACK timing.
- `_bd_sdev_comm_test_gateway_rf_ack` at `0x4203A7E0` checks the low five bits
  of a structure byte at offset 11 against 1, then tests a result byte for
  zero. Failure diagnostics distinguish invalid length and ACK result code.
  The structure has **not** been mapped to our normalized RF frames. This
  does not yet prove which on-air message acknowledges which operation.
- `bd_sdev_comm_process_mcu_abnormal_restart` at `0x42051FD0` includes the
  diagnostic `MCU restart!!!!`, with product-dependent branches. Shared
  firmware can contain paths for other hardware: this is not evidence that
  this board has a second MCU or that this is valve battery-rejoin handling.
- `bd_sdev_comm_inform_dev_ser` at `0x42052280` logs an address and code,
  then can call `bd_sdev_comm_inform_sdev_param_update2` at `0x4204B874`.
  **Do not expand `ser` to "sequence counter" without more evidence.** Its
  name is not a recovered counter-resynchronization command.

No new counter-reset rule, complete ACK builder, pairing stage, or remote-wake
command has been established in this pass. Existing successful protocol paths
must remain unchanged on the strength of these leads alone.

## Radio configuration and board mapping: follow-up evidence

The diagnostic `CMT2300A_OOK_Switch` references a function at `0x42015E90`.
It performs six calls to `0x4205DDF4`. Decoding that helper at its exact entry
shows a byte loop passing `(start + index, table[index])` to `0x42015BF0`,
which forwards to the register-write routine at `0x42016EB0`.

| Register start | Length | Table virtual address | Matching documented bank |
| --- | --- | --- | --- |
| `0x00` | 12 | `0x3C149780` | CMT |
| `0x0C` | 12 | `0x3C149774` | System |
| `0x18` | 8 | `0x3C14976C` | Frequency |
| `0x20` | 24 | `0x3C149754` | Data rate |
| `0x38` | 29 | `0x3C149734` | Baseband |
| `0x55` | 11 | `0x3C149728` | TX |

This exactly matches the manufacturer's six configuration banks (96 bytes),
giving a concrete route to examine stock modem settings. It does not establish
which profile is active for a particular pairing or telemetry exchange, nor
what later writes override it. Retain the table bytes privately and trace the
callers/mode changes before deriving operational settings.
[HOPERF CMT2300A datasheet, Table 22](https://www.hoperf.com/uploads/CMT2300A_Datasheet_EN_V1.8_202501029_1762138881.pdf).

There is also a **tentative software-derived bus map**, not wiring instructions:

| Candidate ESP GPIO | Inferred role | Code evidence |
| --- | --- | --- |
| 10 | Register select / CSB | Register read/write routines lower this line around address/data exchange. |
| 11 | Bidirectional SDIO | Direction changes around reads; byte-write loop drives its level from the next data bit. |
| 12 | SCLK | Byte-write loop toggles it once per bit, starting at branch target `0x42016E40`. |
| 13 | FIFO select / FCSB | Buffer-write path at `0x42016F48` selects it per byte and raises it afterwards; ordinary register transactions leave it high. |

The GPIO helpers construct a pin bitmask (`0x42016C4C`) and pass a pin argument
with level 1/0 (`0x42016CE0` / `0x42016CF0`). The register routines are
`0x42016EB0` / `0x42016EF8`; the byte sender is `0x42016E34`. These ordinary
instructions support the candidate map, but SDK binding, interrupts, physical
continuity and actual board-revision wiring are not qualified. Verify before
connecting an analyzer or building a hardware target. No probe was attached and
no hub pin was driven during this analysis.

See the [custom-firmware assessment](STOCK_HUB_CUSTOM_FIRMWARE_FEASIBILITY.md)
for reuse and qualification boundaries. Recovering this backend could improve
both waveform comparison and a future stock-board port; it does not replace
the separate protocol-state investigation.

## Reproducibility and limitations

Private analysis scripts preserve partition inventory, selective identifier
extraction, literal references, and relevant disassembly. Analysis deliberately
does not print NVS/FAT contents, credentials, or arbitrary string dumps.

The installed ESP32 Xtensa objdump crashes on raw-binary input. Converting the
extracted IROM segment to an ELF wrapper with `objcopy` permits inspection.
Subsequent [S3-tool qualification](STOCK_HUB_DECODER_TOOLING.md) removes the
raw-input crash and corroborates nine bounded regions; this paragraph records
the original tool limitation rather than a continuing research blocker.
That wrapper is **not** the original ELF and contains no recovered symbols.
The decoder is not independently qualified for all S3-specific instructions.
Literal pools, alignment padding, and branch targets require separate aligned
decoding; a linear disassembly can produce convincing nonsense. Claims above
are limited to ordinary instructions and corroborating literals/diagnostics.

No exact five-byte occurrence of the known `79 F4 88 2F 28` sync, in forward or
reverse order, was found in the newer application image. This does not imply
another RF protocol: constants can be split, packed, computed, or configured
through separate register writes.

The highest-value continuation is the report-mode/heartbeat configuration path
and its RF serializer. It can distinguish gateway bookkeeping from settings
that actually change a sensor's behavior. This is an analysis direction, not
authorization to transmit experimental packets or change production settings.
