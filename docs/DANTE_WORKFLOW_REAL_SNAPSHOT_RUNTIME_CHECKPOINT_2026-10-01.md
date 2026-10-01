# Real retained snapshot preflight: runtime checkpoint

## Outcome

The first real read-only parent preflight for the isolated O3a PEM snapshot
refused before capture. Existing source freeze f254b2b and scientific contracts
are unchanged. This is a blocked increment, not a completed real-chain replay.
The previously sealed O3a results are not being reclassified or invalidated.

Observed CLI result (WSL Python, session 97666, OS exit **1**):

```json
{"error":"STOP_ENVIRONMENT_MISMATCH: O3a scoring requires the frozen WSL runtime","error_type":"ContractError","status":"FAIL_CLOSED_O3A_COINCIDENCE_EVIDENCE"}
```

The original validator in `src/dante_light/o3a_native_contract.py` compares the
whole current fingerprint when require_current=True. The actual parent gate in
`src/dante_workflow/o3a_coincidence_verification.py` requests that check, so the
existing fail-closed behavior is preserved, not bypassed.

## Diagnosis

Original load_runtime_contract(require_current=False) validates the frozen
contract, and original _capture_o3a_runtime("cuda") supplies the live fingerprint.
A read-only recursive comparison found exactly one non-digest field differing:

| Field | Frozen | Observed |
| --- | --- | --- |
| cuda_device.driver_version | 616.92 | 617.14 |
| environment_digest | 582a9b99f689d36f126b75f95dd31763c2b399aab03180f06c9838eb1f8f1b58 | ebeae01fdbad49d252555e354daba1e69282ddfcdd89ee386ceeb3c184fb474f |

All other fields captured by that schema compare equal, including Python,
packages, OS, Torch settings and other CUDA device metadata. Equal metadata is
not a proof of numerical equivalence between drivers. The diagnostic itself
returned OS exit 0; it did not run or certify the scientific parent chain.
Frozen runtime file SHA256 is
3b00a0bf258cc96870971481138e10e7e85deb97a1c3c49c470626e3153d0ef2.

## Reproduction

In WSL at the repository root, using the existing scientific environment:

```bash
base=/mnt/e/dante_cache/dante_light/o3a_native_v1
/home/atafe/miniconda/envs/dante_env/bin/python -B \
  scripts/verify_dante_o3a_coincidence_evidence.py \
  --external-root "$base" --taxonomy-external-root "$base" \
  --classification-external-root "$base" --threshold-external-root "$base" \
  --rescore-external-root "$base" --calibration-external-root "$base" \
  --index-external-root "$base" --cohort-external-root "$base" \
  --primary-external-root "$base"
```

The real invocation used these explicit values for all nine roots; run keys are
derived by the existing verifier from versioned contracts/compacts. No productive
flags, monkeypatch, download, original PEM verifier or runtime amendment used.

Existing regression command:

```bash
/home/atafe/miniconda/envs/dante_env/bin/python -B -m pytest -q --tb=short \
  tests/test_dante_o3a_native_contract.py
```

Result: **10 PASS, OS exit 0, 3.40s**. No implementation was edited, so this is
not a claim of a new full-suite or real complete-chain success.

## Decision required

1. Restore driver 616.92 in a suitable environment, with explicit authorization
   for the host-level change; then repeat the unchanged read-only preflight.
2. Design a separately versioned qualification for retained-only validation on
   the current driver, with explicit compatibility evidence and unchanged
   productive scientific gates. This changes validation semantics and requires
   author approval before implementation. It is not simply ignoring a field.

No host downgrade, contract refreeze, acceptance of 617.14 or new qualification
was performed. A retained-only qualification would still not certify fresh
scoring, sensor/null recalibration, global quiescence, all runs or Virgo.

No real capture plan/archive created, no history or user files changed, no push,
merge, release or external communication. Next: author decision, then the exact
reviewed capture plan and bounded complete-chain replay if the gate is resolved.
