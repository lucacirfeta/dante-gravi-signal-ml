---
phase: 08-multi-run-productization
plan: 03
verified: 2026-10-01
status: passed
scope: schema_administrative_only
score: 5/5
is_re_verification: false
overall_multi_run_productization_complete: false
---

# Verification 08.03: schema boundary, not new science

| Required truth | Status | Evidence |
| --- | --- | --- |
| V1 semantics and frozen O4a contract preserved | VERIFIED | Old v1 schema/controller suites green, exact15-stage/key-set checks retained; config diff empty, checkout matches Git after exact LF-to-CRLF reconstruction |
| V2 binds an entire per-profile graph | VERIFIED | Common loader wired to schema_v2; exact file SHA plus independent seals and full stage-array equality |
| Scope mutations and missing parent/hash gates fail closed | VERIFIED | Re-signed mutations, native-reference/generic-DAG/policy negative tests; O4a run/detector and short-graph rejection |
| Unsupported adapters remain blocked before state | VERIFIED | Synthetic non-O4a graph parses but factory rejects; no cache/ledger created |
| No productive run or scientific-method change | VERIFIED | Test fixtures only; no production profile binding, scientific config/scripts/src/dante_light/data diff empty |

## Observed checks

- Full native Windows controller: **224 passed**, OS exit 0, 35.37s.
- Full WSL controller: **223 passed, 1 skipped**, OS exit 0, 115.79s.
  Skip is the existing Windows-specific no-signal regression, not a v2 skip.
- Post-feature-freeze schema-v2/v1/run-profile tests: **112 passed**,
  OS exit 0, 3.90s. The new v2 suite contributes 56 tests.
- Ruff lint: modified schema, new v2 module, modified O4a adapter and new tests
  PASS. New module/test format PASS. Existing scientific files not reformatted.
- Initial TDD 27 FAIL/12 PASS is recorded, not substituted for final evidence.
  Native Ruff failed solely because that environment has no Ruff module;
  existing WSL Ruff passed without dependency installation.
- `git diff --check`: PASS. Feature source freeze `b9cbbc1`.
- Frozen config/scripts/src/dante_light/data: no changes. Frozen O4a contract
  checkout SHA 7148db11ea455ff97319ac763ca420874711d3e5dcaea6f7968f85df01a75e06;
  Git blob SHA 9ad4286b08a611c18cc73a4493fa47ac57e052d1a4048c0be0b456b4b36c0c70.
  Exact LF-to-CRLF reconstruction true; raw-byte Git equality false, qualified.

## Wiring and limits

`load_workflow_spec` performs v2 dispatch into substantive `schema_v2` validation;
returned immutable GraphProfile metadata reaches the existing O4a constructor
and exact adapter factory. Synthetic full O4a v2 preserves its command templates
but produces a new workflow/run identity. V1 callers retain default graph_profile
  None and their historical contract semantics.

No production O3a profile/adapter, numerical receipt replay or full multi-run
GUI binding is claimed. Source checks are administrative, not empirical strain
validation. Existing UI launch timing risk remains as qualified in08-01; this
turn's green full suites do not demonstrate a repaired root cause. No push,
release, new scientific default, Virgo null or historical rewrite.
