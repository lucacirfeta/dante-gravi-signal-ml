# DANTE 3.8.0 archival release checklist

Status: **PREPARED; PUBLICATION REQUIRES HUMAN CHECKPOINT**

This checklist creates a new immutable software version without moving the
historical `3.7.0` or `dante-workflow-productization-v1` tags. It does not
authorize a GitHub Release or Zenodo publication.

## Frozen release identity

- version: `3.8.0`
- proposed tag: `v3.8.0`
- repository: <https://github.com/lucacirfeta/dante-gravi-signal-ml>
- related architecture preprint: <https://arxiv.org/abs/2609.08695>
- license: `GPL-3.0-only`
- historical 3.7.0 version DOI: `10.5281/zenodo.21912589`
- Zenodo concept DOI: `10.5281/zenodo.20121859`
- 3.8.0 version DOI: **not yet reserved**

If publication occurs after 2026-09-09, update `date-released` and the
changelog date before building or tagging.

## Pre-tag gate

- [ ] Merge the reviewed release branch into `main`.
- [ ] Confirm local and remote `v3.8.0` tags do not exist.
- [ ] Confirm tracked files are clean at the selected `main` commit.
- [ ] Confirm `pyproject.toml`, `CITATION.cff`, README, release notes, and
      license all agree on version and license.
- [ ] Run the Windows and WSL workflow regressions.
- [ ] Build wheel and source distribution from the selected commit.
- [ ] Inspect both archives and install the wheel in a fresh Python 3.11
      environment.
- [ ] Run the bounded public CPU smoke and verify hash-checked reuse.
- [ ] Recheck GitHub-hosted CI on the selected commit.

## DOI-before-tag sequence

To keep the immutable tag self-describing, create a draft **new version** of
the existing Zenodo concept record and reserve its version DOI before tagging:

1. Open Zenodo record `21912589` and choose **New version**.
2. Keep the draft unpublished and reserve its DOI.
3. Replace the pending DOI marker in `CITATION.cff`, README, and these release
   notes with that exact version DOI.
4. Re-run metadata validation, archive builds, install checks, and tests.
5. Commit the DOI-only metadata change and obtain final human approval.

Do not enable a second automatic GitHub-to-Zenodo deposit for this tag if the
new-version draft is being managed manually; that could create a duplicate
record.

## Publication checkpoint

Only after explicit approval:

- [ ] create annotated tag `v3.8.0` on the verified `main` commit;
- [ ] push only that tag;
- [ ] create the GitHub Release using `DANTE_3_8_0_RELEASE_NOTES.md`;
- [ ] upload the exact source archive and optional built distributions to the
      reserved Zenodo draft;
- [ ] verify archive hashes and metadata against the GitHub release;
- [ ] publish the Zenodo version;
- [ ] verify DOI resolution and record the final URLs and hashes.

## Stop conditions

Stop without tagging or publishing if a test fails, metadata diverges, an
artifact hash changes unexpectedly, the reserved DOI differs from tracked
metadata, or the selected commit contains unreviewed scientific changes.
