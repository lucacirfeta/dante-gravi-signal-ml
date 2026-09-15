# DANTE 3.8.1 release notes

DANTE 3.8.1 is a provenance-transparency maintenance release. It publishes the
compact evidence from the complete canonical-source rerun of the corrected O4a
native chain and corrects the project's earlier, overly strong explanation of
an unretained working-tree source digest.

## Result

The frozen ten-stage chain from `COHORT` through `COMPARE` was recomputed with
Git-recoverable canonical source. The final comparison is
`PASS_VERIFIED_CANONICAL_FINAL_COMPARISON` and all scientific outputs are
byte-identical to the retained corrected-O4a outputs. No score, population,
threshold, class, taxonomy, coincidence selection, PEM disposition, numerical
result, or scientific conclusion changes in this release.

The historical digest beginning `2c20...` remains unrecoverable. Therefore this
release does not claim to reconstruct those lost bytes. It records the gap,
preserves the earlier 12-window reconciliation as historical evidence, and
replaces subset-based reassurance with a complete empirical recomputation.

## Included evidence

- the full public transparency note;
- ten compact, verified stage records from `COHORT` through `COMPARE`;
- a deterministic manifest containing SHA-256 checksums, run keys, contract
  digests, and the canonical-rerun source commit;
- a claim-to-artifact map for auditing public statements.
- an LF checkout rule for every canonical-provenance contract and runtime
  amendment, so fail-closed SHA-256 gates remain stable with Windows
  `core.autocrlf=true` as well as in WSL-native checkouts.

Build the compact evidence archive with:

```console
python scripts/build_o4a_provenance_release_bundle.py
```

The resulting `dante-o4a-provenance-evidence-v3.8.1.zip` is an evidence
supplement to the source release. It contains no raw GWOSC strain, model cache,
credentials, or machine-local paths.

## Release verification

The release candidate passed 134 focused regressions on Windows and 133 on
WSL, with one expected platform skip. Ruff, archive-layout and metadata checks,
a fresh Python 3.11 wheel installation including the optional browser UI, and
the bounded public CPU smoke all passed. The smoke was then reopened through
the verification-only path and accepted only after its recorded files matched
their hashes.

## Scope

This is not a new paper, a new O4a analysis, or a discovery claim. The corrected
science remains unchanged. Short cross-references may be added to affected
public records so that readers of those records can find this append-only
provenance correction; those links do not republish or replace the papers.

The reserved 3.8.1 version DOI is
[`10.5281/zenodo.22763556`](https://doi.org/10.5281/zenodo.22763556). It becomes
registered when the Zenodo draft is published. The previous 3.8.0 archive
remains immutable at `10.5281/zenodo.22681395`.
