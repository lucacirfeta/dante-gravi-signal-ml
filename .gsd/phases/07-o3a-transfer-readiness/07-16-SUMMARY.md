# 07-16: O3a native thresholds verified

Completed 2026-09-24. Implementation/source freeze: b87db6a; launch: 3f30d03.
Fit PASS at 18:04:49 Europe/Rome. Independent CLI --verify completed at
19:05:41; captured process exit code 0. The original --run launcher did not
persist its exit code; completion is supported by its PASS summary/log and
the later successful deterministic recomputation, not an invented exit code.

Run `1bd630e29eda34be625f6bbd325b60d114d7f4dc2508a8c09c81263127f35405`.
Summary `30671367d022c1a935a446313ea65f4b0457f6b85b2cc8f2107e94055b1d1d79`.
Compact `32890633207ebb91839131b972dc0ca18650ceb3fe18383fb9adee3bed6ce281`.

| Detector | p99 | CI lower | CI upper | Width | Width / p99 |
|---|---:|---:|---:|---:|---:|
| H1 | 0.4057316654920578 | 0.4015953540802002 | 0.40964144468307495 | 0.008046090602874756 | 1.9831063944976357% |
| L1 | 0.41683934092521674 | 0.41297605633735657 | 0.4202978295087814 | 0.00732177317142485 | 1.7564976365170907% |

Exactly 5000 point rows, 4998 bootstrap rows, 294 complete blocks of17 and
2 point-only tail rows per detector. No candidate fitting or detector pooling.
No new width acceptance cutoff. These are threshold uncertainty intervals,
not globally significant candidate detections.

Post-run WSL O3a/PatchProducer tests: 122 passed, 11 upstream deprecation
warnings, 86.74s. Receipt seals, summary file SHA, matching replay values,
cardinalities and all five source hashes checked. Four implementation sources
match Git bytes; contracts.py is exactly recoverable from Git LF->CRLF.
Historical upstream EOL qualifications remain; no files normalized.

No scientific-method deviation. All changes: new adapter/runner/tests and
contract, compact receipt, source EOL rule, checkpoint documentation and STATE.
User has authorized the next CLASSIFY increment; no other downstream opened.
