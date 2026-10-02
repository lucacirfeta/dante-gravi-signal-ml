---
phase: 08-multi-run-productization
plan: 24
status: passed_primary_manifest_coverage_only
---

# 08.24 verification: exact declared primary manifest coverage

## Observable truths and wiring

1. `InputCoverageBinding` has explicit immutable field mappings; default adapter
   capability is absent. No shared DQ/population/geometry defaults are supplied.
2. `inspect_input_coverage` checks parent binding and selected source/audit SHA,
   exact half-open context bounds and merged manifest coverage by detector.
   Full provider-row JSONL SHA/counts match the frozen profile, not a substituted
   or silently reduced population. Any mismatch fails, rather than skipping.
3. Corrected-O4a maps to its original selector and rejects another checkout's
   imported module. Its pinned source is checked before and after iteration.
   Unit wiring test denies protocol rebuilding; standalone real WSL replay
   checks all811251 original eligible identities, OSexit0 and matching SHA.
4. CLI resolves explicit registered run/detectors and invokes the inspector
   directly; tests fail if `_orchestrator` is constructed or fallback occurs.
   Bare common imports do not load the scientific selector.
5. The PASS is scoped to primary manifest GPS/context metadata, with raw,
   calibration, DQ eligibility, live coverage, runtime, writer exclusion and
   scientific execution explicitly false. Registry/scientific contracts,
   productive and retained execution remain unchanged.

Source freeze9fc224e. Windows318 PASS; WSL317 PASS/one Windows-only skip,
post-freeze WSL80 PASS; all final OSexit0. Ruff5 files lint/format PASS.
The first full WSL UI timeout, isolated unchanged PASS and successful full
repeat are retained explicitly in SUMMARY/checkpoint, not hidden.

## Open gaps

Manifest bounds do not attest file presence, sample grids/values, actual raw
validity or sensor safety. Frozen validity audit metadata is reused, not
recomputed. GPS coverage of calibration, numerical runtime/source closure,
bounded clean-install raw-to-result proof, other-run/V1 qualification and
scientific activation remain open. Observed hashes are not writer exclusion
or an atomic/global snapshot. No stub substitutes for these gates.
