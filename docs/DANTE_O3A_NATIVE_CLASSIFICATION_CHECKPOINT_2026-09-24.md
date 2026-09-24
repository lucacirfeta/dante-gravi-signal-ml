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

No real classification result was claimed at this pre-execution checkpoint;
verified results are recorded in the completion section below.

Full WSL O3a/PatchProducer regression: **155 passed**, 11 upstream
deprecation warnings, 99.32 seconds. Ruff check/format passed on the three
new Python files. Frozen contract digest:
`9aaeff60fd078538355d724f4102b39886dca97fef7474d394e2ee4109f5f1a2`.

## Launch

Source frozen and pushed in `03a38ab`; all three new implementation source
hashes match Git bytes exactly. Started the hidden WSL worker under run key
`5cedef7de1c036f49a2c33acfeaa64198a67b31bed1c1109c6b34004faf6c044`.
The supervising command waits for --run and captures its exit code; only
exit0 and an absent failure file permit --verify, with distinct logs and a
separately captured exit code. Exec session54398 holds the supervisor output.
The launch record did not claim completion or classification counts.

## Verified completion

On 2026-09-24, --run completed at 20:15:30 Europe/Rome and --verify at
20:20:13. Both captured exit codes are 0. Both stderr files are empty,
no failure artifact exists, and no classification worker remains active.

| Detector | BACKGROUND | AMBIGUOUS | ROBUST | Total |
|---|---:|---:|---:|---:|
| H1 | 1070 | 263 | 2291 | 3624 |
| L1 | 1422 | 295 | 3559 | 5276 |
| Total | 2492 | 558 | 5850 | 8900 |

Post-run WSL regression: **155 passed**, 11 upstream GWPy/Matplotlib
deprecation warnings, 107.59 seconds. A separate read-only audit checked
every input/output row pair, recomputed labels from the detector-local
thresholds without invoking the classifier, and confirmed unchanged source
fields, unique detector/GPS identities and exact population/class counts.
Contract/receipt/summary seals, input/output/summary SHA-256 values, frozen
references and all three new source Git blobs match. Historical upstream EOL
qualifications remain; this is not a new clean-clone numerical replay.

Run summary artifact:
`24bfce9f2b7661ab5c4c9193d5d1200a9416df6d1704d8b80eadd7b91636c4e2`.
Verified compact artifact:
`65d67d4c4dac2ff53893d3d23b3f308e5008c436b684a4247c8e927b662de3ac`.
Output JSONL SHA-256:
`88973cde9bf0c33307f320eab2cd8e6ca45a65dbcfaf2c04086c26ad8c3c0830`.

No scoring, population, threshold or statistical rule was changed. The
classification checkpoint is complete. These are single-detector labels,
not astrophysical discoveries or global significance estimates. Taxonomy,
coincidence and PEM remain unopened pending user authorization. Suspend the
completed classification monitor after the branch checkpoint is pushed.
