---
phase: 07-o3a-transfer-readiness
plan: 20
subgate: common-pem-aux-native-samples
verified: 2026-09-29
status: passed
score: 5/5 must-haves verified
is_re_verification: false
---

# Common-PEM auxiliary native sample subgate verification

This verifies only exact retained auxiliary samples for the frozen 77-target
O3a/O4a five-common-channel comparison. The broader 07-20 comparative PEM
gate remains open.

| Observable truth | Status | Empirical evidence |
| --- | --- | --- |
| Parent population and channel intervals remain frozen | VERIFIED | Plan key `df2a8c05f158d491d577ecf80cebae0ac2ea61b9158c2ef61fb96bedf4081b11`; parent metadata re-query PASS for 77 targets; verifier checked parent seals. |
| Native samples are retained without resampling or cast | VERIFIED | 750 native-rate float32 NPY files, 84,158,251,008 sample bytes, native geometry/unit/channel in sealed receipts. |
| Every retained file has one complete source-bound receipt | VERIFIED | Exact 750 receipt/file sets; numerical and whole-file SHA-256 replay; no orphan, partial, failure or lock. |
| Independent local replay passes | VERIFIED | Standalone `--stage verify` OS exit 0, `PASS_VERIFIED_AUX_NATIVE_SAMPLES_ONLY`, count 750; stderr empty. No second NDS2 fetch is claimed. |
| Scientific boundary remains closed | VERIFIED | Summary flags five-channel null and paired outcomes false; no null/verdict/output from this runner. |

The versioned config, substantive acquisition/replay module and CLI runner
are present and wired: the real controller called `acquire_series` once per
unique series and wrote 750 sealed receipts; the standalone CLI called
`verify_series` over the exact retained set. Source SHA-256 for all three
frozen files matches the plan and tracked Git files are clean. Synthetic
tests exercise shared-background identity, chunk geometry, transport
failure, altered dtype/rate/channel/start, nonfinite data, tampering and
orphan-file rejection. Post-run WSL regression: 85 PASS, 11 upstream
warnings; Ruff lint/format PASS. No TODO/FIXME/stub pattern was found in the
modified code.

No human visual verification is required for this transport subgate. The
external NDS2 service's future availability and independently published
auxiliary-frame byte identity are outside this proof: the verifier replays
the retained local samples, not the remote source. No blocker was found for
this subgate. The five-channel null, PEM verdict, global significance and
astrophysical interpretation have not been verified here.
