---
phase: 07-o3a-transfer-readiness
plan: 21
verified: 2026-09-27
status: passed
score: 5/5 must-haves verified
is_re_verification: false
---

# O3a-only PEM verification

| Must-have | Status | Evidence |
| --- | --- | --- |
| O3a-only diagnostic boundary | VERIFIED | Contract and compact receipt state no O4a comparison, global significance, astrophysical confirmation or A2 promotion. |
| Exact frozen target selection and separate populations | VERIFIED | Standalone verifier exit 0; 11 ROBUST primary plus one AMBIGUOUS diagnostic in separate sealed JSONL outputs. |
| Five public channels per detector and excluded high-FPR channels | VERIFIED | Contract channel list and verifier source/contract replay; event outputs contain five detector-local channels. |
| Frozen method, O3a-only null and candidate exclusion | VERIFIED | Method-reference hash, event calibration receipts and 8,900-row classification exclusion validated by preflight and standalone verifier. |
| Complete sealed run and cache cleanup | VERIFIED | `PASS_COMPLETE_O3A_NATIVE_PEM_V1`, `PASS_VERIFIED_O3A_NATIVE_PEM_V1`, no failure, empty stderr and transient raw cache. |

Artifacts are substantive and wired: versioned config, O3a adapter, runner,
synthetic tests, 12 event JSONs, 12 null calibration JSONs, primary/diagnostic
JSONL ledgers and compact receipt. The runner's standalone verifier reopens
parents and output files; it does not independently repeat NDS2 acquisition or
the full coherence/null computation. Real NDS2 service behavior beyond the
sealed run is therefore not asserted as independently reproducible here.

No new blocker was found for this O3a-only stage. The separate O4a
`.gitattributes` provenance-policy regression failure remains open and was
not part of this verification. The COUPLED H1 result is diagnostic only.
Post-run WSL O3a/PatchProducer regression passed 194 tests with 11 upstream
warnings; Ruff passed.
