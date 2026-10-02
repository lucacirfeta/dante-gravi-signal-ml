---
phase: 08-multi-run-productization
plan: 23
status: passed_input_binding_only
---

# 08.23 verification: input binding only

## Observable truths

1. Common inspector retrieves no scientific defaults: adapter-selected field
   paths resolve to exact parent values. Three synthetic run/scope combinations
   use different declarations without fallback; not scientific certification.
2. Workflow file SHA, finite unique-keyed JSON and contract seal are checked;
   every selected reference SHA and checkout boundary is checked. Negative
   cases exercise missing/changed metadata, escaped paths, symlinks and drift.
3. No ledger or worker is constructed by the CLI. Real `input-readiness`
   reads five pinned metadata files/eight declarations and creates no cache.
   Explicit run/detectors are required; unbound O3a/O2/V1 stay blocked.
4. PASS explicitly leaves exact GPS/DQ/raw/runtime/writer-exclusion/scientific
   readiness false. It is neither a release receipt nor execution authorization.
5. Existing commands/configs/registry/frozen scientific helpers are unchanged.
   Fifteen-file Windows280 PASS/OSexit0 and WSL279 PASS/one Windows-only skip/
   OSexit0; Ruff lint/format five files PASS. The increment's bounded scope passes.
   Source freeze fd9e164; post-freeze WSL input/CLI/packaging42 PASS/OSexit0,
   standalone checkout command OSexit0/PASS and bare base-package import PASS.

## Artifact and wiring audit

- `input_preflight.py`: substantive inspector, strict parsing/hash checks and
  bounded report. No subprocess, network, numerical library or source reader.
- `StageAdapter.input_preflight_binding`: default denial; the corrected-O4a
  adapter explicitly names its current scientific contract fields.
- CLI: profile selection and schema loading occur before inspector, with no
  call to `_orchestrator`; actual CLI test fails if such a call occurs.
- 33 tests: boundary assertions, real metadata invocation and malformed cases.

## Open gaps

Actual GPS interval/sample-grid coverage, flag eligibility, context validity,
current scientific runtime/source verification and numerical raw-to-result
execution are not implemented by this metadata-only gate. Historical O4a
identity semantics and multiple DQ inventories cannot be silently generalized
to new runs. No stub is passed off as any of those gates.
