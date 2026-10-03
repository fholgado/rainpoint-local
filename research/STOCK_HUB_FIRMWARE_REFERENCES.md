# Stock hub firmware: offline format references

Verified 2026-09-27 against primary sources. This note records formats and analysis
techniques, plus verification of numeric metadata and tool observations supplied
by the offline-analysis task. No dump was opened and no device was contacted for
this reference task. Project status remains in
[PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

## ESP image and partition formats — confirmed

All offsets below are bytes; multibyte integers are little-endian. Image offsets
are relative to an extracted application image, not the full flash dump.

| Image-relative offset | Meaning |
| --- | --- |
| `0x00` | Magic `E9` |
| `0x01` | Segment count |
| `0x02` | Flash mode |
| `0x03` | Flash size/speed nibbles |
| `0x04` | Entry point, uint32 |
| `0x0C` | Chip ID, uint16 |
| `0x17` | Appended-SHA256 flag |
| `0x18` | First segment header: load address uint32, data length uint32 |
| `0x20` | First segment data |

Subsequent segment headers follow the preceding segment data immediately. Each
header is eight bytes. Footer padding places the checksum at the last byte of a
16-byte block. Checksum is XOR of segment data bytes with initial value `EF`;
when flagged, a 32-byte SHA256 follows. This hash is not a secure-boot signature.
Use `esptool image-info` (older versions: `image_info`) on an extracted image,
not indiscriminately on an entire flash dump.
[Espressif image-format specification](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/advanced-topics/firmware-image-format.html).

The partition-table default address is `0x8000`, but it is configurable: verify
the dump rather than assuming it. An app partition's offset and allocated size
are not the same as the contained image's segment addresses and actual length.
OTA slots must be analyzed separately; a valid image does not establish which
slot booted.
[Espressif partition-table guide](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/partition-tables.html).

| Partition-record offset | Meaning |
| --- | --- |
| `0x00` | Two magic bytes `AA 50` |
| `0x02`, `0x03` | Type, subtype |
| `0x04` | Flash offset, uint32 |
| `0x08` | Partition size, uint32 |
| `0x0C` | 16-byte label |
| `0x1C` | Flags, uint32; bit 0 denotes encryption |

Records are 32 bytes (`<2sBBLL16sL`). An MD5 record begins `EB EB`, followed by
14 `FF` bytes and the digest of preceding records. An all-`FF` record terminates
the table. ESP-IDF's own `gen_esp32part.py` decodes and validates this format.
[Espressif v4.4.8 parser source](https://raw.githubusercontent.com/espressif/esp-idf/v4.4.8/components/partition_table/gen_esp32part.py).

### Application descriptor

The descriptor starts at image `+0x20` in the first DROM segment.
[Espressif application-image guide](https://docs.espressif.com/projects/esp-idf/en/v5.2/esp32s3/api-reference/system/app_image_format.html).

These offsets are **relative to the descriptor**; add `0x20` for image offsets:

| Descriptor-relative offset | Field |
| --- | --- |
| `0x00` | Magic uint32 `ABCD5432` (bytes `32 54 CD AB`) |
| `0x04` | Secure version uint32 |
| `0x10` | Version string, 32 bytes |
| `0x30` | Project name, 32 bytes |
| `0x50`, `0x60` | Build time/date, 16 bytes each |
| `0x70` | ESP-IDF version string, 32 bytes |
| `0x90` | Original ELF SHA256, 32 bytes |

The v5.2 structure totals 256 bytes. The ELF hash identifies the original ELF,
not the extracted app image. Version-specific reserved fields should not be
interpreted using an unrelated newer layout.
[Espressif v5.2 descriptor definition](https://raw.githubusercontent.com/espressif/esp-idf/v5.2/components/esp_app_format/include/esp_app_desc.h).

### OTA selection metadata — verified against IDF v4.4.8

Each OTA selection record is 32 bytes: sequence uint32 at `+0x00`, 20-byte
label at `+0x04`, state uint32 at `+0x18`, CRC uint32 at `+0x1C`. State `2`
is `ESP_OTA_IMG_VALID`; states `3/4` mean invalid/aborted.
[Espressif OTA record definition](https://raw.githubusercontent.com/espressif/esp-idf/v4.4.8/components/bootloader_support/include/esp_flash_partitions.h).

CRC covers **only the four little-endian sequence bytes**, using
`esp_rom_crc32_le(UINT32_MAX, bytes, 4)`. The selector rejects erased sequence
`FFFFFFFF`, invalid/aborted state, or CRC mismatch; when both records are valid,
it selects the higher sequence.
[Espressif OTA validation/selection implementation](https://raw.githubusercontent.com/espressif/esp-idf/v4.4.8/components/bootloader_support/src/bootloader_common_loader.c).

Independent local calculation for the supplied metadata:

| Sequence | State | Supplied CRC | Recomputed CRC | Result |
| --- | --- | --- | --- | --- |
| 1 | 2 | `4743989A` | `4743989A` | Valid, older |
| 2 | 2 | `55F63774` | `55F63774` | Valid, selected |

Reproduction: `zlib.crc32(struct.pack("<I", sequence), 0xffffffff) & 0xffffffff`.
Espressif's implementation complements the supplied CRC before processing and
complements the result; do not substitute an ordinary default-seed CRC call.
[Espressif CRC implementation](https://raw.githubusercontent.com/espressif/esp-idf/v4.4.8/components/esp_rom/patches/esp_rom_crc.c).

The two records are at OTA-data offsets `0` and `0x1000`. Selected slot is
`(sequence - 1) % OTA_app_count`; with two OTA slots, sequence 2 selects
**`ota_1` as the metadata-selected boot candidate**. This does not prove that
partition actually ran: anti-rollback secure-version checks and failed image
validation can cause different selection/fallback. The conclusion assumes
standard IDF boot selection, not a custom override or forced boot path.
[Espressif boot-selection and image-loading implementation](https://raw.githubusercontent.com/espressif/esp-idf/v4.4.8/components/bootloader_support/src/bootloader_utility.c).

## Offline tooling — observed locally, with limitations

**Follow-up:** the raw-input crash is reproduced on synthetic bytes and avoided
with the separately installed, checksum-verified official ESP32-S3 toolchain.
See [decoder qualification](STOCK_HUB_DECODER_TOOLING.md) for regression results,
bounded cross-checks and remaining code/data alignment limitations. The older
commands below preserve the original observation, not the preferred decoder.

Installed paths verified without opening firmware:

```text
/Users/federicoholgado/.platformio/packages/tool-esptoolpy/
/Users/federicoholgado/.platformio/packages/framework-arduinoespressif32/tools/gen_esp32part.py
/Users/federicoholgado/.platformio/packages/toolchain-xtensa-esp32/bin/xtensa-esp32-elf-objdump
```

The last tool reports binutils `2.35.1.20201223`, Espressif
`esp-2021r2-patch5`; `-i` lists `binary` and `xtensa`. Its installed package is
ESP32-specific, **not an independently verified ESP32-S3 instruction decoder**.
Ordinary Xtensa disassembly can be useful, but an undecoded instruction must not
be labeled corruption without checking an S3-capable decoder.

Raw-input GNU option pattern (documented, but **failed locally**):

```sh
xtensa-esp32-elf-objdump -D -b binary -m xtensa -EL \
  --adjust-vma=0x42000000 extracted-code-segment.bin
```

`-b binary` selects raw input; `-m` selects architecture; `-EL` selects
little-endian; `--adjust-vma` rebases addresses; `-D` disassembles all sections.
Use the **actual segment load address**, not its flash offset. GNU warns that
`-D` can interpret data as instructions. Raw segments lack ELF symbols and
section metadata; literal pools therefore require manual care.
[GNU objdump manual](https://sourceware.org/binutils/docs/binutils/objdump.html).

The offline-analysis task observed raw `objdump -b binary` terminate with
segmentation fault/status 139. Wrapping the extracted segment as an ELF object
worked with the installed tools:

```sh
xtensa-esp32-elf-objcopy -I binary -O elf32-xtensa-le -B xtensa \
  --rename-section .data=.text,alloc,load,readonly,code,contents \
  --change-addresses=0x42000020 extracted-code-segment.bin extracted-code-segment.elf
xtensa-esp32-elf-objdump -d extracted-code-segment.elf
```

The displayed base is the address used in that successful observation; use the
actual extracted segment's load address for each conversion. This synthetic ELF
does not restore original symbols or separate literal pools from code. Restrict
disassembly to bounded basic blocks starting at independently established
instruction boundaries (for example verified branch/call targets). Literal
pools and padding otherwise produce misleading instructions and can derail
linear decoding; successful output alone does not validate a function.
`--start-address`/`--stop-address` provide the bounds. The wrapping command uses
GNU's binary input, section-renaming, and address-adjustment features.
[GNU objcopy manual](https://sourceware.org/binutils/docs/binutils/objcopy.html).

Analysis inference: a string at segment-data offset `k` has runtime address
`load_addr + k`; search little-endian pointers and their literal-load references,
then trace callers. This is an address-mapping technique, not proof that a
matching constant is live code or an active configuration.

## CMT2300A configuration — confirmed documentation

The manufacturer's configuration bank occupies `00–5F`:

| Addresses | Bank | Bytes |
| --- | --- | --- |
| `00–0B` | CMT/internal | 12 |
| `0C–17` | System | 12 |
| `18–1F` | Frequency | 8 |
| `20–37` | Data rate/deviation/bandwidth | 24 |
| `38–54` | Baseband/packet | 29 |
| `55–5F` | TX | 11 |

RFPDK generates these values. Runtime control is separate (`60–6A`, `6B–71`).
Register transfers use CSB with a read/write bit and seven-bit address; FIFO
transfers use FCSB. FIFO timing differs from register timing: FCSB lead time is
at least a clock period, trailing delay at least 2 microseconds, and high time
between accesses at least 4 microseconds. These distinctions help identify
bit-banged access functions during static analysis.
[HOPERF datasheet v1.8, sections 5.1–5.2 and 8](https://hoperf.com/uploads/CMT2300A_Datasheet_EN_V1.8_202501029_1762138881.pdf).

Useful decode targets:

| Registers | Interpretation |
| --- | --- |
| `18`, `19–1B[3:0]` | RX PLL integer N and fractional K |
| `1C`, `1D–1F[3:0]` | TX PLL integer N and fractional K |
| `1B[6:4]`, `1F[6:4]` | Divider code, VCO bank; AN199 needed for full frequency calculation |
| `38[1:0]` | Data mode: 0 direct, 2 packet |
| `38[7:3]`, `38[2]` | RX preamble length, 8-/4-bit unit |
| `39–3A`, `3B` | TX preamble length, preamble pattern |
| `3C[3:1]`, `3D–44` | Sync size-minus-one, sync storage |
| `45–46` | Payload configuration/length |
| `4C–4E` | FEC/CRC configuration and seed |
| `4F–50` | Whitening/Manchester configuration and seed |
| `60` | Mode command: `08` RX, `10` sleep, `40` TX |

These mappings describe the chip, not this hub's values. Exact frequency cannot
be claimed from N/K alone without oscillator, divider, and mode context.
[HOPERF AN192 v0.6](https://www.hoperf.com/uploads/AN192_CMT2300A_Register_Description_EN_V0.6_20250624_1751591675.pdf).

FIFO defaults to separate 32-byte RX/TX buffers; `69[1]` merges them into one
64-byte buffer, with `69[2]` selecting RX/TX. `69[0]` selects SPI FIFO read/write.
`6C[1:0]` clears RX/TX; `6C[2]` restores TX's read pointer for retransmission.
`AUTO_ACK_EN` does **not** autonomously switch RX to TX and transmit an ACK.
Short sync words occupy the **high** end of the 64-bit sync field: two-byte
`56 78` uses registers `44=56`, `43=78`, not `3D/3E`. Fixed payload length uses
an N-minus-one encoding; variable length and node-ID placement change length
semantics. Do not equate FIFO bytes with the complete on-air packet: CRC,
preamble, sync, and encoding may be handled by hardware.
[HOPERF AN143 v1.1, sections 1–2](https://www.hoperf.com/uploads/AN143_CMT2300A_FIFO_and_Packet_Format_Usage_Guide_V1.1_202511_1764551828.pdf).

## Recovery hypotheses — not firmware findings

A contiguous 96-byte array, or six arrays of lengths `12/12/8/24/29/11`, is a
plausible initialization candidate. It is not a reliable signature by itself.
Require code references establishing register destinations and execution paths;
follow per-mode, per-channel, and post-initialization writes. Correlate decoded
packet settings with preserved passive RF captures before calling them active.
Firmware may store multiple region profiles, dead example tables, or generated
values rather than literal tables. None of these possibilities authorizes live
transmission or changing the hub.

The official product page lists AN149 (RF parameter configuration) and AN199
(frequency calculation); their contents were not retrieved in this pass, so no
formula or undocumented modem setting is inferred from their titles.
[HOPERF product document index](https://www.hoperf.com/ic/rf_transceiver/CMT2300A.html).
