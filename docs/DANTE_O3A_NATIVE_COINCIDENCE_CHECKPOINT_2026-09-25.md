# O3a native physical coincidence — pre-run checkpoint (2026-09-25)

The author approved strict corrected-O4a method parity for O3a on 2026-09-25.
This checkpoint is frozen **before opening any O3a coincidence outcome**. The
method is band-passed, top-K-patch-localized, light-travel-lag-limited physical
cross-correlation, with eight nominal partner shifts (`+/-1, 2, 4, 8 s`). The
linear p99 diagnostic threshold is computed from **one maximum of eligible
shifted correlations per measured ROBUST seed**, not from eight observations
in total. AMBIGUOUS seeds are measured separately; BACKGROUND is excluded;
partner class and taxonomy family are never consulted. All strain, index,
population and null values are O3a-only.

## Pre-registered statistical limitation and expectation

Each seed has at most eight eligible shifted comparisons, and fewer near
window edges. This small, position-dependent within-seed null set can
undercharacterize its tail. The pooled p99 has one maximum per measured
ROBUST seed (nominally 5,850 seeds); that nominal count does not establish
effective independence or tail precision. Consequently, substantial
threshold uncertainty is plausible. We do not set a post-hoc acceptance
width, infer a confidence interval that this method does not compute, or
interpret an exceedance as corrected global false-alarm significance. Any
result is diagnostic and may only form a PEM review shortlist. A potentially
promising PEM shortlist requires author review before external communication.

## Frozen execution boundary

- Corrected-O4a method remains versioned in
  `config/dante_o4a_corrected_native_coincidence_v1.json`; O3a-specific
  contract: `config/dante_o3a_native_coincidence_v1.json`, digest
  `d0734ae8e6a946d8d741211321f0dce7fc59acf53f76986564ba4a2956962ecf`.
- The source-only preflight passed with digest
  `1e8109c39b2f23d44a7da10ecbe26ba78690f28b318bdab1cdade2e05749c649`.
  Workload: 6,408 seed measurements, 12,782 distinct seed/partner identities,
  4,783 distinct raw frames; one frame is inventory-only and must be pinned
  by SHA-256 before measurement. Complete opposite-detector source coverage
  is unavailable for 885 planned partner identities; this is not negative
  coincidence evidence. No strain or coincidence outcome was opened in this
  preflight.
- Technical replay on a noncandidate O3a raw block reproduced the frozen
  image, clean-window and raw-context SHA-256 values. The real CUDA scorer
  returned the expected 68 top-K patch indices. This is an adapter check,
  **not** an O3a physical-coincidence result.
- Pre-run focused tests: 15 passed. Complete WSL O3a/PatchProducer suite:
  185 passed, 11 upstream deprecation warnings. Ruff passed. The frozen
  contract was independently reloaded and matched the current source bytes.

Execution may proceed without tuning. The historical O4a results and any
earlier O3a stages remain unchanged. A failed structural or scientific gate
stops execution; a verified transport/storage failure may be archived and
resumed only on the same run key from validated shards. PEM begins only after
an independent PASS verification of coincidence and a separate public O3a
channel/method-parity preflight.

The source freeze was committed and pushed as `f79692b` before real execution.
The first O3a coincidence worker started with run key
`713609d1605d2b2a0d2871829a2b91288ce6330510a296021b86977b3c6c4a53`.
It later failed at the frozen 8 GiB transient-cache cap after nine verified
shards. Its failure, partial shards and raw cache are preserved on `E:`;
there is no final stage summary, pooled threshold or PEM shortlist. The
monitor was suspended. The separate cache-remediation checkpoint documents
the authorized execution-order fix and new run; this original pre-run
statistical preregistration remains unchanged.
