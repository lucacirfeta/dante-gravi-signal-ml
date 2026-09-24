# O3a native morphology taxonomy — verified checkpoint (2026-09-24)

The author approved strict methodological parity with the corrected O4a
taxonomy. Before executing O3a, the frozen contract recorded the prediction
that single-linkage chaining would again create one dominant family, with no
numerical acceptance cutoff. A different O3a partition would have been
reported without retuning the method.

## Method and population

- All 8,900 classified O3a primary seeds: 3,624 H1 and 5,276 L1. Native
  class is not used to select rows for the morphology graph.
- Unchanged primary-scan MIL vectors (384 float32 components), L2-normalized;
  cosine similarity cutoff 0.75, equivalently cosine-distance cutoff 0.25;
  SciPy single linkage and historical O4a family naming across both detectors.
- No O4a scientific rows, scores, thresholds or vectors were imported into
  O3a clustering. The O4a family-size summary informed only the prediction
  registered before execution; the O4a implementation and versioned method
  defined the calculation.
- Parent primary-scan and native-classification receipts, source bytes,
  database/output hashes, detector/GPS, identity digests and image hashes are
  bound by `config/dante_o3a_native_taxonomy_v1.json` (contract digest
  `bfc1a0588ae71d63efde752ac1f2858b717e00eb10aa0291e47084a155a8769b`).
  The primary verifier reads scores for integrity; taxonomy clustering does
  not use those scores.

## Observed result

Standalone run and replay verification both exited 0. The verified result
contains **two clusters: one 8,899-member family and one singleton** out of
8,900 rows (largest-family fraction 99.9888%). This confirms the pre-registered
expectation of a dominant chained family, as in O4a (10,940/10,942 in its
largest family), but does not demonstrate that all members have the same
physical morphology. The near-total collapse limits the discriminative value
of these family IDs for comparing detailed morphology across O3a and O4a.

Run key:
`f475a46f829c9afd78994898f6be5f9499483e401152e0f5f148a11f00b0c629`.
Run summary artifact digest:
`4ccc3b54f00bb3308ac8edd00803f6b88df1b5df9d609c713ac40303e7b7c1bf`.
Verified compact receipt:
`artifacts/dante_light/o3a_native_v1/native_taxonomy.json`, digest
`9f947eeca4d8609f2ae96659d6364cf6a303d4ab411121f74c84e4332e287b41`.
The external 8,900-row JSONL SHA-256 is
`3afe6d840d1330dcb83252f67028e1e61220b5bd39b170c6b5d077bf7212ba8e`.

## Verification

- Before the real run: 15 focused synthetic tests passed; the complete WSL
  O3a/PatchProducer suite passed 170 tests. The source/contract freeze was
  committed as `76a3552` before opening O3a taxonomy outcomes.
- After the run: standalone full replay verification passed and independently
  reproduced the exact output and summary. The complete WSL suite again
  passed **170 tests**, with 11 upstream GWPy/Matplotlib warnings; Ruff passed.
- A separate read-only audit compared every taxonomy JSONL row to the frozen
  native-classification row, checked every candidate MIL-vector hash and
  detector/GPS/identity/image join against the primary-scan SQLite, recomputed
  counts and family sizes, and independently checked threshold-graph
  connectivity with normalized vector dot products. All 8,899 dominant-family
  rows are connected by edges meeting similarity 0.75; the singleton's maximum
  similarity to that family is about 0.6962, below the cutoff.
- The three new source files' SHA-256 values match their frozen Git blobs
  byte-for-byte. The upstream EOL qualifications documented in earlier O3a
  checkpoints remain; this check is not a clean-clone numerical replay.

Taxonomy is a morphology graph, **not physical cross-detector coincidence**.
No PEM analysis, global-significance calculation, A2 promotion or
astrophysical-discovery claim is made here. Those downstream stages remain
separate decisions.
