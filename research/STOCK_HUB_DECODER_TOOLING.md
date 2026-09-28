# Stock hub decoder tooling

Research date: 2026-09-27. Scope: offline analysis of the retained ESP32-S3
firmware, not flashing or controlling the hub. Project status remains in
[the roadmap](../PROJECT_ROADMAP.md).

Follow-up: [Ghidra decompilation](STOCK_HUB_DECOMPILATION.md) now loads all six
application segments and exports selected pseudocode; this S3 disassembler
remains the instruction-level cross-check.

## What the crash means

The earlier note describes a **host-side disassembler crash**, not a hub crash,
failed firmware dump, or proof of corrupt firmware. The recorded observation
was that the installed `objdump` failed on raw-binary input while an ELF wrapper
allowed bounded inspection of the same extracted code. That workaround does
not establish the cause of the crash. See the
[original tool observations](STOCK_HUB_FIRMWARE_REFERENCES.md).

Two separate questions need verification: whether the input container triggers
a tool bug, and whether the decoder supports the actual ESP32-S3 instruction
set. Fixing the first does not automatically answer the second.

The follow-up offline reproduction removes stock firmware from the equation:
the old decoder exited with signal 11 twice on a synthetic two-byte `ret.n`
sample (`0d f0`), while an ELF wrapper let it decode that sample successfully.
This isolates a host-tool/input-path failure independent of proprietary code;
it does not yet identify the faulty source line or prove all S3 decoding works.

## Correct target and reproducible tool choice

Local read-only inventory found only the classic ESP32 PlatformIO toolchain:
`toolchain-xtensa-esp32`, package `8.4.0+2021r2-patch5`; its
`xtensa-esp32-elf-objdump --version` reports binutils `2.35.1.20201223`,
`crosstool-NG esp-2021r2-patch5`. This is not the target-specific S3 toolchain
listed for the stock image's ESP-IDF release.

Espressif's **ESP-IDF 5.1.6** tools documentation specifies separate ESP32,
ESP32-S2 and ESP32-S3 toolchains. The S3 package is
`xtensa-esp32s3-elf`, release `esp-12.2.0_20230208`. On Apple Silicon its
published archive is
[xtensa-esp32s3-elf-12.2.0_20230208-aarch64-apple-darwin.tar.xz](https://github.com/espressif/crosstool-NG/releases/download/esp-12.2.0_20230208/xtensa-esp32s3-elf-12.2.0_20230208-aarch64-apple-darwin.tar.xz),
with SHA-256
`ae9a1a3e12c0b6f6f28a3878f5964e91a410350248586c90db94f8bdaeef7695`.
The pinned [v5.1.6 tools.json](https://github.com/espressif/esp-idf/blob/v5.1.6/tools/tools.json)
also specifies **57,080,804 bytes** (about 54.4 MiB) for that compressed archive.
The official installer supports selecting one tool and a separate
`IDF_TOOLS_PATH`; no production PlatformIO upgrade is necessary.
[Espressif tool list and installer](https://docs.espressif.com/projects/esp-idf/en/v5.1.6/esp32s3/api-guides/tools/idf-tools.html#xtensa-esp32s3-elf).

## Completed local qualification

The main investigation downloaded that exact archive, checked both its size
and SHA-256 against Espressif's manifest, and extracted it separately under
`/private/tmp/rainpoint-s3-toolchain.VSTSGO/`. No global installation or
production PlatformIO change was made. The new executable reports binutils
`2.39.0.20220915`, crosstool-NG `esp-12.2.0_20230208`.

The same synthetic test now succeeds for raw input twice and for the ELF
wrapper. Reproduction command (offline, no firmware or device connection):

```sh
python3 /private/tmp/rainpoint_decoder_probe.py --prefix /private/tmp/rainpoint-s3-toolchain.VSTSGO/xtensa-esp32s3-elf/bin/xtensa-esp32s3-elf-
```

With its default old-tool prefix it exits 1 and records signal 11 for both raw
attempts; with the S3 prefix it exits 0 and all three paths decode `ret.n`.
The probe disables core dumps and keeps outputs private. A bounded LLDB
attempt did not yield a stack and was stopped; the precise old-binutils source
defect remains unlocated. The demonstrated repair is changing the offline
analysis tool, not patching the hub or asserting a known faulty source line.

The full retained 1.1.1040 IROM segment then decoded with return code zero.
This is an input-handling check, **not validation of every line as executable
code**. Nine bounded regions (292 instruction rows) agree after normalizing
address labels and literal annotations across old-tool ELF, S3 raw and S3 ELF:

| Region | Start | Exclusive end |
| --- | --- | --- |
| Heartbeat defaults/conditional override | `0x4203FFE4` | `0x420400A1` |
| Allocator wrapper, through return | `0x420403D4` | `0x4204040E` |
| ACK check prefix | `0x4203A7E0` | `0x4203A80F` |
| ACK check branch target | `0x4203A810` | `0x4203A816` |
| ACK check tail | `0x4203A819` | `0x4203A838` |
| Channel-notification region | `0x4204ABA0` | `0x4204AC50` |
| Report-mode prefix | `0x4204463C` | `0x420446D0` |
| Report-mode store region | `0x420446E1` | `0x42044720` |
| Radio-register write | `0x42016EB0` | `0x42016EF8` |

Early differential runs intentionally retained failure evidence. Clipping an
instruction at the stop address produced misleading raw/ELF differences;
the harness now decodes beyond the comparison window and compares instruction
starts within it. Linear decoding after the allocator's return at `0x4204040C`
and across ACK padding at `0x4203A80F` also differed. Starting at independently
identified branch targets removes those disagreements. Even the S3 decoder
can produce a plausible S3 opcode from padding: do not use linear output as
control-flow evidence.

Private final provenance is under
`captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/decoder-validation-nnfd7cdy/`:
summary, synthetic probe, differential harness, input hash, extracted ELF and
bounded disassembly. Earlier comparison failures remain beside it. All are
Git-ignored. The tool path is temporary; reconstruct it from the pinned archive
and checksum if unavailable, without upgrading production tooling.

### Sharpened heartbeat finding

In the rechecked heartbeat block, successful internal lookup selector 31
supplies one byte at stack `+32`. Branches `0x42040077..0x42040091` select the
`off = 2 × (heart + 1)` override exactly when that byte is **`0x80` or `0x03`**.
Other values skip that override; prior configured/default intervals still
apply. This is a static byte predicate, not a decoded device mode or RF field.
Its configuration source, model applicability and serializer remain to be
traced. It does not prove a remote wake mechanism or explain a particular
historical sensor outage on its own.

## Containers and instruction boundaries

An ESP firmware image contains headers, load-addressed segments and a footer;
it is not the original build ELF. The image's segment addresses, not flash
partition offsets, determine code addresses. Parse and validate the image first,
then extract executable segments. `image-info` is an offline metadata operation.
[Espressif image format](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/advanced-topics/firmware-image-format.html).

A synthetic ELF can give a decoder the correct executable section and virtual
address, but cannot recreate source, symbols, types or original section
boundaries. GNU documents `-b` for file format, `-m` for architecture, `-i` for
supported formats/architectures and bounded address options. `-D` can decode
data as instructions; unrestricted output should not be treated as a call graph.
[GNU objdump manual](https://sourceware.org/binutils/docs/binutils/objdump.html).

Do not limit eventual coverage to IROM: ESP-IDF can place interrupt and
time-critical code in IRAM. Conversely, DROM is normally read-only data and
literal constants can sit alongside executable code. Code/data separation and
branch-entry validation remain necessary even with the correct decoder.
[Espressif memory types](https://docs.espressif.com/projects/esp-idf/en/v5.1.6/esp32s3/api-guides/memory-types.html).

## Useful work without user intervention

The following are research methods, not a second status checklist:

- Qualify the decoder with non-secret fixtures; recheck earlier instruction
  claims and maintain address/segment/tool-version provenance.
- Trace callers, serializers and state writes for pairing, reconnect, ACKs,
  counters and retained channel selection. Check both directions across queue
  boundaries instead of assuming a string reference identifies a whole path.
- Compare validated versions 1.1.1032 and 1.1.1040 by function behavior and
  constants, not only raw byte differences or shifted addresses.
- Correlate recovered structures and branches with existing RF captures and
  local implementation tests; turn established differences into reviewable
  hypotheses and deterministic fixtures.
- Audit software ownership/restart/freshness behavior using temporary databases
  and fake transport, without deploying or issuing RF commands.

This can narrow the next physical experiment substantially. It cannot alone
prove which path was taken on the live hub, the radio's active configuration at
a particular instant, real RF timing, receiver acceptance, or recovery after a
device battery change. Those conclusions still need matching captures or an
explicitly authorized controlled hardware test.

Keep firmware bytes, disassembly and configuration private. Publish only
necessary redacted findings and independently authored tests. Do not upload
the dump to external decoder services. Runtime fixes remain subject to the
review gate in the [improvement plan](STOCK_FIRMWARE_IMPROVEMENT_PLAN.md).
