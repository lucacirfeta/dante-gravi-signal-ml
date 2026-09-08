# O4a native source-provenance reconciliation — 2026-09-04

## Finding

The three frozen native-v1 contracts recorded the raw-byte SHA-256
`2c20d4e89b48060986770127bf41c2d860d22efc4f98f430cb152cfb71f39dcf`
for `src/core/patch_producer.py`. That exact byte stream is not present in the
reachable Git history, archived runs, or unreachable Git objects.

This was not a transcription error: the native contract validator checked the
working-tree raw-byte digest before the run was created. The retained Git blob
at source commit `68388e6727b8738561a0c40346fce5646d120ecc` and the current source both
normalize under `utf8_lf_v1` to
`67b858e2ed6e6b0451cf29040f0a39ba98b29828460b5094be6d2f47012f7fef`.
The repository already enforces `src/**/*.py text eol=lf`.

The defensible conclusion is therefore narrow: the original byte
representation was not retained, while the canonical LF source was retained.
The record does not claim recovery of the missing raw bytes.

## Numerical check

The canonical WSL preprocessing runtime replayed 12 frozen native-cohort
windows: six H1 and six L1, including two stitched contexts per detector. The
gate requires the frozen Python executable and all preprocessing-relevant
package versions. CUDA, Torch, and the NVIDIA driver are excluded because this
replay performs no encoder or scorer operation. For every window, the
clean-window SHA-256, context-source digest, and excess-power disposition were
identical to the frozen ledger. This is a representative source-level replay,
not a substitute for the already completed full native-index replay.

The machine-readable evidence and exact identities are in
`artifacts/dante_light/o4a_v1_parity/native_patch_producer_provenance_reconciliation_v1.json`.
Run the static verification with:

```text
python scripts/verify_dante_o4a_native_provenance.py
```

Run the numerical replay only in the frozen WSL/CUDA environment:

```text
python scripts/verify_dante_o4a_native_provenance.py \
  --replay \
  --raw-root /mnt/e/o4a \
  --native-external-root /mnt/e/dante_cache/dante_light/o4a_corrected_native_v1
```

## Scientific boundary

No cohort, index, score, threshold, class, or population is changed. No
scientific output is rewritten. The historical contracts remain immutable.
Their exceptional raw-byte reference is accepted only through the exact,
content-addressed reconciliation mapping; all other mismatches remain
fail-closed. The four validators updated to enforce this rule are also mapped
from their frozen raw hashes to their new canonical hashes, explicitly marked
as `provenance_validator_only`. A full scientific rerun is not required by
this finding.

The earlier Windows replay is not evidence for or against numerical equality,
because Windows is outside the frozen canonical runtime. Only the WSL result is
part of this reconciliation.

## Downstream text-byte audit

The full O4a regression exposed two further checkout-byte mismatches with no
content difference. The final-comparison contract recorded the CRLF byte hash
`a01c064d...` of the GPS identity audit before Git stored the same JSON as LF
(`37777885...`). Conversely, the PEM contract correctly recorded the LF hash
`d28b7a4c...`, while a Windows checkout materialized that Markdown file as
CRLF. Both pairs normalize exactly under `utf8_lf_v1`; their validators use the
same exact-pair, fail-closed mechanism. No scientific field or contract was
changed.
