---
phase: 08-multi-run-productization
plan: 16
verified: 2026-10-01
status: passed_scoped_implementation
source_freeze: e9a256a
real_complete_chain_verified: false
---

# Verification 08.16: explicit driver metadata exception only

| Truth | Evidence and scope |
| --- | --- |
| Driver version alone may differ on opt-in | Separate helper validates both seals, normalizes one field, recomputes digest; 30 synthetic tests and real WSL runtime-only probe |
| Other checks and productive guard remain | Resealed package/OS/Python/Torch/device drift negatives; actual original productive loader rejects changed driver; no original source/config changed |
| All existing reader sites share the opt-in | Seven AST-checked runtime call sites, shared evidence; explicit CLI argument tests, default strict fixture regressions; not a positive historical chain certificate |
| Audit and mid-replay drift refuse | Policy SHA/final rehash, source bindings, current full runtime checked between parents and at final read-only unchanged check; receipt qualification copied defensively |
| Tested and source-bound before real retry | Broad WSL/Windows suites, post-freeze 40 PASS each, Ruff and byte/EOL audit; source freeze e9a256a before actual CLI retry |

WSL workflow + native contract/native PEM/PatchProducer: 992 PASS/7 skips/
11 upstream warnings, OS exit 0, 534.76s. Windows workflow + native contract:
758 PASS/220 platform skips, OS exit 0, 330.87s. Post-freeze qualification plus
native contract 40 PASS on each platform, OS exits 0, WSL5.10s/Windows5.60s.
Ruff lint and four-file format PASS. No full-repository/all-platform claim.

Twenty source-commit files byte-identical Git. Three old helpers remain exact
Git LF-to-CRLF reconstructions (contracts, physical coincidence, PEM coherence),
not byte-identical Git claims. Frozen runtime unchanged SHA3b00a0bf258cc96870971481138e10e7e85deb97a1c3c49c470626e3153d0ef2.

Actual retry, all explicit roots and opt-in: FAIL_CLOSED, CLI/OS exit 1. New
blocker: original persistent cohort run.lock versus blanket earlier `_clean`.
Producer code confirms cooperative flock release without unlink. Contract-derived
canonical path/marker probe and read-only historical flock probe both OS exit 0;
lock bytes/size/inode/mtime unchanged. That probe is momentary, not adoption or
ongoing writer exclusion. No new real snapshot/whole-chain scientific certificate.

Structural next decision: extend held read-only existing-lock handling to earlier
native ancestors, with producer-contention/inode/DrvFS tests and full-scope holds,
or preserve blanket refusal and defer the historical replay. No automatic guard
change/delete, producer invocation, measurement, source normalization or push.
