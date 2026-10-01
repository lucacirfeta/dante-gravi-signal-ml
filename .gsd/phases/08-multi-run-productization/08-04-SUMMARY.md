---
phase: 08-multi-run-productization
plan: 04
completed_at: 2026-10-01
scope: native_interface_synthetic_only
overall_multi_run_productization_complete: false
---

# Summary 08.04: native O3a interface, public activation gated

| Task | Result | Local commit |
| --- | --- | --- |
| 1: actual native CLI/config/receipt interface and synthetic integration | VERIFIED | 138ed7c |
| 2: side-effect audit and remaining activation gates | VERIFIED | Documentation checkpoint |

Nine existing native CLI interfaces retain exact run/verify selectors and
path-only arguments. Each requires its actual leaf contract; v2 O3a H1/L1
metadata is mandatory. Nested cohort summary seal and exact ledger SHA/path
checks replace the incompatible flat O4a receipt assumption. Native calibration
is a distinct frozen selector stage. Scientific values/methods are unchanged.

Shared-controller adoption/release verification is exercised using synthetic
temporary evidence and a fake runner. Adapter factory/registry remain unchanged
and block O3a activation; no productive command or historical verifier ran.
The fixture's native subgraph is not a complete production graph or a scientific
applicability decision.

Windows controller 269 PASS; WSL 268 PASS/one Windows-only skip, both observed
OS exit 0. Final post-freeze adapter 45 PASS; Ruff lint/format PASS. Initial
expected missing-module TDD error, unbound fixture SCAN inputs and API wrapper
assertion corrections are recorded in JOURNAL; no schema gate was weakened.

Audit identifies missing autonomous initial acquisition/acceptance verifier
CLI, existing compact/summary writes during native verification, and per-stage
preflight/parent gates needed for clean execution. These must be bound before
public activation/adoption; source-hash checks do not substitute for numerical
verification. No initial/new-run/V1 method or completed O3a diagnostic finding
was changed. No push/release; user files preserved.
