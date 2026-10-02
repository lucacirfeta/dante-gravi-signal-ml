---
phase: 08-multi-run-productization
plan: 25
status: blocked_missing_acquired_inputs
---

# 08.25: calibration input gate implemented; real inputs blocked

Source freeze52780ff6ad5af21e5e2a24aaa0c6a98a72102449,six exact staged files.
Common deny-default metadata/byte inspector, audited corrected-O4a reader and
calibration-readiness CLI. Explicit acquisition path/SHA, source inventory,
parent/canonical seals, exact interval set, declared sampling metadata and
acquired file SHA/size, final input/source/receipt rechecks. No state or worker.

Historical84 calibration HDF5 were absent; the obvious September18 archive
contains84 byte-identical frozen references. Copied only absent original paths
after full SHA validation; destinations verified, no overwrite/archive change.
These are original identity inputs only, not reusable calibration scores.
Reader decodes historical GPS with unchanged frozen geometry and inspects
score dataset shape only. Historical score-containing full-row digest is
explicitly unchecked; no substitute digest or numerical score reuse claimed.

## Software verification

- 31 new tests; focused Windows115 PASS/6.05s,WSL115 PASS/9.84s.
- Final17-file common suites Windows349 PASS/49.36s;WSL348 PASS/one Windows-only
  skip/123.13s. Post-freeze WSL111 PASS/37.78s; all final OSexit0.
- Ruff5 files lint/format PASS,bare dependency-light import PASS; scientific
  protocol and three historical qualified EOL SHA unchanged.

## Real verification and blocker

One post-freeze real invocation with SHA-pinned acquisition receipt observed
host OSexit1/WORKFLOW_ERROR: missing acquired HDF5. Read-only diagnosis confirms
0/28 physical files present; no copies under prior corrected-O4a acquisitions
or obvious archive. Existing receipt/hash preserved; no download or retry of
the failed byte gate. No PASS input receipt or scientific activation produced.
Separate metadata-only diagnosis:BLOCKED_CALIBRATION_SUPPLEMENT_REQUIRED,
39971 identities (19715H1+20256L1),84 sources,28 manifest gaps. Host exit nonzero;
guest blocked exit not separately captured. This is NOT an input coverage PASS.

## Deviations

Initial read-only probe stopped at the absent first historical input before
reading HDF5 datasets; bounded archive recovery restored exact84 references.
Initial lint unused import/fixture shadow corrected before tests. One source
search used a Windows glob argument and was corrected read-only. No scientific
source/config/selection/DQ/runtime change, score/outcome/raw numerical read,
productive job/network/GPU work, user-folder edit,push/main/release.

Next requires author direction for transport-only recovery preflight of28
raw inputs; never silently replace an old file hash with newly downloaded bytes.
Native calibration/runtime/clean-install numerical qualification remains open.
