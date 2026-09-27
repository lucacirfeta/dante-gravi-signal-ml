# O3a/O4a five-channel PEM input freeze — 2026-09-27

The approved paired diagnostic comparison has an input-only machine contract:
`config/dante_o3a_o4a_common_pem_v1.json`, digest
`aa25cff27ea5af0884da16dd12d5fe579154fae5f835c88aa95d9e46df2b2f7a`.
No new PEM event, null or comparative outcome has been calculated.

The contract verifies the exact five public auxiliary channels per detector
as the ordered O3a/O4a intersection. The two L1 VMON channels remain
excluded. All measurement/null/bootstrap parameters match the versioned
corrected-O4a contract and the existing O3a-only method, except that each
run retains its own frozen candidate-exclusion population. The target and
full candidate-exclusion ledgers are independently replayed and checked:
O3a has 12 targets / 8,900 excluded seeds; O4a has 65 targets / 10,942
excluded candidates. Primary and AMBIGUOUS diagnostic targets remain separate.

The signed references bind both PEM contracts, compact verified receipts,
external summaries and target ledgers, classification receipts, the O4a raw
replay contract/adapter, the comparative preflight adapter, the CLI and both
shared PEM measurement modules. The current O4a PEM source hash is recorded
separately from its historical raw source hash; their difference is governed
by the existing versioned reconciliation record, not called byte identity.
No existing parent receipt or historical output was rewritten. The new test
file is not raw-byte-bound because no additional `.gitattributes` rule was
approved for it; runtime source and config bytes are LF-stable by existing
rules.

Empirical checks in WSL `dante_env`:

- The combined contract/raw-replay/O3a PEM/O4a PEM/provenance pytest suite
  exited 0: **32 passed, 11 upstream warnings**. Tamper tests reject an
  altered channel, bootstrap count, target receipt, candidate-exclusion
  digest or interpretation boundary, including a re-signed contract.
- Ruff lint and format checks passed on the comparative adapter, CLI and
  test file; `git diff --check` passed.
- The input-only CLI preflight exited 0 with
  `PASS_O4A_PEM_RAW_REPLAY_PREFLIGHT`: comparative contract digest above,
  raw replay contract digest
  `81f6b609087068253faa84a0a32f94364bb727c3655077add99b19b243ccd1ba`,
  published-manifest SHA-256
  `531912260ea45cd5265198f7a1990a8a89f69ffa98abca8a21930140e332b7ba`,
  65 historical target contexts mapped gap-free to 64 official O4a 4 kHz R1
  frames. It opened neither strain nor PEM outcomes.

Next gate: acquire the official frames under the new raw-replay run key and
independently verify the exact 40-second float64 context digest for every
one of the 65 historical targets. Any single mismatch fails closed. Only
after that and the separate adapter/method regression gates may the paired
PEM measurements run. This freeze is not an astrophysical or global
significance claim. GPS 1243231936 remains an O3a diagnostic record with
its documented dual-detector BURST_CAT2/3 warning, not a promoted candidate.
