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

## Launch record

Source and contract committed/pushed as `b87db6a` before fitting. The --run
worker was launched at 18:00 Europe/Rome on 2026-09-24. One WSL Python
instance was observed (PID 422), with no stderr output at the first check.
The run key is
`1bd630e29eda34be625f6bbd325b60d114d7f4dc2508a8c09c81263127f35405`.
The external directory is under `E:\dante_cache\dante_light\o3a_native_v1`.
The existing hourly monitor was repointed to thresholds; it must not duplicate
the worker, must run independent --verify only after successful fitting, and
must stop for failure review. No completion or threshold result is claimed
by this launch record.

## Verified completion

The fit completed at 18:04:49 Europe/Rome. Independent --verify completed
at 19:05:41 and returned captured exit code 0. The initial launch exit code
was not persisted and is not claimed. Both deterministic calculations match.

| Detector | p99 | 95% percentile-bootstrap CI | Absolute width | Width / p99 |
|---|---:|---|---:|---:|
| H1 | 0.4057316654920578 | [0.4015953540802002, 0.40964144468307495] | 0.008046090602874756 | 1.9831063944976357% |
| L1 | 0.41683934092521674 | [0.41297605633735657, 0.4202978295087814] | 0.00732177317142485 | 1.7564976365170907% |

No post-hoc precision cutoff was applied. Both detectors have exactly5000
point rows and4998 bootstrap rows (294 blocks of17;2 point-only tail rows).
Post-run regression:122 tests passed,11 upstream warnings,86.74s.
Source/receipt/summary consistency audit passed, retaining the EOL caveats.
Verified compact artifact:
`32890633207ebb91839131b972dc0ca18650ceb3fe18383fb9adee3bed6ce281`.
Summary artifact:
`30671367d022c1a935a446313ea65f4b0457f6b85b2cc8f2107e94055b1d1d79`.

The user subsequently authorized CLASSIFY after this gate. It will use the
already-frozen detector-local CI boundary rule, with equality classified
AMBIGUOUS. No other downstream stage is authorized by that follow-up.
