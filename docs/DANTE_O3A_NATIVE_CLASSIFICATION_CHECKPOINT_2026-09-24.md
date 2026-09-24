# O3a native classification checkpoint

## Scope and prerequisites

The user authorized CLASSIFY after native thresholds were independently
verified. Phase 07-16 is complete, including exit code 0, deterministic threshold
recomputation, 122 post-run regression tests and receipt/source audit.
Parent threshold receipt:
`32890633207ebb91839131b972dc0ca18650ceb3fe18383fb9adee3bed6ce281`.

This adapter reads the approved rule and populations from the versioned O3a
contracts. It classifies every frozen primary seed (3624 H1 and 5276 L1),
without filtering or rescoring: BACKGROUND below the detector's CI lower
endpoint, ROBUST above its CI upper endpoint, AMBIGUOUS otherwise, including
exact equality at either endpoint. All source fields and score encodings are
preserved; only the native class and applied threshold values are added.

No O4a scientific rows, scores or labels enter this stage. No pooling,
taxonomy, coincidence, PEM, A2 promotion or global-significance claim.
ROBUST denotes this single-detector classification, not an astrophysical
discovery or a multiple-testing-corrected detection.

## Implementation and verification

The adapter binds source bytes, stage/rescore/threshold contracts, verified
parent receipts and canonical runtime. It checks complete detector/GPS
identity cardinalities and order, score encodings, absence of prior labels,
and the exact frozen input SHA. Canonical output JSONL is hashed bytewise.
Summary/output differences are rejected without overwriting evidence.

Both --run and --verify independently invoke the frozen threshold verifier,
including upstream integrity checks and deterministic threshold recomputation.
--verify compares every regenerated output byte and the entire summary before
creating its compact receipt. The singleton lock prevents duplicate workers.
Any failed parent/runtime/input/output check stops the stage; no retuning or
automatic failure-file removal is provided.

All 33 targeted tests passed using synthetic fixtures and metadata-only checks, covering exact/adjacent
boundaries, detector locality, preservation of source fields, invalid numbers,
population/order/identity corruption, prior outcomes, parent/input hashes,
immutable re-sealed summary/output corruption, replay and singleton locking.
New Python files are LF, including a pinned test-file EOL rule. Historical
upstream byte-reconstruction qualifications are inherited, not silently fixed.

No real classification result is claimed by this pre-execution checkpoint.

Full WSL O3a/PatchProducer regression: **155 passed**, 11 upstream
deprecation warnings, 99.32 seconds. Ruff check/format passed on the three
new Python files. Frozen contract digest:
`9aaeff60fd078538355d724f4102b39886dca97fef7474d394e2ee4109f5f1a2`.
