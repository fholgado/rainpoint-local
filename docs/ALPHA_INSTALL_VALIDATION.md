# Independent installation validation evidence

The single live checklist remains [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).
This document separates reproducible package checks from an actual new-user
installation. [Alpha 1](ALPHA_1.md) is available for external testing; publishing
it does not mark HACS, HA OS or radio adoption independently accepted.

## Automated evidence

- CI and `tools/package_release.py --smoke-test` extract only tracked runtime
  files into a temporary installation, start an empty gateway twice using its
  own SQLite store, check an empty device/registry response and reject an absent
  mutation credential. No household catalog, database or radio is contacted.
- `tools/package_alpha.py` consumes PlatformIO's real build receipt and validates
  firmware version, source commit, clean source, image digests, the four USB
  parts/offsets, both OTA slot capacities and production command boundaries.
  The committed-source 0.17.0 build produced the same application digest as the
  installed image; only packaging/build metadata changed, not RF logic.
- Local clean-source candidate bundles from commit `7062ad8` matched byte for
  byte across two runs. CI for that commit passed Python, firmware/package and
  container jobs. This proves package determinism for fixed inputs, not physical
  first-flash success or reproducibility of all compiler/toolchain versions.
- Distribution tests enforce a single `rainpoint_local` integration directory,
  required metadata, a nonempty maintainer, a separate cloud-independent domain,
  consistent HA version declarations and the alpha report template.
- Official HACS and hassfest checks passed on `6541df2` in
  [CI run 34467939697](https://github.com/fholgado/rainpoint-local/actions/runs/34467939697).
  Hassfest exposed an existing missing `network` dependency used by adoption,
  then incorrect manifest key ordering; both now have source/metadata regressions.
  This is integration-data validation, not a real HA setup/commissioning test.

## What these checks do not cover

September 11: a dedicated Colima ARM64 VM ran the existing
`tools/qualify_clean_ha.py` against HA **2026.7.0** and **2026.9.1**, using tracked
source from `d31b516`. Both passed real-Core authenticated TLS setup, duplicate
discovery, model menus, no-radio feedback, reload and removal. Resolved HA image
digests were `sha256:cb76c9922b530f6a5063a15463eb3ad6de287d297c826713abda16795bb98980`
and `sha256:612d76760b544cb40b7ba01387fdac964c59a6a550a50a4d30b4773c822d2918`,
respectively. The gateway used a new database and generated test credentials;
the container had no host mounts, privilege, USB devices, published ports or
outbound default route. The extracted-source package fresh/restart smoke and
the ten existing package/distribution tests also passed.

A separate fresh HA frontend serves its onboarding page (HTTP 200) through a
Mac-loopback SSH tunnel into the same isolated network. This is reachability
evidence, not a completed owner setup or rendered integration-flow check. See
[isolated HA testing](ISOLATED_HA_TESTING.md) for the procedure.

The automated Core test supplies a Supervisor-style discovery object; it does
not run Supervisor. No isolated HA OS or browser-control tool was available.
The manual form's missing TLS credential input is a source-level qualification
risk, not yet a reproduced browser result. These tests do not establish HACS
installation, frontend selectors, physical BOOT adoption, Wi-Fi commissioning or
valve pairing. The declared HA minimum now has Core-flow evidence, not complete
new-user acceptance. Do not use the configured house as independent-install proof.

The integration now includes original local `brand/icon.png` and `icon@2x.png`
assets with editable source and PNG structure/dimension regressions. Current
[HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/)
include brand assets. Official HACS and hassfest jobs are now configured in CI;
their results must be checked per revision. Metadata unit tests are not a
substitute for those validators or a real HACS install. Alpha testers should
select `v0.18.0-alpha.1` in HACS rather than the default branch or firmware-only
release. The gateway repository still follows `main`; verify its version against
the release combination or install the pinned source package.

On a new HA OS test instance, follow the getting-started guide with an empty
gateway, no copied credentials/IDs, a self-built node and each supported device
family. Capture versions, UI results, association ownership and physical outcomes
using the alpha issue form. Keep the tests dry until open and both stop modes
are independently observed. Record results in the roadmap rather than creating
another status list here.
