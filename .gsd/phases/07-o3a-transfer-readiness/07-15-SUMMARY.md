---
phase: 07-o3a-transfer-readiness
plan: 15
status: complete
completed_at: 2026-09-24
---

# Summary: O3a native score-only replay

## Result and boundary

The frozen v3 run completed all 18,900 score-only rows: 5,000 native-calibration
rows for H1, 5,000 for L1 and all 8,900 frozen primary seeds. The runner finished
with `PASS_VERIFIED`, 591 complete score shards and an empty transient cache.
There is no active failure artifact. All source-frame, context, image-hash,
encoder and finite-score gates report zero failures or mismatches.

No native thresholds, classes, taxonomy, coincidence results, PEM conclusions
or scientific significance were computed. No O4a scores or thresholds were
adopted. Completion of score replay is not a discovery result.

## Canonical evidence

- Source freeze: `f38af52` (unchanged throughout execution).
- Contract: `config/dante_o3a_native_rescore_v3.json`.
- Contract digest: `85028c59d55fbc95c9b2b056eb0e783dfbffb3b7f446feb1befd8c2e1ff2f20c`.
- Run key: `e9b75ee479f5fa6850accb2178d00fa752954519fe7db768629ef1422c4c27e0`.
- Artifact digest: `4b1eff34f618005a2b881e3dd29e4dc0b25f1c6e5b5b5d19a23c0a833245503a`.
- External directory: `E:/dante_cache/dante_light/o3a_native_v1/native_rescore_e9b75ee479f5fa6850accb2178d00fa752954519fe7db768629ef1422c4c27e0`.
- Compact verified receipt: `artifacts/dante_light/o3a_native_v1/native_rescore.json`.

| Output | Rows | SHA-256 |
| --- | ---: | --- |
| `native_calibration_H1.jsonl` | 5,000 | `bb565f0675f6472ea1bca2db18e6190506345ace0990548c7f21a5b2bc0d9b04` |
| `native_calibration_L1.jsonl` | 5,000 | `7054797893bf013fd90d66d983a5cf45fb72b85c530cb67f43cc85de91b44ba3` |
| `primary_candidate.jsonl` | 8,900 | `15b0e84ffc1fa04b5b2a5faf46b85d8fe48729e765ecf90286d083691f273c24` |

## Validation

- Standalone production `--verify`: PASS, exit code 0 on 2026-09-24:
  `{"status": "PASS_COMPLETE_O3A_NATIVE_RESCORE", "artifact_digest": "4b1eff34f618005a2b881e3dd29e4dc0b25f1c6e5b5b5d19a23c0a833245503a"}`.
  Command: `/home/atafe/miniconda/envs/dante_env/bin/python scripts/run_dante_o3a_native_rescore.py --verify`.
  This validates saved shards, exact output ledgers and parent evidence; it is
  not an additional numerical rescore from redownloaded raw strain.
- WSL regression command:
  `/home/atafe/miniconda/envs/dante_env/bin/python -m pytest -q tests/test_dante_o3a_*.py tests/test_patch_producer_context.py`.
- Regression result: `103 passed, 11 warnings in 81.52s` on 2026-09-24.
  Warnings are upstream GWPy/Matplotlib pending deprecations.
- Separate byte-hash audit: 15/15 implementation sources, 8/8 parent files,
  3/3 output files, summary digest and all three failure-archive digests PASS.
- Outcome-blind identity/context audit performed on 2026-09-23: ten checks
  passed with zero violations; see the linked audit below. This was not a
  second raw-strain replay or an inspection of score values.

## Transport interruptions preserved

All three infrastructure failures were verified and archived by the frozen
runner before same-key resume. No source/configuration or scientific criterion
was changed. Complete shards were validated and reused, not silently replaced.

| Failure | Rows already saved | Failure artifact digest |
| --- | ---: | --- |
| HTTP 502 | 4,544 | `5b3de486f6f618b2b7a55e5f788ffa9c9f2f78e267ca77631508bd94c8d04f92` |
| HTTP 503 | 16,672 | `ce3f1ff1fbb6fcc0ed716ddd478aa397fd040431531dd4ff99132618b5802bd2` |
| Connection timeout | 17,792 | `9533ff02deb68683f2a67764090313dc6ac54cdfcc25bd7b7ddfc9d661665ff5` |

Their JSON files remain under `failure_history/failure_<digest>.json` alongside
the original and `worker.resume1`, `worker.resume2`, `worker.resume3` logs.
The structural preflight failures for v1/v2 remain preserved, with zero score
shards, and were never resumed or adopted. These successful transport resumes
are not a universal certification of abrupt power-loss/CUDA-crash recovery.

## Checkout reproducibility qualification

The source audit proved exact recovery from Git commit `f38af52` for all 15
frozen source files: nine are identical Git blobs and six require the documented
LF-to-CRLF conversion. All 15 working-byte hashes match the frozen contract.
The six files and reversible byte-level check are recorded in
`docs/DANTE_O3A_RESCORE_READ_ONLY_AUDIT_2026-09-23.md`.

This is not a missing-source finding, but a clean LF checkout does not directly
satisfy all frozen hashes. A clean-clone reconstruction test remains follow-up
work; this completion does not claim that such a test or a new numerical replay
was performed. No line endings or frozen contract hashes were rewritten.

## Next gate

Prepare the detector-specific native p99/block-bootstrap threshold stage under
the approved statistical contract; freeze and test its adapter before execution.
Do not reuse initial thresholds or import O4a thresholds. Candidate classification
and all later scientific stages remain unopened at this checkpoint.
