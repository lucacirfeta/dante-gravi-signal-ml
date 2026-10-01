---
phase: 08-multi-run-productization
plan: 03
completed_at: 2026-10-01
scope: schema_administrative_only
overall_multi_run_productization_complete: false
---

# Summary 08.03: approved schema-v2 profile boundary

Author explicitly chose A. Shared loading now supports a separately versioned
workflow schema v2 with an exact file-hashed and canonically sealed per-profile
graph. V1's key set and frozen O4a fifteen-stage requirement remain intact.
Generic DAG, native parent/artifact gates and product policies stay fail-closed.
The O4a adapter rejects different run/detector scope or shortened graphs;
unsupported adapters remain blocked before state creation.

| Task | Result | Local commit |
| --- | --- | --- |
| 1: schema, adapter boundary and synthetic regressions | VERIFIED | b9cbbc1 |
| 2: decision resolution, evidence and scope handoff | VERIFIED | Documentation checkpoint |

Windows full controller 224 PASS; WSL 223 PASS/one Windows-only skip, both OS
exit 0. Post-freeze targeted 112 PASS, OS exit 0. Ruff lint/new-file format PASS.
New v2 tests comprise 56 cases. Initial TDD 27 FAIL/12 PASS was expected before
implementation. Native Ruff was unavailable; existing WSL tool used, no install.

No production profile/registry binding or O3a numerical adapter was created.
No scientific execution, download, outcome inspection, config/source change
within the scientific engine, historical artifact mutation, push or release.
Existing exact LF-to-CRLF O4a contract qualification and UI timing qualification
remain. User untracked directories are preserved. The completed O3a study is
unchanged. See 08-03-VERIFICATION and the dated schema-v2 guide.

Next: exact O3a applicable-stage/receipt mapping and adapter, with synthetic
boundary tests before independent historical verification/adoption. Do not
claim clean-install numerical replay or all-run scientific readiness from
these administrative tests.
