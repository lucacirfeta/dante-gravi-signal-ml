---
phase: 07-o3a-transfer-readiness
plan: 17
completed_at: 2026-09-24
---

# O3a native classification: verified execution

## Execution and results

Source/contract freeze committed and pushed in `03a38ab` before execution;
launch recorded in `84a7de4`. The --run process completed at 20:15:30
Europe/Rome on 2026-09-24. A separate --verify invocation completed at
20:20:13. Supervisor session 54398 returned both CLASSIFY_RUN_EXIT_CODE=0
and CLASSIFY_VERIFY_EXIT_CODE=0 (retrieved in the 20:48 status check).
Both stderr files are empty; no failure artifact is present.

| Detector | BACKGROUND | AMBIGUOUS | ROBUST | Total |
|---|---:|---:|---:|---:|
| H1 | 1070 | 263 | 2291 | 3624 |
| L1 | 1422 | 295 | 3559 | 5276 |
| Total | 2492 | 558 | 5850 | 8900 |

These are detector-local classes under the frozen CI boundary rule, not
astrophysical detections or globally significant results. Taxonomy,
coincidence, PEM and A2 promotion were not performed.

## Evidence identities

- Contract: `9aaeff60fd078538355d724f4102b39886dca97fef7474d394e2ee4109f5f1a2`.
- Run: `5cedef7de1c036f49a2c33acfeaa64198a67b31bed1c1109c6b34004faf6c044`.
- Run summary artifact: `24bfce9f2b7661ab5c4c9193d5d1200a9416df6d1704d8b80eadd7b91636c4e2`.
- Verified compact: `65d67d4c4dac2ff53893d3d23b3f308e5008c436b684a4247c8e927b662de3ac`.
- Output JSONL SHA-256: `88973cde9bf0c33307f320eab2cd8e6ca45a65dbcfaf2c04086c26ad8c3c0830`.
- Input JSONL SHA-256: `15b0e84ffc1fa04b5b2a5faf46b85d8fe48729e765ecf90286d083691f273c24`.

External results remain under `E:\dante_cache\dante_light\o3a_native_v1`;
the small verified receipt is versioned under
`artifacts/dante_light/o3a_native_v1/native_classification.json`.

## Validation

- Both invocations re-verified parents and recomputed native thresholds.
- The standalone verifier regenerated and compared all classified output
  bytes and the complete summary before issuing the verified receipt.
- Post-run read-only audit separately checked all 8900 source/output row
  pairs and recomputed labels without invoking the classifier: all original
  fields are unchanged; threshold values match each detector; no duplicate
  detector/GPS identity; exact detector totals and class counts agree.
- Receipt/contract/summary seals and file SHA-256 bindings pass.
- All three new implementation source hashes match the `03a38ab` Git blobs
  byte-for-byte. Upstream historical LF/CRLF reconstruction qualifications
  remain; no clean-clone numerical replay is claimed by this check.
- Pre-run tests: 33 targeted; 155 full O3a/PatchProducer, all passed.
- Post-run WSL O3a/PatchProducer regression: **155 passed**, 11 upstream
  GWPy/Matplotlib deprecation warnings, 107.59 seconds; exit code 0.

## Scope and handoff

No scientific-method deviation, parameter tuning or historical artifact
replacement. Code, CLI, tests and contract were frozen before classification.
This completion increment changes only the verified receipt and checkpoint
documentation/STATE. No merge or push to main. After successful post-run
tests and branch push, suspend the monitor and await the user before any
downstream stage.
