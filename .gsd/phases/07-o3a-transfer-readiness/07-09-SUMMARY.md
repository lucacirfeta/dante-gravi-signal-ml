---
phase: 07-o3a-transfer-readiness
plan: 09
completed_at: 2026-09-19
---

# Summary: O3a initial-calibration raw acceptance

## Results

- Evaluated all 590 provisionally selected O3a calibration blocks under the
  frozen 17-row block-atomic acceptance rule.
- All 590 blocks passed; no fallback, cross-stratum reallocation, failure, or
  defer was required.
- Published exactly 5,000 point-estimate rows per detector and 4,998 complete-
  block bootstrap rows per detector.  The final two rows per detector remain
  explicitly point-only.
- Acceptance used only exact coverage and finite-stage gates.  Score magnitude
  and class did not affect acceptance; no threshold, class, or candidate
  outcome was evaluated.

## Canonical evidence

- Run key:
  `8fdbca72bf4af0dd8b74b299aaa7ff1a7b431fa872a28eac6578fa97114f0cfd`
- Status: `PASS_VERIFIED_O3A_INITIAL_CALIBRATION_ACCEPTANCE`
- Contract digest:
  `1c2b79a94674317edbea9f92a314d9ec08cf8425161ece8b83e4c74ad138a279`
- Raw-manifest SHA-256:
  `9a60a2990cdee999e48d919bf20adf2ae5c5decd5a954440bd682c2ced7a6926`
- Accepted-ledger SHA-256:
  `b9fe2a4fb3481a44b7b067846791d2f286d2da9bd595069d2edc00a1fd4b2c2b`
- Artifact digest:
  `5e26caaff083050c79731b35b6109c473310bd7719c366111518a3282a1593ed`

## Verification

- Independent replay of all 590 shard self-digests and identities: PASS.
- Summary self-digest and accepted-ledger SHA-256: PASS.
- Independent cardinality audit: 5,000 point rows and 4,998 bootstrap rows for
  each of H1 and L1.
- Windows focused O3a/PatchProducer suite: 58 passed.
- WSL focused O3a/PatchProducer suite: 58 passed, 11 upstream warnings.
- WSL Ruff: passed.

## Next gate

Freeze and verify the detector-specific initial p99 threshold-fitting contract
against this accepted O3a ledger before fitting any threshold.  Classification,
primary scanning, and native-index selection remain closed.
