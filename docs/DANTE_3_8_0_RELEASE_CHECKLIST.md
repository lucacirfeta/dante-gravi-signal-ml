# DANTE 3.8.0 archival release checklist

Status: **TAG, GITHUB RELEASE, AND ZENODO VERSION PUBLISHED; ZENODO VERIFIED;
LIVE GITHUB DESCRIPTION UPDATE PENDING**

This checklist records the completed immutable software release without moving
the historical `3.7.0` or `dante-workflow-productization-v1` tags.

## Frozen release identity

- version: `3.8.0`
- proposed tag: `v3.8.0`
- repository: <https://github.com/lucacirfeta/dante-gravi-signal-ml>
- related architecture preprint: <https://arxiv.org/abs/2609.08695>
- license: `GPL-3.0-only`
- historical 3.7.0 version DOI: `10.5281/zenodo.21912589`
- Zenodo concept DOI: `10.5281/zenodo.20121859`
- 3.8.0 version DOI: `10.5281/zenodo.22681395` (published)
- published Zenodo record: <https://zenodo.org/records/22681395>
- published GitHub Release:
  <https://github.com/lucacirfeta/dante-gravi-signal-ml/releases/tag/v3.8.0>
- release commit: `94a39f9b7b34660918efa4156eafb22d3c831ad7`

If publication occurs after 2026-09-10, update `date-released` and the
changelog date before building or tagging.

## Pre-tag gate

- [x] Merge the reviewed release branch into `main`.
- [x] Confirm local and remote `v3.8.0` tags do not exist before tagging.
- [x] Confirm tracked files are clean at the selected `main` commit.
- [x] Confirm `pyproject.toml`, `CITATION.cff`, README, release notes, and
      license all agree on version and license.
- [x] Run the Windows and WSL workflow regressions.
- [x] Build wheel and source distribution from the selected commit.
- [x] Inspect both archives and install the wheel in a fresh Python 3.11
      environment.
- [x] Run the bounded public CPU smoke and verify hash-checked reuse.
- [x] Recheck GitHub-hosted CI on the selected commit.

## DOI-before-tag sequence

To keep the immutable tag self-describing, create a draft **new version** of
the existing Zenodo concept record and reserve its version DOI before tagging:

1. [x] Open Zenodo record `21912589` and choose **New version**.
2. [x] Keep the draft unpublished and reserve its DOI.
3. [x] Insert `10.5281/zenodo.22681395` into `CITATION.cff`, README, changelog,
   release notes, and release checks.
4. [x] Re-run metadata validation, archive builds, install checks, and tests.
5. [x] Commit the DOI-only metadata change and obtain final human approval.

Do not enable a second automatic GitHub-to-Zenodo deposit for this tag if the
new-version draft is being managed manually; that could create a duplicate
record.

## Publication checkpoint

Completed after explicit approval:

- [x] create annotated tag `v3.8.0` on the verified `main` commit;
- [x] push only that tag;
- [x] create the GitHub Release using `DANTE_3_8_0_RELEASE_NOTES.md`;
- [x] upload the exact source archive and built distributions to the reserved
      Zenodo draft;
- [x] verify archive hashes and metadata against the GitHub release;
- [x] publish the Zenodo version;
- [x] verify DOI resolution and record the final URLs and hashes.
- [ ] replace the reserved-DOI wording in the live GitHub Release description
      with the published DOI state.

## Published record verification

- Zenodo record `22681395` reports software version `3.8.0`, publication date
  `2026-09-10`, public access, Luca Cirfeta as creator, and the GNU GPL v3.0
  license selected as version 3 only.
- The DOI resolves to <https://zenodo.org/records/22681395>.
- The record contains the three release archives plus `RELEASE_MANIFEST.txt`
  and `SHA256SUMS.txt`.
- The archived wheel, source distribution, source ZIP, and release manifest
  reproduce every SHA-256 recorded in the published `SHA256SUMS.txt`.
- Related works identify the architecture and scientific preprints through
  `10.48550/arXiv.2609.08695` and `10.48550/arXiv.2607.18136`.

## Stop conditions

Stop without tagging or publishing if a test fails, metadata diverges, an
artifact hash changes unexpectedly, the published DOI differs from tracked
metadata, or the selected commit contains unreviewed scientific changes.
