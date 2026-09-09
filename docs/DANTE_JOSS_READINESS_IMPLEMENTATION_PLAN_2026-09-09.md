# DANTE JOSS readiness and archival release plan

Status: **IN PROGRESS**

## Objective

Prepare the released DANTE workflow for independent software review and a
future Journal of Open Source Software (JOSS) submission without changing any
scientific score, population, threshold, null construction, detector
semantics, or adopted corrected-O4a artifact.

The architecture preprint is public as
[`arXiv:2609.08695`](https://arxiv.org/abs/2609.08695). The immutable
`dante-workflow-productization-v1` tag remains the software baseline cited by
that preprint and must never be moved.

## Release boundary

Before J4, the root `CITATION.cff` described DANTE release `3.7.0` and DOI
`10.5281/zenodo.21912589`. It now identifies 3.8.0 with the reserved version
DOI `10.5281/zenodo.22681395`. The old DOI remains valid only for the archived
3.7.0 software record.

The first archival release prepared by this plan is version `3.8.0` with the
new immutable tag `v3.8.0`. The choice does not rewrite either historical tag.
The 3.8.0 version DOI must be reserved in a new-version draft under the existing
Zenodo concept before the final tag so the immutable release metadata can name
the correct DOI.

## Progress

| Increment | Status | Evidence or next gate |
|---|---|---|
| J1 public metadata and policy | Complete | Commit `9580624`; 121 workflow tests passed. |
| J2 installation and packaging | Complete locally | Hybrid Option B; wheel/base/UI isolation and CLI run-key parity passed; 125 Windows and 124+1-skip WSL workflow tests passed. |
| J3 clean-environment reproduction | Complete | Fresh GitHub HTTPS clone, isolated install, CPU smoke/retry/verify, UI discovery, 14 focused tests, and hosted CI passed. No external human pre-review is claimed; the checklist remains available for optional community validation. |
| J4 archival release | DOI reserved; final verification | Version `3.8.0`, DOI `10.5281/zenodo.22681395`; final metadata/build/test checks precede the tag. GitHub Release and Zenodo publication remain human checkpoints. |
| J5 JOSS manuscript/submission | Pending | Requires J3/J4 and the public-history gate. |

## Dependency order

```text
Public arXiv record
        |
        v
Open-source policy and citation metadata
        |
        v
Install/package boundary and reviewer smoke
        |
        v
Independent clean-clone reproduction
        |
        v
Reserve Zenodo version DOI
        |
        v
Release identity verification
        |
        v
Tag and GitHub Release -> publish reserved Zenodo version
        |
        v
JOSS paper and submission
```

## J1 — Public metadata and project policy

Files:

- `README.md`
- `CITATION.cff`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `GOVERNANCE.md`
- `SUPPORT.md`

Acceptance:

- the public architecture preprint is linked and citable;
- contribution, conduct, governance, and support expectations are explicit;
- the historical 3.7.0 DOI is not relabelled as a workflow-productization DOI;
- YAML and repository links validate;
- scientific contracts and adopted artifacts remain byte-identical.

## J2 — Installation and packaging boundary

Goal: provide a conventional Python installation surface without changing the
scientific runtime or silently replacing the pinned CPU and CUDA environments.

Before implementation, audit imports, entry points, package data, and current
clean-clone commands. Introducing `pyproject.toml` or console entry points is a
structural release change and requires its own reviewed increment.

Acceptance:

- a clean Python 3.11 environment installs the bounded public workflow;
- the documented CLI and UI entry points resolve the same run identity;
- existing `requirements-cpu.txt` and `requirements-ui.txt` remain the
  authoritative environment locks unless explicitly superseded;
- regression and public-smoke tests pass on Windows and WSL.

## J3 — Clean-environment reproduction evidence

Run the public CPU smoke from a new WSL-native clone using only documented
commands. The published branch was also exercised by GitHub-hosted CI. No
external colleague was available for a separate pre-submission run, so this
checkpoint is explicitly not described as independent human reproduction.
JOSS reviewers will perform their own installation and functional checks. The
[`DANTE_JOSS_EXTERNAL_REPRODUCTION_CHECKLIST.md`](DANTE_JOSS_EXTERNAL_REPRODUCTION_CHECKLIST.md)
remains available for optional community validation without being represented
as completed evidence.

Acceptance:

- no undocumented path, parameter, or scientific choice is required;
- start, resume, progress, logs, report, and receipt are discoverable;
- failures are actionable and no full-O4a claim is inferred from the bounded
  smoke;
- the evidence record distinguishes automated clean-environment reproduction,
  maintainer usability acceptance, and unavailable external human pre-review.

## J4 — Archival software release

Version `3.8.0` distinguishes the JOSS-ready software from both `3.7.0` and the
immutable architecture-paper baseline tag. Package, citation, license,
changelog, and release-note metadata are prepared before creating the tag.
Tagging, GitHub Release creation, and Zenodo publication remain explicit human
checkpoints.

Acceptance:

- version, date, title, authorship, repository URL, arXiv relation, and license
  agree across `CITATION.cff`, README, tag, and GitHub Release;
- the release is created from a clean, verified commit;
- Zenodo archives that exact tag and assigns a version DOI;
- the DOI resolves to files and metadata matching the GitHub release.

## J5 — JOSS manuscript

Create the required `paper.md` and bibliography in the repository. The paper
will describe the research-software contribution, not introduce new O4a
results. It will disclose the related architecture preprint and the verified
use of generative-AI assistance.

Submission occurs only after the repository has more than six months of public
development history and all current JOSS screening requirements have been
rechecked against the live author guide.

## Out of scope

- recomputing corrected O4a;
- promoting DANTE-Light v8.1;
- adapting the workflow to O3a, O4b, or O5;
- changing statistical or scientific contracts;
- claiming global significance, discovery, or public real-time operation.

Those are separate scientific or product increments and do not block a review
of the frozen productized workflow.
