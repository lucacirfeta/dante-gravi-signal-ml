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

The existing root `CITATION.cff` describes DANTE release `3.7.0` and DOI
`10.5281/zenodo.21912589`. A Zenodo archive must not be generated for a new
workflow release until the repository metadata and the new release identity
agree. The old DOI remains valid only for the archived 3.7.0 software record.

The first archival release prepared by this plan will use a new immutable tag.
Selecting its version identifier is a release checkpoint; it is not inferred
by rewriting the historical tag.

## Progress

| Increment | Status | Evidence or next gate |
|---|---|---|
| J1 public metadata and policy | Complete | Commit `9580624`; 121 workflow tests passed. |
| J2 installation and packaging | Complete locally | Hybrid Option B; wheel/base/UI isolation and CLI run-key parity passed; 125 Windows and 124+1-skip WSL workflow tests passed. |
| J3 independent reproduction | Local rehearsal passed | Clean WSL clone, isolated install, CPU smoke/retry/verify, UI discovery, and 14 focused tests passed; public-source and external-user gates remain. |
| J4 archival release | Pending | Human choice of new version and release metadata. |
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
Release identity checkpoint
        |
        v
GitHub Release -> Zenodo version DOI
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

## J3 — Independent reproduction evidence

Run the public CPU smoke from a new WSL-native clone using only documented
commands. Ask an external user to repeat the installation and smoke workflow,
then preserve only non-sensitive acceptance evidence.

Acceptance:

- no undocumented path, parameter, or scientific choice is required;
- start, resume, progress, logs, report, and receipt are discoverable;
- failures are actionable and no full-O4a claim is inferred from the bounded
  smoke.

## J4 — Archival software release

At a human release checkpoint, choose a new version that distinguishes the
JOSS-ready software from both `3.7.0` and the immutable architecture-paper
baseline tag. Update release metadata before creating the tag.

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
