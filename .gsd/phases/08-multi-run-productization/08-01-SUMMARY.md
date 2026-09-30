---
phase: 08-multi-run-productization
plan: 01
completed_at: 2026-09-30
scope: administrative_foundation_only
---

# Summary 08.01: explicit public-run/detector profiles

## Results

Author confirmed all public H1/L1 runs and V1 where publicly available. One
content-addressed registry covers S5/S6/O1/O2/O3a/O3b/O4a/O4b in that scope.
Availability is separate from approved numerical method and executable
workflow. V1 is not silently dropped, substituted or assigned LIGO thresholds.

Real shared CLI exposes `runs`, `run-readiness`, `--observing-run`, `--detectors`
and `--run-registry`. Blocked selection fails before cache/ledger/worker
creation. Equivalent O4a selection preserves the legacy plan and run identity.
Common CLI/UI construction dispatches the named implemented adapter; unknown
adapters are not O4a. Full O3a adapter and multi-run GUI are still pending.

## Completed tasks

| Task | Description | Commit | Status |
| --- | --- | --- | --- |
| 1 | Registry, selection and complete adapter-dispatch boundary | 8d29136 | VERIFIED |
| 2 | Scope, verification, investigation and state handoff | Documentation checkpoint | VERIFIED |

## Verification

WSL controller: 167 PASS/one Windows-only skip; Windows controller: 168 PASS;
native profile/process subset: 48 PASS. All observed exit 0. Ruff lint PASS;
format PASS for new profile/test modules and CLI. Real native profile binding
and blocked selection checked. No production scientific stage or outcome
opened. No old scientific constant, source, contract, raw file or artifact
changed; existing EOL qualifications remain.

## Deviations and concerns

- Catalogue/factory/CLI were kept as one vertical feature task because each
  imports the other boundary; avoids an intermediate broken import commit.
- Initial TDD collection failed before implementation, as expected.
- A parity test ran across a formatter/source change and therefore correctly
  produced different source-bound keys. Static-source reruns passed.
- Existing detached UI lifecycle regression exceeded its unchanged 15-second
  deadline twice, later passing in the complete suites. Git diff in the
  Windows-mounted WSL checkout was observed running around 12 seconds; differing
  inherited EOL interpretation is recorded, not silently normalized. Timing
  cause remains incompletely resolved and must be qualified before release.

## Next handoff

See docs/DANTE_WORKFLOW_MULTI_RUN_2026-09-30.md and 08-01-VERIFICATION.md.
Continue the existing O3a adapter and common selector under versioned contracts;
stop before any newly chosen scientific DQ/reference/calibration/network policy.
No push, merge or publication; this does not alter completed O3a findings or
claim that every publicly catalogued run is scientifically validated by DANTE.
