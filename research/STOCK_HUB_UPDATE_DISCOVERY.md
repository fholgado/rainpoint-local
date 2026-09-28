# Stock hub firmware update discovery

Research date: 2026-09-27. Scope: public source-code/documentation reads,
offline examination, and an explicitly approved off-device firmware lookup.
No account login, firmware download, hub update check, flash write, or OTA
operation was performed. This is an evidence/procedure note;
project priorities and gates remain in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

## Result

**The vendor offered no newer firmware for this hub running 1.1.1040.**
The approved regional lookup returned HTTP 200, `result: 0`, and empty `data`;
there was no image URL to download. This is not proof of the latest version
across all regions, hardware variants or rollout cohorts. The stock application constructs
`<scheme>://<configured-host>:<configured-port>/app/edge/firmware/upgrade` and
supplies the hub MAC, model code, and current version. Its success callback
accepts a string in `data` and passes it to the OTA starter, which can initiate
an update. Consequently, asking the *hub* to
check for an update is not a safe download-only experiment.

There is already a usable, hardware-matched offline comparison pair:
`1.1.1032` and `1.1.1040` in the retained OTA slots. Both application images
validated as ESP32-S3 images. The retail hub is **HWG023WBRF-V2**, while the
embedded ESP-IDF project name is **HWG009WB**; these are not interchangeable
device identifiers. [Local inventory and image hashes](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md#validated-image-inventory).

## Live lookup result — 2026-09-27

The user approved sending this hub's device identity, model 289, version
1.1.1040, timestamp and derived signature from the Mac to
`https://region3.homgarus.com:1446/app/edge/firmware/upgrade`, and privately
downloading any returned firmware. Saved configuration, CRC-checked NVS
metadata and the retained boot log supplied the model/version/endpoint inputs;
the project descriptor was not used as a retail model identifier.

At **21:28:02 UTC**, the service returned HTTP 200 / `application/json`,
`result: 0`, and an empty string in `data`. The stock callback recognizes
result zero. No download URL or firmware bytes were returned. The retained,
validated **1.1.1040** application therefore remains our working baseline,
with 1.1.1032 available for comparison. No command was sent to the hub.

An initial attempt at 21:26:51 UTC with the default Python HTTP user agent
received a generic nginx HTTP 403 page. Repeating with the stock client's
`ESP32 HTTP Client/1.0` user agent succeeded. This header is present at DROM
`0x3C16B2EC`, referenced through literal `0x42080E14` and SDK use
`0x420A8CAD`. This observation does not establish the server's full validation
policy or suggest that the user agent alone authorizes requests.

The private lookup helper verified TLS, restricted the request to the approved
endpoint, disabled request redirects/proxy inheritance, and bounded response
sizes. It did not emulate the stock client's HTTP fallback. Private request,
response and safe summary are retained under
`captures/stock-hub-firmware/vendor-lookup-20260927-e1tfi667/`; the earlier
403 is retained under `vendor-lookup-20260927-151b1fb3/`. These directories are
Git-ignored, mode 700, with evidence files mode 600. Never publish their raw
request bodies, identities or signatures.

The [complete HTTP trace](STOCK_HUB_HTTP_UPDATE_TRACE.md) records method,
wrapper, signing and configuration mapping. The
[firmware reference](STOCK_HUB_FIRMWARE_REFERENCE.md) consolidates the current
subsystem findings; the [improvement plan](STOCK_FIRMWARE_IMPROVEMENT_PLAN.md)
is for review before implementation.

## Instruction-backed device-side discovery

Addresses below refer to the retained **1.1.1040 runtime mapping**, not flash
offsets. Source is the private application/disassembly retained under
`captures/stock-hub-firmware/2026-09-27-adzoj0e3/`; no raw firmware or private
identifiers are reproduced here. The mapping and provenance are documented in
[the stock analysis](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md).

| Evidence | Address / interpretation |
| --- | --- |
| URL format `%s://%s:%u/app/edge/firmware/upgrade` | DROM `0x3C14F2D4`; URL builder `0x4202BC48`, references `0x4202C0C0` / `0x4202C0E0` |
| Production URL construction | `0x4202C0D1` uses configured hostname, port and protocol; no complete production URL is established by the format alone |
| Development fallback | `0x4202C0A8` uses an HTTP private-LAN address and port 8080; this is not a vendor download host and must not be probed |
| Static regional host strings | `region3.homgarus.com` at `0x3C14BF6C`; `region0.homgarus.com` at `0x3C14BFD0`; presence alone does not identify the active configured endpoint |
| Request format | DROM `0x3C1506A8`, referenced at `0x42030F6F` |
| Request construction and queue | `0x42030EF8` constructs the body; `0x42030F8D` sets message 47 and `0x42030F95` calls the queue helper; dispatch at `0x4202BDEA` / `0x4202BDEF` selects this URL branch; `bd_ota_check_new_gw_firmware_path` is `0x42030F9C` |
| Success callback | `0x42031048` checks result zero, parses `data` as a string, copies it into OTA-request storage at offset `+40`, then calls `bd_ota_start` (`0x42030D3C`) at `0x42031100` |

The recovered request template is:

```json
{"Mac":"<six lowercase hexadecimal octets separated by hyphens>","modelCode":"<decimal model code>","currentVersion":"<version>"}
```

All three values are JSON strings. The template capitalizes `Mac` and uses
`%02x` for its octets, `%u` for the model code, and `%s` for the version. A
successful `data` string is evidence for a server-selected download location,
not a publicly browsable manifest or a known static filename. This template is
only the inner body: the complete POST request adds device name, timestamp and
signature as described in the HTTP trace. It does not use the app's account
token. The live result above validates this scoped reproduction, not arbitrary
model queries or every server-side validation rule.

Further instruction evidence narrows the authentication investigation. The
HTTP task calls `_bd_http_modify_req_data` (`0x4202B6D0`) at `0x4202C562`
before packaging the request URL. For message 47, its message-class mask
`0x00FF7A63` (literal `0x42002E38`, index `47-28`) selects the branch at
`0x4202B9D1`, which calls the helper identified as
`_bd_http_hmac_md5_encoding` (`0x4202B5A4`) at `0x4202BABA`. Static HTTP
formats also mention signature, timestamp, nonce and access-key fields. The
message-47 signing input, serialization and key source are now traced in the
HTTP reference. The helper consumed the required private material without
printing it. This explains preparation beyond the three-field template; it
does not establish the server's independent checks or image authentication.

A literal `http://` / `https://` inventory of both extracted applications and
the complete retained flash read found no usable literal URL. This rules out
a straightforward embedded/cached plaintext link in that scan, not encoded,
compressed, fragmented or dynamically assembled URLs. The narrow inventory
helper and its private result are retained alongside the analysis. It reports
only hostname/extension metadata; any future signed URL must remain private.

## What public sources establish

### Cloud host and app authentication, not a firmware manifest

The public `homeassistant-homgar` client at commit
`0897690ea542bd61e4a58baf70b7962f53bfa0df` uses
`https://region3.homgarus.com`. Its app requests use an `auth` token and
`appCode`, with separate namespaces for HomGar (`1`) and RainPoint (`2`).
Its product-catalog method requests `/app/common/core/productModel` with
authentication. **That endpoint describes supported models; it is not a
firmware-download endpoint.** No firmware/upgrade method was found in the
inspected client. These are facts about this community client's implementation,
not a vendor guarantee about the device-side endpoint.
[Pinned client source](https://github.com/brettmeyerowitz/homeassistant-homgar/blob/0897690ea542bd61e4a58baf70b7962f53bfa0df/custom_components/homgar/api/client.py),
[pinned app namespace mapping](https://github.com/brettmeyerowitz/homeassistant-homgar/blob/0897690ea542bd61e4a58baf70b7962f53bfa0df/custom_components/homgar/const.py#L45-L50).

The independently inspected `macher91/homgar-homeassistant` client at commit
`52786d05f6f048ca7d390abe1b2301a726e90001` likewise defaults to this host and
uses an app token. No firmware/upgrade endpoint definition was found in that
API source either. This limits the public-source discovery result; it does
not establish that the vendor lacks other APIs.
[Pinned second client](https://github.com/macher91/homgar-homeassistant/blob/52786d05f6f048ca7d390abe1b2301a726e90001/custom_components/homgar/api.py).

The earlier local network observation found TLS connections on TCP 1446 and
a `*.homgarus.com` certificate. It did not recover encrypted payloads or prove
that firmware discovery uses that connection. Do not combine the app's HTTPS
host and the observed port into a supposedly verified firmware URL.
[Prior cloud/network evidence](cloud/README.md#hub-network-behavior).

### Product matching is essential

The public captured product catalog distinguishes the following models:

| Catalog model | `modelCode` | `productCode` |
| --- | ---: | ---: |
| HWG009WB | 280 | 1 |
| HWG023WBRF-V2 | 289 | 1 |
| HWG023WRF | 273 | 1 |
| HWG023WRF-V6 | 332 | 1 |
| HWG023WRF-V8 | 369 | 1 |

Source: the pinned catalog's
[HWG023WBRF-V2 entry](https://github.com/brettmeyerowitz/homeassistant-homgar/blob/0897690ea542bd61e4a58baf70b7962f53bfa0df/custom_components/homgar/data/product_models.json#L1961-L1965),
[HWG009WB entry](https://github.com/brettmeyerowitz/homeassistant-homgar/blob/0897690ea542bd61e4a58baf70b7962f53bfa0df/custom_components/homgar/data/product_models.json#L2395-L2399),
[HWG023WRF entry](https://github.com/brettmeyerowitz/homeassistant-homgar/blob/0897690ea542bd61e4a58baf70b7962f53bfa0df/custom_components/homgar/data/product_models.json#L17424-L17428),
[V6 entry](https://github.com/brettmeyerowitz/homeassistant-homgar/blob/0897690ea542bd61e4a58baf70b7962f53bfa0df/custom_components/homgar/data/product_models.json#L20824-L20828), and
[V8 entry](https://github.com/brettmeyerowitz/homeassistant-homgar/blob/0897690ea542bd61e4a58baf70b7962f53bfa0df/custom_components/homgar/data/product_models.json#L22306-L22310).

For this retained hub, 289 is both the catalog match and the hub model code
corroborated by the retained boot log before discovery. The descriptor's `HWG009WB` project string is not a
reason to request a model-280 firmware. A matching version string, common
ESP32-S3 chip, shared project name or shared product code is insufficient to
establish binary interchangeability across these variants.

### Vendor documentation exposes an app workflow, not binary links

RainPoint's own HCS026FRF troubleshooting instructions tell users to open the
Gateway page in RainPoint Home, inspect Firmware Version, and update gateway
firmware when available. This establishes the supported user-facing route,
but the article supplies neither a `.bin` URL nor a discovery API schema.
It is not permission to invoke that update on the research hub.
[RainPoint HCS026FRF common issues, condition 3](https://service.rainpointonline.com/hc/en-us/articles/17355146149775-RAINPOINT-HCS026FRF-Common-Issues-Fixes).

## Safe route to an additional offline comparison image

The next acquisition should be off-device and separated from installation.
A vendor-provided direct image link plus model/hardware applicability and
checksum would provide the cleanest provenance. Alternatively, an explicitly
authorized, existing app response/export or a confirmed read-only metadata
request could reveal the selected image URL without calling the hub's OTA
callback. The approved request above exercised that route but offered no image.

For any future lookup, recheck model/version and regional configuration and
use the traced request contract within the applicable approval. Do not guess credentials, enumerate identifiers,
probe the development fallback, or treat account login as passive: the public
integration documents that a new login can end the phone app's session.
[Upstream session-conflict warning](https://github.com/brettmeyerowitz/homeassistant-homgar/blob/0897690ea542bd61e4a58baf70b7962f53bfa0df/README.md).

Any subsequently authorized artifact should be retained privately with its
provenance, exact model/version/hardware association, response metadata,
download time, size and SHA-256. Signed or token-bearing URLs must stay private.
Verify chip/project/version and image integrity before static comparison;
record whether the bytes are a complete app image, container, encrypted
payload or delta. Do not flash an image merely because its descriptor or
checksum parses. ESP image integrity is not publisher authenticity.
[Espressif image format](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/advanced-topics/firmware-image-format.html),
[local format and validation references](STOCK_HUB_FIRMWARE_REFERENCES.md).

Until that extra artifact is available, comparing the retained 1032 and 1040
images can continue without network access or changing stock hardware. Useful
comparisons are the already identified ACK framing, association state,
timeouts, ownership and RF receive/dispatch paths documented in the
[implementation comparison](STOCK_HUB_IMPLEMENTATION_COMPARISON_20260927.md).
This keeps firmware analysis focused on improving the existing implementation
before any stock-hardware port.
