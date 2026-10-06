# Agent release playbook

Use this procedure when preparing, signing, publishing or relabeling a RainPoint
Local release. Documentation is part of the release, not a follow-up task.
Publish verified artifacts from an identified source commit, with matching
installation instructions. Signing, publication and deployment are separate
actions; use the user's authorization for each.

## 1 Define the release

Read `AGENTS.md`, the current release notes and `PROJECT_ROADMAP.md`. Inspect
existing GitHub releases before choosing tags or asset names. Record:

- The release label/channel and components being released: firmware, gateway,
  integration or a matched stack.
- Each component version, proposed tags and source commit. Read versions from
  `firmware/rainpoint_bridge/version.txt`, `rainpointd_addon/config.yaml` and
  `custom_components/rainpoint_local/manifest.json`; their numbers are independent.
- Required companion versions, supported hardware, upgrade order and the
  evidence supporting new features.

A stack label such as Alpha 2 can name existing published versions without a
new firmware build or tag. A firmware-only release is not a HACS integration
release. For an integration-only release, use existing compatible signed
firmware and skip building/signing a new image.

**Done when:** the component/version/tag combination and scope are explicit;
existing artifacts and installed devices are accounted for.

## 2 Update documentation before freezing source

Include this pass in every public release, including maintenance releases.
Update applicable files and explicitly note unchanged items in the release PR.
Use candidate wording until publication succeeds; preserve the previous current
release links while the candidate is unpublished.

| Documentation | Required review |
|---|---|
| Release notes, such as `docs/ALPHA_2.md` | Label, component versions, downloads, changes, limitations, upgrade order and short tester instructions. Create a new note for a new stack label; keep previous notes historical. |
| `README.md` and `GETTING_STARTED.md` | Current release links/versions, support table, prerequisites and installation path. |
| `docs/ALPHA_BUNDLE.md` and `docs/TWO_ZONE_ALPHA_TESTING.md` | Asset names, pinned source, OTA staging, gateway-first updates and relevant testing steps. |
| Gateway/firmware guides and `rainpointd_addon/CHANGELOG.md` | Changed capabilities, options and release status; remove superseded setup restrictions. |
| `PROJECT_ROADMAP.md` | Completed work and remaining qualification, using this sole live checklist. |

For HACS changes, also review `docs/HACS_DISTRIBUTION_REQUIREMENTS.md`. Keep
automated/replay evidence distinct from physical results. Ask testers to use
dry valves or visually verify opening and closing; retain default HA
notifications and optional phone forwarding. Add only tests warranted by the
change, not a new mandatory soak or per-user experimental unlock.

Check local links, anchors, component-version consistency and `git diff --check`.
Check the actual archive contents against the documented downloads: root docs
are not automatically included in `rainpoint-source.tar.gz`, and the radio ZIP
has an explicit documentation list in `tools/package_alpha.py`. Include the
release note and needed install/test instructions in the published assets or
provide working links to them at the release source tag.

**Done when:** every applicable documentation row is updated or explicitly
reviewed as unchanged, and users have a complete install/update path.

## 3 Validate and freeze the candidate

Run the validation commands in `AGENTS.md` with the required permissions.
Check CI for the exact candidate, including Python/native tests, firmware
boundaries, container, HACS/hassfest and clean HA Core qualification as applicable.
Run the existing source-package smoke test and public-artifact checks; reference
[bundle preparation](ALPHA_BUNDLE.md#maintainer-preparation-source-checkout).

Commit runtime and candidate documentation together, review and merge through
the repository's normal process. Record the immutable merged SHA used for
signing and packaging. Resolve unrelated local changes separately; keep private
captures, credentials and installation data out of commits and assets.

**Done when:** required checks pass for the identified source, documentation
is included, and the release candidate is committed and traceable.

## 4 Prepare and verify signed firmware when needed

Follow [firmware signing](FIRMWARE_SIGNING_DESIGN.md#protected-github-release-workflow).
For public firmware use the production profile of `sign-firmware.yml` on
protected `main`; verify the run resolves to the candidate SHA. Development
builds use the separate development workflow/key and remain unpublished unless
separately authorized for their intended audience.

Identify the signing run, profile, version and SHA for the user. Explicit chat
approval may be submitted through the authenticated GitHub review API using
the [chat approval procedure](FIRMWARE_SIGNING_DESIGN.md#release-approval-from-chat).
After signing, independently verify the downloaded image, signature, receipt,
version, SHA-256 and source commit with the pinned public key.

Package the verified application without rebuilding it. Verify all USB support
images against the same build receipt and check the partition layout and OTA
slot sizes. If the workflow artifact lacks support images, obtain the exact
receipt-matching bytes and verify them before packaging. Keep the signed
descriptor, OTA catalog, compatibility metadata and packaged source consistent.

**Done when:** the production image and all packaged inputs match their
receipts and source, with no private/development key or research probe in a
public production artifact. A successful signing run alone is not publication.

## 5 Publish the authorized release

Confirm publication authorization covers the identified candidate. Use unique
tags and assets; preserve previous release binaries and identities. Set the
intended prerelease/latest status, rather than relying on defaults.

Create the release with reviewed notes from step 2. Include the compatible
component versions, upgrade order, verified feature scope, known limitations,
source/tag links, checksums and tester guide. Publish HACS integration and
firmware releases separately when both are in scope; link them to each other.
Upload only the verified asset set and verify tag targets against the recorded
source, accounting explicitly for any reused firmware from another commit.

Download the published assets and compare their sizes/digests with the staged
copies and `SHA256SUMS`. Confirm the integration tag's manifest version and
the firmware release's compatibility metadata. An upload response is not
readback verification.

**Done when:** intended releases are public, tags and component versions are
correct, and every published asset matches the verified staged copy.

## 6 Finish the publication documentation

Replace candidate wording with the actual published label, URLs and dates.
Update the current-release pointers in README/setup/bundle/testing guides,
date the relevant changelog entries and mark publication complete in the
roadmap. Keep previous releases explicitly historical. GitHub release titles
and bodies must agree with repository documentation.

Commit and push this publication record, then report whether its PR is merged
or still open. Documentation-only corrections do not require rebuilding or
replacing released binaries: retain their original source SHA and distinguish
it from the newer documentation commit. Update approved release display text
when needed while preserving tags and assets.

**Done when:** current public instructions and release pages agree, downloaded
instructions point to usable information, and publication documentation is
committed/pushed with its merge status reported.

## 7 Deploy only within the approved scope

Publication does not install anything. When deployment is authorized, back up
live HA configuration, let watering finish and update the compatible gateway
before radios. Confirm its running version first. Update the integration
separately, preserve existing OTA offers, and update one radio at a time using
the [OTA procedure](ALPHA_BUNDLE.md#routine-updates-after-all-components-support-tls-and-signed-ota).

Confirm authenticated reconnection, healthy OTA completion and restored
ownership/counters. A completed transfer is not a healthy boot. Keep working
associations; perform only authorized control tests and report their actual
results. Record deployment evidence in the roadmap and relevant validation
document without presenting one installation's result as universal support.

**Done when:** approved targets are verified and recorded, or no deployment
was requested. Unapproved targets remain unchanged.

## Release handoff

Report the release label and component versions, download/guide links, source
SHA, validation/readback result, documentation commit/PR status, and what was
actually deployed. If any completion criterion is unmet, identify that step
instead of reporting the release process complete. Keep the handoff concise;
the roadmap holds remaining work.
