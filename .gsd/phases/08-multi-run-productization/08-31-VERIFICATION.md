---
phase: 08-multi-run-productization
plan: 31
verified: 2026-10-03
status: passed
score: 4/4 scoped truths verified
is_re_verification: false
---

# 08.31 scoped numerical gate verification

| Truth | Status | Evidence |
|---|---|---|
| Driver-only drift requires fresh numerical gate, not exact version pin | VERIFIED | New opt-in policy, valid seals/types/other fields exact, observed runtime stable, refusal tests |
| Real admitted images feed unchanged offline encoder/index/scorer | VERIFIED | All28, full preprocessing receipt replay, source/artifact SHA, direct-forward exact tokens, configured K/batch |
| Scoring independently matches frozen formula tolerance | VERIFIED | NumPy float64 cosine/max/top-k/mean, maximum4.1391923610856196e-8 within existing2e-7/rtol0, no fit/label output |
| Fresh installed workflow reproduces entire evidence | VERIFIED | Installed43 source matches, actual outside-checkout invocationOSexit0, complete receipt byte equality |

Artifacts substantive/wired: module CLI -> explicit pinned policy/admission ->
existing provider/PatchProducer -> offline pinned model -> unchanged PatchScorer
-> independent CPU oracle -> sealed fresh receipt. Installed verifier recalculates,
compares all fields and refuses mismatch before writing. No stub or productive
factory redirection. The infinite threshold argument disables an unused API
label; it is explicitly NOT a decision threshold or candidate classification.

Checkout exec69168 / installed39683 OSexit0; receiptSHAe8aa81d7...,seal03617f6d....
Host279 and WSL279 PASS; post-freezeWSL102 PASS; Ruff lint/format PASS.
Qualified EOL reconstruction preserves actual frozen SHA, especially mixed
data_loader; no change/bypass to historical contracts or comparators. Initial
race/path/audit failures recorded and diagnosed, not omitted from checkpoint.

Limits: bounded primary28-context current-runtime proof, not historical
cross-driver score equality, full39971 calibration, native scorer certification,
all productive entrypoints, fully isolated science/clean clone, all-run/Virgo
readiness, O4b launch or a release. Those gates remain OPEN. Existing strict
historical runtime test incompatibility remains recorded in08.30, unchanged.
No astrophysical or statistical interpretation follows from this test.
