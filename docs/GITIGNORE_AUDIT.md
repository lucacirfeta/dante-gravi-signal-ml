# Repository ignore audit

Audit date: 2026-08-22

## Policy

The repository tracks code, configuration, tests, user documentation, paper
sources and the compact final artefacts required by the versioned v6
reproducibility allowlist. It does not track raw GWOSC strain, auxiliary
channel downloads, model or token caches, generated spectrogram collections,
compiled PDFs, LaTeX intermediates, logs, scratch work, archived stale runs,
credentials or machine-specific agent configuration.

The authoritative published-paper selection is implemented by
`scripts/build_paper_reproducibility_bundle.py`. Files selected by that builder
are intentionally tracked even when a broader legacy ignore rule matches their
directory or suffix. Their hashes and final-status checks are verified by the
bundle test; this avoids exposing the rest of `data/production` or
`paper_draft`.

## Findings

- Approximately 31.5 GiB under `data` are raw or regenerable products and
  remain ignored.
- The final v6 allowlist previously depended on 225 local-but-untracked files
  (about 14.6 MiB), so bundle tests could pass in the working copy while a clean
  clone lacked the scientific evidence. Those allowlisted files are now
  tracked.
- arXiv manuscript figures were absent from the bundle selection even though
  `arxiv_v6/main.tex` references them. Both manuscript figure sets are now
  selected and checked explicitly.
- `AGENTS.md` is repository-specific scientific and contribution policy and is
  tracked.
- Legacy pilot scripts, temporary patch scripts, obsolete run wrappers and
  private GSD/Memorix configuration remain ignored. They are neither called by
  the supported CLI nor selected by the reproducibility bundle.

## Clean-clone invariant

For every path returned by `source_paths()` in the bundle builder:

1. the path must be tracked by Git;
2. its recorded provenance/hash checks must pass;
3. manuscript sources must have every referenced figure present;
4. no raw data, credential, pilot or stale path may enter the bundle;
5. the sole archive exception is the immutable 1.6 MB pre-fix taxonomy needed
   to reconstruct the detector-aware representation transition.

The 73 MB native O4a index remains outside Git. Its path and SHA256 are
versioned in `config/reference_artifacts.json` and the published reference
bundle is acquired and verified by `scripts/manage_reference_artifacts.py`.

The 312 MB P5 token cache also remains ignored. L4 split regeneration uses the
compact, self-hashed candidate-key projection in
`config/dante_light_prefilter_robust_candidates_v1.json`; it records the
original cache path and SHA256 and reproduces the frozen split hashes exactly.

This invariant is checked in `tests/test_paper_reproducibility_bundle.py`.
