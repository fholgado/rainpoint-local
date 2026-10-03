# Stock hub HTTP firmware-discovery trace

Research date: 2026-09-27. This is an offline trace of the retained 1.1.1040
application. The separately approved [live lookup](STOCK_HUB_UPDATE_DISCOVERY.md#live-lookup-result--2026-09-27)
subsequently returned HTTP 200, result zero and no newer offering; it does not
prove the server's complete validation policy. No hardware operation or
firmware installation was performed. Addresses
are runtime addresses in that image. Image provenance and mappings are in
[the stock analysis](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md); the discovery
entry point and OTA callback are in
[the discovery note](STOCK_HUB_UPDATE_DISCOVERY.md). Project priorities remain
in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

## Verified request construction

Message 47 is the firmware-discovery request. It goes through the signing
branch selected at `0x4202B77D` by mask `0x00FF7A63`, builds the URL through
`0x4202BC48`, and selects `/app/edge/firmware/upgrade` at `0x4202BDEA` /
`0x4202BDEF` / `0x4202C0D1`.

The method is **POST**, with **Content-Type: application/json**:

- `0x4202BD2C` stores method 1 at request structure offset `+0x194`.
- `0x4202C78E` reads that field; `0x4202C7A0` selects method 1 and
  `0x4202C7AD` through `0x4202C7C1` attaches the complete body.
- Header literals referenced at `0x4202C780` / `0x4202C783` are
  `application/json` / `Content-Type`.
- The locally installed ESP32-S3 SDK's `esp_http_client.h`, lines 69-70,
  assigns GET=0 and POST=1, corroborating the method interpretation.
- The stock user agent is `ESP32 HTTP Client/1.0` (DROM `0x3C16B2EC`,
  literal `0x42080E14`, SDK use `0x420A8CAD`). Matching it changed the observed
  response from generic HTTP 403 to accepted JSON; see the live lookup record.

The original body from `0x42030EF8` has string fields `Mac`, `modelCode`,
and `currentVersion`. The wrapping code produces this shape without spaces:

```json
{"key":"<signature>","dname":"<configured device name>","timestamp":<integer>,"Mac":"<lowercase-hyphenated MAC>","modelCode":"<decimal code>","currentVersion":"<version>"}
```

The wrapper format at DROM `0x3C14EF18` contains the opening brace and first
three fields, but no closing brace. At `0x4202BBA3`, the code skips the
original body's opening brace, then joins the prefix and remainder using
`%s,%s` (DROM `0x3C14EF44`). Thus the wrapper neither nests the original
payload nor signs its complete JSON text. The message-47 path uses the body
pointer directly (`0x4202BB21`), unlike special cases for messages 6, 39, 50.

## Signature algorithm and private inputs

Let `D` be the configured device-name string and `T` be the timestamp:

1. `T = time(NULL) * 1000`, represented as an unsigned decimal integer.
   The clock call is at `0x4202B6F9` through `0x4202B70D`; it has
   millisecond units but whole-second resolution. The time wrapper at
   `0x4211FF88` returns seconds, not the fractional component.
2. The exact signed bytes are ASCII `D + "&" + decimal(T)`. Format
   `%s&%llu` is DROM `0x3C14EF04`, used at `0x4202BA6A` through
   `0x4202BA78`.
3. The HMAC key is a firmware-resident format string with its `%s` replaced
   by `D`. That format is at DROM `0x3C14EF0C`, referenced by literal
   `0x42002E74` and used at `0x4202BA86` through `0x4202BA91`.
   It contains a private suffix, deliberately not reproduced here.
4. Compute HMAC-MD5 using that key and the signed bytes, then encode the
   **16 raw digest bytes** with standard padded Base64. This result becomes
   the JSON `key` field.

Evidence for step 4 is the call to `_bd_http_hmac_md5_encoding`
(`0x4202B5A4`) at `0x4202BABA`. The underlying routine at `0x420AA57C`
constructs 64-byte inner/outer pads with XOR constants `0x36` and `0x5C`,
performs the nested MD5 hashes, and returns 32 hex characters. The wrapper
converts those hex characters back to 16 bytes at `0x4202B652` through
`0x4202B65E`, then calls the Base64 encoder at `0x420B3D28` via
`0x4202B68A`. Its padding assignments use ASCII `=` at `0x420B3E50`
and `0x420B3E57`. This is not Base64 of the 32-character hexadecimal digest.

The signed input does not include the MAC, model, version, URL, HTTP method,
or body serialization. This describes the client code only; it does not
establish the server's independent checks or current acceptance rules.

## Configuration mapping and endpoint

The configuration descriptor table is at `0x3FC9F018`, with 36-byte
entries. Its embedded names and lengths identify these slots:

| Slot | NVS key | Struct size | Relevant field |
| --- | --- | ---: | --- |
| 1 | `gw_app_info` | 224 | Host/port string begins at `+64` |
| 5 | `gw_region` | 8 | Availability flag `+0`, selected region index `+1` |
| 15 | `gw_dyn` | 294 | Device name begins at `+22` |

`0x4201DF80` is the common config accessor; mode 2 copies the descriptor's
cached bytes to the caller (`0x4201E23D` through `0x4201E246`). Descriptor
lookup is `0x4201C344`.

For message 47, `0x4202BA4E` calls the region/identity getter
`0x4201E510`. That getter checks slot 5, then calls `0x4201C6C4`, which
uses `0x4202A8F4` to read slot 15. The source string at `gw_dyn+22`
is copied to getter-output `+20` (`0x4201C72E` through `0x4201C737`).
The signer copies getter-output `+20` at `0x4202BA51` through
`0x4202BA5F`. These two offsets must not be confused. The check at
`0x4202A894` categorizes another field; it does not decrypt or modify the
device-name bytes.

For the URL, `0x4202BC79` through `0x4202BC80` reads slot 1. At
`0x4202BCEF`, `+64` is passed to the host/port parser `0x4201DA48`.
It splits on a colon, copies the host, and parses the supplied port as an
integer. `0x4201D9CC` maps paired HTTP/HTTPS service ports:

- For explicit ports greater than 2000: HTTP uses that port; HTTPS uses
  that port minus 1000.
- For explicit ports greater than 1000 and at most 2000: HTTPS uses that
  port; HTTP uses that port plus 1000.

The URL scheme helper `0x4202AEC8` maps mode 2 to `https`, otherwise
`http`. Message 47 uses mode 2 for early attempts (retry counter less
than 3, `0x4202BCC2` through `0x4202BCE1`); later retries can select HTTP.
An off-device read-only reproduction should use HTTPS only, not emulate
this downgrade behavior or probe the separate private-LAN fallback.

The separately retained, CRC-checked `gw_app_info` host field was consumed
privately and matched **region3.homgarus.com with HTTPS port 1446** using
the above mapping. This establishes the endpoint from saved configuration
and code, rather than combining unrelated observations. It does not prove
the host's present availability or trust state.

## Private offline preparation and limits

An untracked helper in `/private/tmp/rainpoint_stock_update_request.py`
reads only the retained configuration export and stock application, and
offers `build_request()` to generate a fresh descriptor in memory or
`save_request()` to write a mode-600 descriptor. It contains no network
client and prints no device name, MAC, key, signature, or body. The prepared
descriptor is `/private/tmp/rainpoint-stock-update-request.json` and must
remain private. Generate a fresh timestamp immediately before any separately
authorized request; the prepared file is not a replayable long-lived token.

The helper asserts the saved hostname, HTTPS port, blob sizes, and string
encoding, then uses model code 289 and version 1.1.1040 as independently
confirmed by the main investigation. It does not infer the model from the
ESP-IDF project string. The MAC is read privately from retained `cal_mac`.

The approved query's response and helper copies are retained privately under
`captures/stock-hub-firmware/vendor-lookup-20260927-e1tfi667/`; its `analysis/`
directory includes the narrow metadata export and three helpers. The helpers
retain their original temporary input paths; reproducing offline construction
requires explicitly selecting the retained inputs, not replaying an old signed
request. NVS export checked entry and blob CRCs using the
[IDF NVS layout](https://docs.espressif.com/projects/esp-idf/en/v5.1.6/esp32s3/api-reference/storage/nvs_flash.html).
No secret values are documentation dependencies.

Any further metadata query/download remains a separate action requiring the
applicable authorization. Do not invoke the hub's update-check callback: its success path
can start OTA. A successful off-device response would still require careful
model, version, image integrity, and publisher/provenance checks; obtaining
an image is not authorization to install it.
