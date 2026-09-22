---
phase: 07-o3a-transfer-readiness
plan: 11
completed_at: 2026-09-22
---

# Summary: O3a primary scan

## Result

The frozen O3a primary scan completed over the exact CBC_CAT1 geometric
universe.  H1 and L1 used their separately calibrated p99 point thresholds;
no threshold pooling or retuning occurred.  Intermediate outcomes remained
closed throughout execution.

| Detector | Required windows | Verified windows |
|---|---:|---:|
| H1 | 349,925 | 349,925 |
| L1 | 372,986 | 372,986 |
| Total | 722,911 | 722,911 |

The exact 6,313-frame source ledger passed detector/GPS interval/filename/URL
and hash-form verification.  There were zero invalid or silently dropped
windows, no failure artifact, and the transient raw cache was empty at
completion.

The threshold-exceedance count stored by the scan is not a detection claim,
native classification, taxonomy, coincidence result, or publication claim.
Those stages remain closed.

## Canonical evidence

- Contract digest:
  `e069c93b89498e2375144ace1285d5a68c21cba4fb0acf56dbbb6ae2b653d1e5`
- Run key:
  `8f0424e5f3ea2b94449eaddb0e1ccf61c5fd7ba91d54c839bfa89d0e26efad35`
- Artifact digest:
  `ba51f9cad83826223f860fda9b52077cbcc2e45c44fc7ad5063ebe56f49c4c79`
- Database SHA-256:
  `1f222dfbc4066abf8fe2b2f3a09edb4a7ccbc83f79aac94ba9a54aa6b0844699`
- External summary SHA-256:
  `7333867c9098f8bd760de1a23c333f7889c4cf14b8bc28b63fb5f6a57e437d68`
- Compact evidence:
  `artifacts/dante_light/o3a_native_v1/primary_scan.json`

## Interruption and resume evidence

The superseded run
`9c7a7790a3952e12975deee884497b4747018cac896cb4eb3ab94d9836b90e54`
remains preserved as FAILED with failure artifact digest
`ee709fa7663c6bf46e0364c54b7aa32bcfa376e4ae3d5bfbd234ecfc05e5f46d`.
No row from that run was adopted.  The clean replacement run later resumed
under the same replacement run key after an infrastructure interruption; its
database identity, uniqueness constraints, frame mapping, final hash, and
exact cardinality all passed verification.

## Verification

- Independent production verifier: PASS.
- Focused Windows O3a suite: 56 passed.
- Focused WSL O3a suite: 56 passed, 11 upstream GWPy warnings.
- Final source ledger: 6,313/6,313 frames, exact mapping verified.
- Final transient raw cache: empty.

## Next gate

Native cohort selection, index construction, native calibration, rescore,
classification, taxonomy, coincidence, PEM, and comparison remain unopened.
Their contracts must be frozen before execution; no downstream result is
implied by this scan completion.
