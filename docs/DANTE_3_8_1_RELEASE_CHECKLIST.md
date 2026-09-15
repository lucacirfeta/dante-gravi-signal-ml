# DANTE 3.8.1 provenance release checklist

Status: **DOI RESERVED; RELEASE CANDIDATE VERIFIED; TAG AND PUBLICATION PENDING**

## Frozen release identity

- version: `3.8.1`
- proposed tag: `v3.8.1`
- release purpose: append-only provenance transparency and compact rerun evidence
- canonical rerun commit: `cf774dd059e5b26da205e5abed3073d574e53c30`
- previous version DOI: `10.5281/zenodo.22681395`
- Zenodo concept DOI: `10.5281/zenodo.20121859`
- 3.8.1 version DOI: `10.5281/zenodo.22763556` (reserved, not published)

## Verified scientific boundary

- [x] Complete frozen `COHORT -> ... -> COMPARE` rerun finished.
- [x] Final status is `PASS_VERIFIED_CANONICAL_FINAL_COMPARISON`.
- [x] Scientific outputs are byte-identical to retained corrected-O4a outputs.
- [x] No scientific parameter, population, threshold, validation rule, or claim
      changed.
- [x] The unrecoverable historical source bytes are not represented as recovered.
- [x] Superseded and failed attempts remain in the append-only audit trail.

## Prepared release material

- [x] Transparency note completed.
- [x] Release notes prepared.
- [x] Claim-to-artifact map prepared.
- [x] Deterministic compact evidence-bundle builder added.
- [x] Bundle integrity and reproducibility tests added.
- [x] Canonical-provenance JSON checkout bytes pinned to LF across Windows and
      WSL.
- [x] Reserve the 3.8.1 DOI in a new-version Zenodo draft.
- [x] Update `pyproject.toml`, `CITATION.cff`, README, changelog, installation
      guide, and metadata tests to version 3.8.1 and the reserved DOI.
- [x] Build wheel, source distribution, source ZIP, compact evidence ZIP,
      `RELEASE_MANIFEST.txt`, and `SHA256SUMS.txt` from the selected clean commit.
- [x] Verify archives, fresh installation, public smoke, metadata, and checksums.

## Release-candidate verification

- Windows workflow, artifact, and bundle regressions: `134 passed`.
- WSL workflow, artifact, and bundle regressions: `133 passed, 1 skipped`.
- WSL Ruff: PASS.
- `CITATION.cff` YAML parse and frozen metadata assertions: PASS.
- Wheel and source-distribution metadata: version `3.8.1`, license
  `GPL-3.0-only`; archive layout checks: PASS.
- Fresh Python 3.11 wheel installation with the optional UI: PASS;
  `dante-workflow --help` and `dante-workflow-ui --help`: PASS.
- Bounded public CPU smoke: `PASS_TECHNICAL_SMOKE`, run key
  `5f007b192bb6cb95a23c1539d3b7604d4c9d6189387e31130651be5c2c6d6c4e`.
- Immediate hash-checked smoke reuse: `SKIPPED_VERIFIED_TECHNICAL_SMOKE`.
- Compact evidence manifest: 10/10 canonical stages,
  `BYTE_IDENTICAL_SCIENTIFIC_OUTPUTS`, `scientific_change=false`.

## Publication checkpoint

Do not tag or publish as part of release preparation. After artifact review and
explicit user confirmation:

1. create annotated tag `v3.8.1` on the verified `main` commit;
2. publish the GitHub Release with `DANTE_3_8_1_RELEASE_NOTES.md`;
3. upload the exact archives, evidence bundle, manifest, and checksums to the
   reserved Zenodo draft;
4. publish the Zenodo version and verify DOI resolution;
5. add minimal links from affected public records where editorially possible.

The last step is a transparency cross-reference, not republication of the
scientific or architecture manuscripts. Any arXiv or forum edit remains a
separate human-controlled action.

## Stop conditions

Stop if any artifact differs scientifically, a hash or run identity fails, the
reserved DOI differs from tracked metadata, source is not tracked-clean, or a
release step would overwrite a historical record.
