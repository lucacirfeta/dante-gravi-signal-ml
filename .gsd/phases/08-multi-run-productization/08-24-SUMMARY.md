---
phase: 08-multi-run-productization
plan: 24
status: passed_primary_manifest_coverage_only
---

# 08.24: profile-specific primary GPS/context coverage

Author approved A: common engine, preserve approved selection per profile.
Added a deny-by-default coverage binding/inspector, explicit corrected-O4a
mapping and `coverage-readiness` CLI without orchestrator, state or worker.
Source freeze `9fc224e14f865b7b0fefc2516ed722eb7d8056c7`, six staged files.

The common inspector checks frozen contract/source/audit bytes, exact context
geometry, detector-specific union coverage, unique ordered identities and full
original canonical JSONL SHA/counts. Corrected-O4a supplies unchanged
`iter_scan_identities`; no protocol rebuild or additional CBC/DQ selection.

## Empirical verification

- 38 new tests: exact edges, stitching/overlap, true gaps, detector locality,
  corruption/order/count/digest, source/metadata drift, typed immutable
  selectors, fail-closed reads/integers and CLI no-state/no-fallback.
- Final sixteen-file common suites: Windows318 PASS/OSexit0/55.71s;
  WSL317 PASS/one Windows-only skip/OSexit0/138.47s.
- Post-freeze WSL input/coverage/CLI/packaging80 PASS/OSexit0/16.08s.
- Ruff five Python files lint/format PASS; base-package import without
  scientific selector loading PASS; scientific source/EOL SHA unchanged.
- One real post-freeze standalone WSL metadata-only replay OSexit0/PASS:
  H1=401442,L1=409809,total811251. Full original identity SHA
  `24d6a3f628f2ab9192e5a17f013ca6b20d6d8e7c47257027323520f7a101e20e`.

## Deviations and qualifications

First WSL full suite failed only the unchanged UI detached-launch 15s timeout:
316 PASS/one skip/one failure/OSexit1/144.86s. Read-only diagnosis and unchanged
isolated retry passed1/OSexit0/9.97s; full repeat passed as above. No timeout,
test or UI behaviour was changed; transient latency cause is not established.
Added fail-closed handling for unreadable inputs and lossy integer conversion
before final regressions. Two audit helper paths initially queried under the
wrong directory; resolved under pipeline_v2_production and SHA unchanged.
No scientific criteria, configs, original sources or population were modified.

`PASS_PRIMARY_SCAN_MANIFEST_COVERAGE_ONLY` is not a physical sample proof,
calibration coverage, complete public-run/live/DQ eligibility, runtime
equivalence, writer-exclusion receipt or scientific execution authorization.
Existing PREFLIGHT/registry/commands unchanged, no O3a reopening, productive
job, network/raw/calibration/outcome work, GPU change, push/main/release.
User untracked folders preserved. Next:calibration input coverage, then bounded
clean-install numerical execution; new run/V1 science needs separate review.
