# O3a native thresholds: pre-execution checkpoint

## Frozen scope

Plan 07-16 fits calibration only. The verified parent rescore artifact is
`4b1eff34f618005a2b881e3dd29e4dc0b25f1c6e5b5b5d19a23c0a833245503a`.
Native-threshold contract:
`10d6279a2b637309d3d955881cf0a3d2f450f6a66adfb9de9fd2613ea3b65c5c`.

H1 and L1 are fitted separately. The method is identical to the versioned
O4a native method, not the initial-calibration selector: p99 over all 5,000
rows, 1,000,000 bootstrap replicates, seed 42, complete non-overlapping blocks
of 17 over the first 4,998 rows, percentile CI 2.5/97.5. The last two rows
contribute to the point estimate only. Native population selection remains
the frozen evenly-spaced complete-block selector with context fallback.
Neither detector pooling nor candidate-score fitting is permitted. O4a
method metadata is compared for parity; no O4a scientific values are adopted.

Absolute CI width and width divided by absolute p99 will be reported for
each detector. No new post-hoc acceptability cutoff is introduced. Finite
interval and point-containment checks match the native O4a implementation.
These calibration intervals are not global candidate significance estimates.
Classification, taxonomy, coincidence and PEM remain unopened.

## Pre-execution verification

- New adapter tests: 19 passed. Exact block-resampling oracle, chunk
  invariance, point-only tail, detector locality, row corruption, input hash
  corruption, re-sealed summary corruption, immutable evidence, missing
  summary and singleton lock are covered using synthetic fixtures.
- WSL O3a/PatchProducer suite: 122 passed, 11 upstream GWPy/Matplotlib
  deprecation warnings; 86.43 seconds.
- Ruff check and formatting: passed for the three new Python files.
- No scientific score ledger was opened for contract preparation or testing.
- Two initial synthetic execution fixtures intentionally need a valid
  contained point/interval; their monotonically increasing tail initially
  violated the existing containment guard. The fixture was corrected before
  freeze, not the guard or the scientific method. All final tests pass.

## Byte provenance

The adapter, runner and tests use LF. An exact `.gitattributes` rule pins
the new test file to LF. The reused bootstrap helper matches its Git blob
byte-for-byte. The existing `src/dante_light/contracts.py` working copy is
CRLF and reconstructs exactly by replacing Git-blob LF with CRLF; its frozen
working SHA-256 is
`67400c77574cc805eccf617819d80e70907ad8aef0679ef8b8880f6ad0507e30`.
That historical file is not normalized or modified. Upstream rescore EOL
qualifications in the September 23 read-only audit also remain applicable.
Source recovery is exact, but an arbitrary clean-LF checkout is not claimed
to satisfy the historical byte contracts without reconstruction.

## Execution gate

Commit the source and contract before fitting. Run the canonical WSL CLI
with --run, then --verify, which re-verifies the parent and recomputes both
thresholds before writing a compact verified receipt. A failed hash,
runtime, identity, interval or deterministic-replay check stops this stage;
there is no automatic threshold retuning or downstream opening.
