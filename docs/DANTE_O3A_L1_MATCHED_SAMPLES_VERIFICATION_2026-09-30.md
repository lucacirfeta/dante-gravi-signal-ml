---
phase: O3a-local-L1-matched-native-inputs
verified: 2026-09-30
status: passed
score: 6/6
is_re_verification: false
gaps: []
---

# Matched native input verification

Goal: complete and independently replay the approved matched inputs without
opening local PEM outcomes or changing the scientific population/method.
The checkpoint plan is `DANTE_O3A_L1_MATCHED_SAMPLES_2026-09-30.md`.
No prior verification document for this gate existed.

## Observable truths

| Truth | Status | Evidence |
|---|---|---|
| Exact eligible controls; no rejected gap filled | VERIFIED | Sealed metadata/plan replay: 426 blocks, 1,278 contexts, 53 transport containers; synthetic adjacency/gap/exposure tests |
| Official strain for every used sample | VERIFIED | 20 official frame receipts and 54 full-span receipts; checksum, HDF5 metadata, sample geometry/digest replay in standalone verifier |
| Exact five native auxiliary channels and rates | VERIFIED | 265 control native files/receipts; 3,266,445,312 pre-header sample bytes; dtype/rate/finite/shape and numerical digest replay |
| Historical event input unchanged | VERIFIED | Five receipt-checked borrowed event files, exact source/identity/native numerical hash replay; no event fetch or historical write |
| Complete, fail-closed terminal run | VERIFIED | Acquisition exit OS 0, standalone verifier exit OS 0/PASS; no failure/partial/lock; empty stderr and no remaining controller |
| Source binding and outcome boundary retained | VERIFIED | 17 sealed source SHA match; 16 Git byte matches plus unchanged contracts.py EOL qualification; no real local outcome; first target INCONCLUSIVE, family two |

## Artifacts and wiring

The versioned transport contract, geometry module, productive CLI and
synthetic test file all exist, contain substantive implementations and are
wired. The CLI binds the verified metadata parent and exact official
manifest, uses the existing native acquisition and independent file replay,
and checks the entire planned receipt/file sets before accepting a summary.
It has no local coherence, reference-tail or bootstrap measurement path.

Run root:
`E:/dante_cache/dante_light/o3a_l1_local_followup_v1/matched_samples/samples_e55ae7830250617c9c9ece1e6984285ed249c73e38a4d44740be4e4c715d4c86`.
Source freeze: `3a9303e`. Summary seal:
`4e4c026972fadafb8ef931523960deeaf015c28fc06073e814d9ab08e506a3d9`.
Summary file SHA256:
`5f7372687efe0c302402e37b5da130a06edda04b140628b8c55572818dadbb73`.
Exit evidence was captured from sessions 51240 and 34719, not inferred from
summary text. Separate `worker.verify.*.log` files retain verifier output.

## Regression and anti-pattern checks

WSL local-follow-up/common-PEM/native-PEM/PatchProducer post-suite:
168 passed, 11 upstream warnings, 40.99 seconds, OS exit 0. Ruff lint/format
PASS. Synthetic checks reject altered bytes/summary, orphan/partial files,
an active lock, wrong identities/rates, failed reruns and gap stitching.
No missing, placeholder or unwired productive input path was found.
The existing contracts.py CRLF working bytes are exactly reconstructible
from LF Git bytes; this qualification is preserved, not silently normalized.

## Interpretation and later gates

No blocker remains for **local input integrity**. No human review is needed
to establish the programmatically checked byte/geometry/hash assertions.
This replay is not independent source reacquisition or evidence of safe
physical veto coupling. Sensor safety/physical attribution needs a separate
detector-expert review if a later exploratory screen is positive.
Gate C and all real local outcomes remain closed pending the measurement
adapter/input binding, synthetic tests, source freeze and independent
measurement verifier. This PASS is not a PEM association or discovery.
