# Frozen primary calibration input readiness - 2026-10-02

Common software gate after08.24; O3a diagnostic science remains closed.
No calibration, score reuse, threshold fit or new scientific selection is run.

## Operator boundary

`calibration-readiness` requires explicit registered run/detectors. Profiles
without an audited calibration binding stay blocked, with no O4a fallback.
It constructs no workflow ledger or worker. A missing manifest interval is
not skipped and not fetched automatically: an acquisition receipt path and
explicit exact SHA must be supplied together.

```text
python scripts/run_dante_workflow.py calibration-readiness --observing-run O4a --detectors H1 L1 --acquisition-manifest <absolute-path> --acquisition-sha256 <exact-file-SHA>
```

This binds the same protocol file SHA/seal as input-readiness, the full frozen
historical HDF5 inventory and original legacy GPS decoder source. Historical
GPS dataset values and score dataset shapes are inspected, not numeric score
values. Whole-file SHA necessarily reads container bytes, including encoded
score bytes, but does not decode/reuse them. The score-containing historical
full-row JSONL digest is explicitly NOT recomputed or declared verified.

The generic inspector independently checks exact corrected context geometry,
detector-local manifest coverage and frozen coverage/context/session counts.
For gaps it checks the acquisition receipt's explicit file SHA, parent,
canonical seals, exact required interval set, declared sampling metadata and
all acquired file SHA/size. Receipt and source bytes are rechecked at the end.
The receipt's own self-seal alone is insufficient. No raw sample values,
sensor safety, physical coupling, public/live coverage or runtime equivalence
are measured. Hash observations are not atomic or under writer exclusion.

## Restoration of historical inputs

The original84 listed `data/production/.../novelties_*.h5` were absent from
the checkout. The obvious archive
`E:\dante_archive\o4a_project_outputs_20260918` contained all84 exact matches
to the frozen inventory. Only these absent paths were copied back after full
SHA verification; every destination SHA matched. No existing file was
overwritten, no other archive file was restored and the archive is untouched.
Restored files remain unversioned historical identity inputs, not active
calibration results. Score reuse remains prohibited by the existing contract.

## Verification

Source freeze `52780ff6ad5af21e5e2a24aaa0c6a98a72102449`.

- 31 new tests. Focused Windows115 PASS/6.05s and WSL115 PASS/9.84s.
  Final seventeen-file common suites: Windows349 PASS/49.36s;
  WSL348 PASS/one Windows-only skip/123.13s. Post-freeze WSL111 PASS/37.78s.
  All software test commands observed OSexit0. Ruff5 files lint/format PASS;
  bare common import without scientific reader loading PASS.
- The one standalone real inspection with the explicit acquisition pin stopped
  with WORKFLOW_ERROR/InputPreflightError, observed host OSexit1: the first
  referenced raw file is absent. No PASS was produced and no guard bypassed.
  Read-only inventory diagnosis confirms all28 acquired files are absent.
- A separate metadata-only diagnosis reports39971 identities,19715H1+20256L1,
  84 source files and28 missing manifest intervals. Its explicit status is
  BLOCKED_CALIBRATION_SUPPLEMENT_REQUIRED, coverage/scientific readiness=false,
  nonzero host exit. The guest's blocked exit was not separately captured.
- Source inventory digest remains
  `d36a85138926d0ac2fc99ab9193f74607aa3851eb3317138b09cd186569b6d00`.
  Original protocol and three historical scientific EOL-qualified source SHA
  values are unchanged. Existing productive/retained commands remain intact.

## Real input blocker

The existing receipt is
`E:\dante_cache\dante_light\o4a_corrected_v2\inputs_326495389f511b378c52b2a99f7771bd13d87d6852d4191a4f0fb61d6842d4fa\acquisition_manifest.json`,
SHA `4f0732510604583e8a02827d3172e337cedd714ed3e8d3b86dfaac6c17b7fe78`.
Its missing_calibration files are absent (0/28 present). The bounded search
found no missing_calibration HDF5 in the existing corrected-O4a acquisition
root and no relevant copies in the obvious September18 archive. No broad
drive search, network fetch, file deletion or automatic receipt refreeze ran.

Software implementation passes; real calibration input admission is BLOCKED.
The old receipt cannot stand in for missing bytes. A recovery/acquisition
preflight needs author direction; if reacquired bytes differ, provenance must
be reviewed explicitly and a new transport receipt frozen before admission.
Do not silently replace hashes or grant scientific readiness. No push/release.

## Next gates

`PASS_CALIBRATION_DECLARED_INPUTS_ONLY` establishes primary calibration
metadata/byte coverage only. It leaves native calibration, actual raw sample
validity, current scientific runtime/source preflight and clean-install
raw-to-result numerical reproducibility open. Other-run/V1 qualification and
activation require their own contracts. No productive/retained stage command,
scientific config/source, DQ policy or registry binding changes here.
