# O3a native rescore: independent read-only checkpoint audit

Date: 2026-09-23. Branch: `science/o3-transfer-readiness`.

This audit inspected source bytes, frozen contracts and outcome-blind identity/context
ledgers while scoring continued. It did not open score shards, compute thresholds,
inspect candidate outcomes, change the running source/configuration, or restart a job.
It is not the final rescore verifier or a claim of scientific completion.

## Run and provenance

- Run: `native_rescore_e9b75ee479f5fa6850accb2178d00fa752954519fe7db768629ef1422c4c27e0`.
- Contract: `config/dante_o3a_native_rescore_v3.json`.
- Contract digest: `85028c59d55fbc95c9b2b056eb0e783dfbffb3b7f446feb1befd8c2e1ff2f20c`.
- Source freeze: commit `f38af52`.
- All 15 `implementation_sources` working-file SHA-256 values match the contract.
- Nine match their Git blobs byte-for-byte. Six match exactly after converting
  the Git blob's LF line endings to CRLF:
  `config.yaml`, `src/core/artifact_manifest.py`, `src/core/encoder.py`,
  `src/core/model_loader.py`, `src/core/patch_scorer.py`,
  `src/core/preprocessor.py`.

For each of these six files, both checks passed:

```python
working_bytes == git_blob.replace(b"\n", b"\r\n")
git_blob == working_bytes.replace(b"\r\n", b"\n")
```

The Git blobs were obtained directly with `git show f38af52:<path>`, without
checkout or text decoding. Thus the exact frozen bytes are recoverable from Git;
there is no missing-source finding in this audit. However, an ordinary LF checkout
does not directly satisfy the six frozen raw-byte hashes. This is a checkout
reproduction limitation, not an unqualified clean-clone PASS. Do not normalize
the live files or rewrite the frozen contract. A separate post-run clean-clone
exercise should reconstruct the documented historical bytes, check all hashes,
and then run the verifier. This audit alone does not demonstrate numerical replay
in that separate environment.

## Independent identity and geometry checks

The audit loaded the manifest and the two completed cohort ledgers directly,
without calling the production selection or verification functions. It independently
recomputed file hashes and checked detector/GPS identities, ordering, block membership,
guards and context intervals.

| File | SHA-256 |
| --- | --- |
| `work_manifest.jsonl` | `61c3f4745322f836d72449e8e240beff05c17b169a043ea704318cc3a85cbccd` |
| `native_calibration_cohort.jsonl` | `2cc88654bfea3792a1a423132dc286aa4f40525859565c23c2e178b94aa2c33c` |
| `native_cohort.jsonl` | `99cbc1c897ab1b30df33923b0b75693c997447ecc878971edfb913228893e298` |

Results: PASS, zero violations in each of ten checks:

1. Duplicate detector/GPS identities in the work manifest.
2. Calibration identity order versus the frozen calibration ledger, after restoring ordinal order.
3. Per-detector calibration row numbering.
4. Bootstrap block-index assignment.
5. Within-complete-block spacing (64 seconds).
6. Inclusive 128-second guard against primary seeds, including the other detector.
7. Inclusive 128-second guard against index-cohort windows, including the other detector.
8. Full context coverage and used intervals inside source-frame boundaries.
9. Context-source detector consistency.
10. Context-source canonical JSON digests.

There are exactly 5,000 calibration rows per detector. Each detector has 294 complete
blocks of 17 rows in its 4,998-row bootstrap prefix; the remaining two rows belong
only to the point-estimate population. Context checks covered the complete work
manifest. They verify metadata coverage, not a second read/replay of all raw HDF5
samples; that replay remains the running scorer's responsibility.

## Statistical contract, not new statistical results

The native selector is explicitly
`O4A_NATIVE_V2_EVENLY_SPACED_COMPLETE_BLOCKS_WITH_CONTEXT_FALLBACK`, as recorded in
`config/dante_o3a_native_calibration_selector_amendment_v1.json`. It is not the
initial-calibration hash-stratified selector. The recorded rationale is parity
with the corrected O4a native stage, not a demonstrated superiority of uniform
selection. No new selector choice was made during this audit.

The O3a stage contract prescribes detector-specific p99, complete non-overlapping
temporal blocks of 17, 1,000,000 bootstrap replicates, seed 42, chunks of 500 and
CI percentiles 2.5/97.5. The reviewed bootstrap helper samples complete blocks,
uses all rows for the point p99, and drops the incomplete tail only from bootstrap
resampling. The downstream adapter must pass the explicit frozen block length
rather than rely on the helper's optional default. No thresholds or confidence
intervals were computed here; their precision is not certified by this audit.

## Resume evidence and remaining verification scope

One scorer process was observed, with no active `failure.json` and no final
summary yet. The earlier HTTP 502 failure remains preserved in:

`failure_history/failure_5b3de486f6f618b2b7a55e5f788ffa9c9f2f78e267ca77631508bd94c8d04f92.json`.

The real same-key resume and subsequent progress provide evidence for this
transport-failure recovery path. The source also contains singleton locking,
atomic shard writes and validation of existing shards before reuse. The inspected
rescore unit tests exercise shard integrity and cache/partial-file handling, but
do not constitute a complete interrupted-run fault-injection test matrix.

Do not describe this as universal crash/power-loss certification. Follow-up tests
should cover interruption around shard/progress persistence, corrupted resume
evidence, lock contention, and abrupt process termination. These are future
verification tasks, not reasons to alter the current scientific contract.

No regression suite was rerun in this audit, and no GPU workload was added. The
previous preflight/test checkpoint remains separate evidence. Final rescore
`--verify`, regression tests, complete cardinalities and empty transient cache are
still required before downstream adoption.

## Completion addendum: 2026-09-24

The run subsequently completed. Standalone `--verify` exited 0 and the WSL
O3a/PatchProducer regression suite passed 103 tests (11 upstream deprecation
warnings). The final 18,900 rows, zero mismatch gates, empty transient cache,
three preserved infrastructure interruptions, artifact identities and checkout
qualification are recorded in
`.gsd/phases/07-o3a-transfer-readiness/07-15-SUMMARY.md`.
The clean-clone replay and broader crash-test follow-ups above remain open;
neither is claimed by the completed score-only checkpoint.
