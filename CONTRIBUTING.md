# Contributing to DANTE

Thank you for considering a contribution to DANTE. The project welcomes bug
reports, documentation improvements, reproducibility reports, tests, and
reviewed code changes.

## Before opening a change

Use a GitHub issue to describe the problem, expected behavior, environment,
and affected workflow stage. For reproducibility failures, include the command,
Python version, operating system, CPU or CUDA selection, traceback, and the
relevant non-sensitive receipt or log path.

Do not attach private detector data, credentials, local absolute paths, or
unredacted environment secrets.

## Development setup

The portable reference environment is Python 3.11 on a WSL-native checkout:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-cpu.txt
python -m pip install -e .
python -m pytest -m smoke -q
```

Install `requirements-ui.txt` only when working on the optional local browser
interface. CUDA and historical scientific environments have separate recorded
identities; passing the CPU smoke does not establish CPU/CUDA numerical
equivalence.

Packaging changes must preserve both installed `dante_workflow` imports and
the checkout compatibility scripts. Run
`python -m pytest -q tests/test_dante_workflow_packaging.py` for that boundary.

## Pull requests

Keep each pull request focused and explain:

1. what changed and why;
2. which files and workflow stages are affected;
3. which tests were run and their exact result;
4. whether any serialized artifact or run identity changed;
5. whether the change affects what is measured or how it is validated.

Add regression coverage for behavioral changes. Run the relevant focused tests
and the public smoke before requesting review. Do not include generated caches,
private data, credentials, or unrelated local outputs.

## Scientific and provenance changes

Changes to scoring, populations, thresholds, calibration, bootstrap or null
construction, detector semantics, preprocessing order, vetoes, or scientific
metrics require an issue and explicit scientific review before implementation.
Never bypass a provenance mismatch, rewrite historical evidence, move a
published tag, or reuse an old run after its scientific interpretation changes.

New scientific runs must use versioned contracts, preserve failed and
superseded attempts, and report bounded claims with machine-readable evidence.

## Review and licensing

The maintainer reviews contributions for scope, correctness, reproducibility,
and compatibility with the scientific contracts. By contributing, you agree
that your contribution is provided under the repository's Apache License 2.0.
Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
