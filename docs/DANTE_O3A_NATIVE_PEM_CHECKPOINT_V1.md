# O3a native PEM diagnostic checkpoint v1

Date: 2026-09-27 Europe/Rome. Scope: O3a-only; no O4a comparison.

## Frozen inputs and execution

- Contract: `config/dante_o3a_native_pem_v1.json`, digest
  `a7f4202ff8d85ffb46efdb456ebcb25cc1a14b27b30cea0a64ee7ab198d05a87`;
  source-freeze commit `eb7f6d4`.
- Input preflight digest:
  `02e36df7a1a6d5074c22ca1c4b93e827666dfa118eaafd42257633acbe843cc6`.
  It selected 11 ROBUST primary and one AMBIGUOUS diagnostic target, and
  sealed all 8,900 classified O3a identities for candidate exclusion.
- External run: `E:\dante_cache\dante_light\o3a_native_v1\native_pem_o3a_75a40541a8122aceb35e3c68a723f6a75108b0f5cf9f14ca65529151e5e0eb3e`.
  Run summary status `PASS_COMPLETE_O3A_NATIVE_PEM_V1`, artifact digest
  `8cbfeae700857af0f5ca46054dad9c347a061088764aa881d80d0bd2283b2504`.
  The launch did not preserve an OS exit code; no `--run` exit-code claim is made.
- Standalone `--stage verify` exited 0. Compact receipt
  `artifacts/dante_light/o3a_native_v1/native_pem.json` has
  `PASS_VERIFIED_O3A_NATIVE_PEM_V1`, digest
  `263ed1744dc2dece021d8dd298ad5b5d5c3c8439f78258db4bc9368cc8471e03`.
  It rechecked parents, exact targets, event/calibration seals, source hashes,
  target accounting and empty transient raw cache. It is a structural replay,
  not an independent recomputation of the full PEM null.
- Post-run WSL O3a/PatchProducer tests: 194 passed, 11 upstream warnings.
  Ruff passed on the O3a PEM adapter, runner and tests. The frozen source
  files were unchanged during execution.

## Verified diagnostic outcomes

| Population | Detector | Calibrated | COUPLED | NO_CORRELATION |
| --- | --- | ---: | ---: | ---: |
| ROBUST primary | H1 | 2 | 1 | 1 |
| ROBUST primary | L1 | 9 | 0 | 9 |
| AMBIGUOUS diagnostic | H1 | 1 | 0 | 1 |

The coupled H1 primary target is GPS `1253581920`. Its top tested channel
is `H1:LSC-POP_A_LF_OUT_DQ` (peak coherence 0.5363456117 at 390.5 Hz);
the time-shift control is 0.3555665314 and the quiet zero-lag control is
0.5035300851. This supports a *diagnostic environmental-coupling flag* for
that target, not an astrophysical identification. No primary/diagnostic
pooling is performed. There is no genuinely promising astrophysical shortlist
established by this stage, and no external candidate communication is made.

The five publicly common auxiliary channels per detector are a limited subset,
not a complete sensor network. `NO_CORRELATION` means only that this particular
test did not find coupling within that subset. The 4-hour event-local null
uses guarded 32-second background windows as bootstrap units; shared-window
pairs are not bootstrapped independently. This diagnostic does not establish
global significance, a false-alarm rate, environmental innocence or an
astrophysical origin. A2 is not promoted. The O4a paired comparison remains
blocked by its separate raw-receipt and `.gitattributes` provenance gate;
neither gate was bypassed or changed here.
