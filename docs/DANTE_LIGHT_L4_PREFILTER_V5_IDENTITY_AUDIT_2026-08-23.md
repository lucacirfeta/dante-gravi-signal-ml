# DANTE-Light L4 prefilter v5: Plan 1 identity audit

Date: 2026-08-23  
Scope: outcome-blind O4a identity and local-mirror integrity audit  
Status: `PASS_IDENTITY_CAPACITY_ONLY_NOT_A_SPLIT`

## Scientific boundary

This result establishes only that enough previously unused, fully covered O4a
4096-second blocks exist to design fresh v5 partitions. It is not a split, does
not establish CAT1 or per-window eligibility, does not select a representation,
and does not authorize a v5 freeze. No strain array, teacher score, feature
value, development outcome, confirmation outcome, or O4b datum was inspected by
the audit.

The v5 protocol must still freeze the broader, physically distinct NSBH stress
population in Plan 2, before training. Its development and sealed-confirmation
instances remain separately gated in Plans 4 and 5 and do not enter the primary
training loss.

## Audited capacity

The strict evidence build recomputed SHA256 for every physical file rather than
trusting the resumable cache. The resulting artifact digest is
`0ef6f9652fc5a4213b28b0fc6148a24ab5c5af127f9bea9cd2fcf158e8eee41e`.

| Quantity | Result |
|---|---:|
| Valid physical HDF5 files | 7,174 |
| Unique detector--GPS spans | 6,928 |
| Duplicate spans / extra copies | 246 / 246 |
| Previously used O4a block union (v1, v2/v3, v4) | 2,797 |
| Fresh fully covered blocks | 3,933 |
| Fresh fully covered H1 / L1 blocks | 1,933 / 2,000 |
| Recoverably quarantined corrupt files | 10 |

All duplicate copies for a span were byte-identical. Every unique retained file
opened as HDF5 with exactly one one-dimensional float64 `Strain` dataset and the
sample count implied by its filename at 4096 Hz. The validator inspected HDF5
container and dataset metadata, not strain values. Absolute local paths are not
serialized in the public manifest.

The committed machine-readable evidence is:

- `artifacts/dante_light/prefilter_l4_v5_design/identity_audit_v5.json`;
- `artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl`;
- `artifacts/dante_light/prefilter_l4_v5_design/raw_quarantine_v5.json`.

## Corrupt-file handling and v4 evidence check

Ten files with the HDF5 error `bad object header version number` are stored
recoverably in the user-local quarantine, not deleted. The versioned quarantine
record contains their original identities, sizes, SHA256 values, and any v4
*grouping-block* references. A grouping-block reference does not by itself mean
that the referenced 32-second window read that physical file.

Two development rows warranted direct replay without opening any sealed row:

- `v4-background:H1:cat1:H1:1375879200` was fetched explicitly from GWOSC. Its
  strain SHA256 (`f2b839ec762487319d75acdda5d1f1d5609941e307a02a2b2cec233124bb7764`)
  and all six v4 feature values reproduce exactly.
- `v4-injection:H1:v4inj:BBH_10_10:400:4` was reconstructed in the pinned
  `dante-lalsuite-v3` WSL environment. Raw strain, plus/cross and projected
  waveform hashes, injected-strain hash, and all six v4 feature values reproduce
  exactly.

The two referenced confirmation identities remain sealed; neither their data
nor outcomes were opened. These checks show that the recoverable quarantine did
not invalidate the affected v4 development evidence.

## Reproduction

Verify the committed evidence without access to the local raw mirror:

```text
python scripts/audit_dante_light_prefilter_v5_identities.py --verify
python -m pytest tests/test_dante_light_prefilter_v5_identity.py -q
```

Rebuild the evidence from the local O4a mirror on Windows:

```text
python scripts/audit_dante_light_prefilter_v5_identities.py
```

The rebuild defaults to a full rehash. `--reuse-hash-cache` is only a resumable
local convenience and must not be used to generate final evidence.

## Remaining Plan 1 checkpoint

Wavelet scattering remains an optional label-blind feasibility comparator, not
a selected v5 arm. Kymatio is not installed in either current project
environment. Adding it must be isolated from production dependencies and
reviewed as a separate dependency/architecture checkpoint before any benchmark;
no protected cohort is needed for that decision.
