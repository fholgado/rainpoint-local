# Stock lifecycle comparison: 1.1.1032 versus 1.1.1040

2026-09-27. Offline comparison of the two integrity-checked application images
retained in the same hub backup. No download, hub access, deployment or runtime
change. This is a bounded comparison, not a complete vendor changelog. Status
belongs in [the roadmap](../PROJECT_ROADMAP.md).

## Findings

| Behavior | 1.1.1032 evidence | 1.1.1040 evidence | Qualified result |
| --- | --- | --- | --- |
| Shared sequence increment/wrap | `42036190..420361B3` | `42037920..42037943` | Same instruction body after masking only three PC-relative literal-load displacements; both load the same sequence-byte address. |
| Pending ACK phase | `42039ADC..42039AE5` | `4204A600..4204A609` | Both compare all six low bits, not five bits plus an unrelated action flag. |
| Pending ACK command/route | `42039A64..85`, `42039AC4..D6`, `42039AEB..42039B0B` | `4204A58C..AD`, `4204A5E8..FA`, `4204A60F..2F` | Both require gateway identity, the full command including ACK flag, and queued device identity. |
| Pending-list retry budget | `420490BD..CC` | queue insertion `4204A8E0`; detailed callsites in the ACK lifecycle note | Older code also has the conditional zero-versus-four budget; four retries are not a newly introduced 1.1.1040 concept. |
| Timeout resend packet | `42040F72..42040FC2` | `420445A1..42044601` | Both mark transport metadata, copy the retained packet, send it and repair its internal pointer. No fresh header is built on this bounded resend branch. |

The counter generator's stored sequence advances from zero through `1..64`,
then back to 1; masking to six bits gives `1..63,0,1`. All 36 instruction bytes
match except the six displacement bytes of three `l32r` instructions. Their
resolved literals all point to `3FCA710F` in both images. The constant 63,
comparison, stores, branch displacement and return are unchanged. Both complete
instruction sequences were independently decoded with the qualified S3 tool.

This rules out a change to **this generator's increment/wrap algorithm** between
these two images as an explanation. It does not exclude changed callers,
initialization order, generic memory writes or persistence elsewhere. The hub
generator is also not the valve's acceptance logic.

## Why this matters locally

The full-phase matching repair and byte-preserving retransmission policy align
with a contract present in both retained versions, not just a recently changed
diagnostic name. There is no evidence here for replacing our established pairing
prefix with an older stock version or for trying arbitrary new phases after a
lost ACK. Counter generation and command acceptance remain separate questions.

The pending-list nodes and allocation calling conventions differ in generated
code; do not transplant offsets or function addresses between images. Nor does
this small comparison establish identical end-to-end retry timing, all result
handling, offline-device policy or scheduler behavior. For the independently
traced newer timing and failure paths, see
[ACK/retry lifecycle](STOCK_HUB_ACK_RETRY_LIFECYCLE.md).

## Reproduction and limits

Private script and outputs live under the ignored capture bundle's
`analysis/version-lifecycle-20260927/` with restrictive permissions. `compare.py`
parses the images' actual segment headers, records their SHA-256 hashes and:

1. Finds known diagnostic string pointers and literal-load candidates for
   navigation; these candidates are explicitly not proof of function boundaries.
2. Searches each IROM for the qualified counter instruction body with only the
   three displacement operands masked; each image has exactly one match.
3. Resolves all three literals and verifies they name the same byte.
4. Saves bounded S3 assembly for manual branch and callsite checks. Instructions
   after padding must be decoded from actual branch targets, not assumed from
   a linear listing.

The counter match is mechanically asserted; ACK/queue findings above are
selected assembly interpretations, not whole-function equivalence claims.
Historical firmware, pseudocode, assembly, configuration and identifiers remain
private. No proprietary implementation is incorporated into local runtime code.
