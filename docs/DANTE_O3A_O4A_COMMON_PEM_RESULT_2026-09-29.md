# O3a/O4a public common-channel PEM — verified diagnostic result

Both separate runs use the frozen five publicly common auxiliary channels per
detector and the same corrected-O4a coherence, time-shift, quiet-zero-lag and
window-block-bootstrap core. They retain their own target populations, CAT1
intervals, candidate exclusions and nulls. This is a method-parity diagnostic,
not a matched-population experiment or a global-significance test.

## Execution and provenance

- Source freeze: `d019d2d21ad86982bd46797abe13b7c749ebd923` on
  `science/o3-transfer-readiness`. The seven source/config SHA-256 values in
  the sealed plan still match local bytes; tracked Git files were clean before
  this checkpoint update.
- Sealed plan:
  `E:\dante_cache\dante_light\o3a_o4a_common_pem_v1\comparative_pem\plan_69e581fac3bafa24eab1cfe1fabed2922da10c465b18a77efad7f62eea015719.json`.
  Its parent, target, full exclusion, live O3a CAT1, O4a numerical-context,
  background-span, auxiliary-sample and source checks passed with OS exit 0.
- O3a run key `549334bf4a444aa5d6f0a9a4afe02ec3ae4233dee19d2cd0836ef085061d9f03`:
  production OS exit 0, `PASS_COMPLETE_COMMON_PEM_DIAGNOSTIC_V1`, 12 sealed
  event receipts. Independent `--stage verify --run O3a` exited 0 and returns
  `PASS_VERIFIED_COMMON_PEM_DIAGNOSTIC_V1`. Summary digest:
  `bd7fdf82d170a0a8c82fe45cd7137e8f069dd199d7febeaa201e5321ace9f9f7`.
- O4a run key `d1986c0f009316222f07a8f4504815283ca8384644aa302c347c6caabb9c0b45`:
  production OS exit 0, `PASS_COMPLETE_COMMON_PEM_DIAGNOSTIC_V1`, 65 sealed
  event receipts. Independent `--stage verify --run O4a` exited 0 with
  `PASS_VERIFIED_COMMON_PEM_DIAGNOSTIC_V1`. Summary digest:
  `ed12d4c398cbd47f7045357aad12d8514124a809a258ad84ce5b85b9cbac2cd0`.
- Both runs have zero failure files, partial files and controller locks. The
  verifier recomputed receipt sets, parent/source bindings and verdict
  arithmetic. Post-run WSL common-PEM/native-PEM/PatchProducer regression:
  106 passed, 11 upstream deprecation warnings. Ruff lint and format passed.
- The verifier binds `git rev-parse HEAD` to the source-freeze revision. A
  later documentation commit changes HEAD without changing measured bytes;
  exact standalone verifier replay therefore requires a checkout of
  `d019d2d21ad86982bd46797abe13b7c749ebd923` (and the same verified
  external parents), not the later checkpoint-documentation HEAD.

## Verified five-channel verdicts

`COUPLED` exceeds the frozen quiet-zero-lag quantile; `SUSPECT` exceeds the
time-shift threshold but not that quantile; `NO_CORRELATION` exceeds neither.
These are spectral/full-window PEM diagnostics, not time-localized causal
attributions. Primary and diagnostic target sets are never pooled.

| Run | Population | Detector | COUPLED | SUSPECT | NO_CORRELATION | Total |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| O3a | primary | H1 | 1 | 0 | 1 | 2 |
| O3a | primary | L1 | 0 | 0 | 9 | 9 |
| O3a | diagnostic | H1 | 0 | 0 | 1 | 1 |
| O4a | primary | H1 | 1 | 1 | 1 | 3 |
| O4a | primary | L1 | 2 | 0 | 4 | 6 |
| O4a | diagnostic | H1 | 2 | 2 | 27 | 31 |
| O4a | diagnostic | L1 | 1 | 1 | 23 | 25 |

The O3a primary H1 `COUPLED` record is GPS 1253581920, with top tested
channel `H1:LSC-POP_A_LF_OUT_DQ`. This is the same descriptive coupling
already noted in the O3a-only PEM checkpoint, not a newly established cause
of its selected low-frequency arch. The O4a primary `COUPLED` records are
H1 GPS 1369305280 (top channel `H1:LSC-POP_A_LF_OUT_DQ`) and L1 GPS
1375165280 and 1383544032 (top channel
`L1:ASC-X_TR_A_NSUM_OUT_DQ`). H1 GPS 1378749856 is `SUSPECT`: passing the
time-shift threshold alone is not sufficient for a coupling claim under the
quiet-zero-lag control. These labels do not establish physical causation.

The numerical counts cannot be interpreted as an O3a-versus-O4a change in
instrumental coupling prevalence: the frozen target sets and primary/diagnostic
mix differ substantially (12 versus 65 records), and no rate-comparison null
or selection model was preregistered. `NO_CORRELATION` tests only the five
public common channels and does not clear unavailable or untested channels.
In particular, the two previously described CAT2/3-clean L1 O3a residuals
remain diagnostic-only, not promoted by this comparison. No result here
supports global significance, astrophysical origin, or external candidate
communication. Any localized timing, broader-channel, or rate-comparison
protocol would be a new scientific decision.
