# DANTE O4a native-source provenance transparency note

Status: draft pending completion of the canonical full rerun

Prepared: 2026-09-12

## Purpose

This note records a provenance limitation in the corrected O4a native-index
chain, the earlier attempt to reconcile it, and the complete rerun undertaken
to close the uncertainty. It will be published as an append-only correction to
the project record regardless of whether the rerun changes any output.

## What was not retained

The original native cohort, native index, and first native rescore contracts
recorded the SHA-256 digest
`2c20d4e89b48060986770127bf41c2d860d22efc4f98f430cb152cfb71f39dcf`
for the working-tree bytes of `src/core/patch_producer.py`. Those exact bytes
were used as a run-time provenance gate, but they were not committed or retained
as a separate source snapshot and are not recoverable from reachable or
unreachable Git objects currently available to the project.

The retained canonical LF-normalized source has digest
`67b858e2ed6e6b0451cf29040f0a39ba98b29828460b5094be6d2f47012f7fef`
and is recoverable from Git. The lost digest is neither this LF digest nor the
digest of a uniform CRLF conversion. The project therefore cannot prove from
retained bytes alone that the lost working-tree source was semantically
identical to the canonical tracked source.

## Why the 2026-09-04 reconciliation was insufficient

The reconciliation published on 2026-09-04 correctly stated that the original
byte representation was not retained and identified a canonical tracked source.
It also performed a successful 12-window WSL replay. However, it classified the
gap as a line-ending reconciliation, declared no full rerun necessary, and
treated the subset replay as sufficient to close the provenance question.

That conclusion was too strong. The subset replay provides useful evidence of
agreement on those 12 windows, but it cannot establish the identity of an
unretained source over the complete 1,294-window index cohort and all downstream
scores, thresholds, classes, taxonomy, coincidence, PEM, and comparison outputs.
The earlier reconciliation remains preserved as historical evidence and is not
silently replaced.

## Public records affected by the incomplete explanation

The following records were created while the 2026-09-04 reconciliation was the
project's stated resolution of the source-identity gap and therefore require an
explicit transparency cross-reference:

- the corrected-science preprint record, arXiv:2606.25702;
- the workflow-architecture preprint, arXiv:2609.08695;
- GitHub release `v3.8.0`;
- Zenodo record 22681395, DOI `10.5281/zenodo.22681395`;
- the project discussion associated with IGWN thread 1544, to the extent that
  it cites results derived from the affected chain.

This does not by itself establish that any reported scientific value is wrong.
It establishes that the source identity supporting the chain was not as fully
reproducible as the public reconciliation implied.

## Remediation protocol

The project froze a new fail-closed protocol before inspecting new outcomes. It
recomputes, with Git-recoverable canonical source and separate immutable output
roots:

`COHORT -> INDEX -> NATIVE_CALIBRATION -> RESCORE -> THRESHOLDS -> CLASSIFY -> TAXONOMY -> COINCIDENCE -> PEM -> COMPARE`.

The scientific populations, preprocessing, representation, clustering, scoring,
block-bootstrap, thresholds, classification, taxonomy, coincidence, PEM, and
comparison rules remain unchanged. Each stage is verified independently and its
new output is compared with the retained historical output at byte level or
under an already versioned numerical tolerance. No tolerance may be introduced
after outcomes are inspected.

## Rerun result

Pending. This section will report:

- canonical contracts and run identifiers;
- byte-level and numerical comparison status for every stage;
- any changed identities, scores, thresholds, classes, families, coincidence
  selections, PEM dispositions, or final-comparison claims;
- direct source-sensitive changes separately from downstream recalibration
  effects;
- the status of GPS 1382955253.17 under the recomputed chain.

## Interpretation and record updates

Pending. If every output is identical or numerically equivalent, the conclusion
will be limited to empirical equivalence under the frozen comparison protocol;
it will not retroactively make the lost source bytes recoverable or the earlier
explanation precise. If anything changes, the impact will be quantified before
any scientific text is updated.

The final note and any GitHub, Zenodo, arXiv, or IGWN update will be prepared for
human review and will not be published automatically.
