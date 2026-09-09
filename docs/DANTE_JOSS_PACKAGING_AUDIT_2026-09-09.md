# DANTE JOSS packaging audit

Status: **DECISION REQUIRED BEFORE IMPLEMENTATION**

## Scope

This audit covers the bounded productized workflow and public technical smoke.
It does not change scientific code, configuration, artifacts, thresholds,
populations, or validation rules.

## Findings

1. The repository has no `pyproject.toml`, build backend, wheel metadata, or
   installed console scripts.
2. The supported launchers are `scripts/run_dante_workflow.py`,
   `scripts/run_dante_workflow_ui.py`, and
   `scripts/run_dante_workflow_clean_clone.py`.
3. Those launchers insert the checkout root into `sys.path` and import
   `src.*`. Tests and scientific scripts follow the same repository import
   convention.
4. The productized adapter delegates to versioned scripts under `scripts/` and
   resolves scientific configuration under `config/`. The public smoke also
   invokes root `main.py` and validates root-relative references.
5. The UI requires Jinja templates and static assets under
   `src/dante_workflow/ui/`; a wheel would need explicit package-data rules.
6. The Docker image copies the whole repository and runs the same source-tree
   smoke, so it validates the repository application but not wheel installation.
7. The existing source-checkout installation has already passed clean-clone
   CPU, UI, resume, receipt, and report checks. Lack of wheel metadata does not
   invalidate that evidence.

## Options

### A. Keep a repository application

Document `git clone` plus the pinned requirements as the installation method,
retain the current scripts, and make no wheel claim.

- Lowest provenance risk and smallest review surface.
- Faithful to the architecture paper and existing clean-clone evidence.
- Reviewers cannot use `pip install .` or installed console commands.

### B. Package only the orchestration library

Publish `dante_workflow` as a conventional package, but keep full scientific
execution checkout-bound.

- Gives reusable schema/state/orchestration APIs.
- Requires migrating the current `src.dante_workflow` import namespace or
  deliberately supporting a compatibility layer.
- Installed CLI semantics would differ from the checkout-only scientific
  workflow unless that boundary is made explicit.

### C. Package the complete repository application

Include workflow, shared core, DANTE-Light modules, scripts, configuration,
templates, and static assets in a wheel with installed CLI/UI entry points.

- Provides the most conventional installation experience.
- Creates the largest accidental public API and packaging surface.
- Requires replacing root-relative resource discovery, defining mutable output
  locations, and revalidating every subprocess and provenance path.
- A wheel-only full corrected-O4a claim would still be impossible without the
  external raw archive and historical environment.

## JOSS requirement check

The current JOSS guidance says that software should be packaged according to
the conventions of its language; its Python example is `pip install`-able
software. The review criteria also allow dependency installation driven by an
automated source procedure, but that is the weaker assessment. Sources:

- <https://joss.readthedocs.io/en/latest/submitting.html#submission-requirements>
- <https://joss.readthedocs.io/en/latest/review_criteria.html#installation-instructions>

Option A is therefore a valid description of the present evidence, but it is
not the strongest JOSS submission state for a Python project.

## Recommendation

Use **Option B for the JOSS software boundary**: package the reusable
content-addressed orchestration library and provide an installed controller,
while retaining a source checkout as an explicit requirement for the complete
corrected-O4a stage scripts and public replay.

The implementation should be additive:

1. map `src/dante_workflow` to the installed package name `dante_workflow`;
2. move shared CLI parsing/control into package modules and leave repository
   scripts as compatibility wrappers;
3. include Flask templates and static files explicitly;
4. require or discover an explicit repository root for operations that consume
   root `config/`, `scripts/`, or `main.py`;
5. test wheel installation, editable installation, installed CLI/UI startup,
   checkout compatibility, and run-key parity;
6. make no claim that the wheel alone contains the scientific data, frozen
   model assets, or full corrected-O4a runtime.

Do not select Option C without a dedicated structural design and a new
clean-clone validation matrix.

## Required decision

Confirm whether the first JOSS-ready release adopts the recommended hybrid
Option B, remains a source-checkout application with the resulting JOSS risk
(Option A), or attempts the full application wheel (Option C). No package
metadata or import migration should be implemented before that choice.
