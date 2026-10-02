---
phase: 08-multi-run-productization
plan: 23
status: passed_input_binding_only
---

# 08.23: common input binding readiness

Implemented a common read-only inspector, deny-by-default adapter capability,
explicit corrected-O4a frozen field mapping and `input-readiness` CLI without
ledger/worker creation. No new schema/scientific values or production profile.
Source freeze: fd9e1649a662fec14d112d6fd556f52717438b94 (six exact staged files).
The bounded PASS cannot establish exact GPS/DQ coverage, raw sample validity,
runtime equivalence, writer exclusion or scientific execution readiness.

## Verification evidence

- 33 new tests cover synthetic O2/O3a/O4a labels/scopes, immutable selectors,
  absent mappings, missing/altered metadata, path/symlink rejection, malformed
  reference/SHA/JSON/seal, contract drift and CLI no-state/no-fallback behaviour.
- Focused Windows: 88 PASS, OSexit0,1.54s. Fifteen-file Windows common workflow:
  280 PASS, OSexit0,47.39s. Same fifteen-file WSL common regression:
  279 PASS/one Windows-only skip, OSexit0,117.76s.
- Ruff lint and format check on five Python files PASS.
- Post-freeze WSL input/CLI/packaging42 PASS, OSexit0,30.27s; standalone WSL
  checkout command observed OSexit0/input-binding PASS. Base-package imports
  with only src/ on sys.path PASS; not a clean-install numerical validation.
- Real metadata-only probe: input-binding PASS, five exact input references,
  eight declarations; GPS/scientific readiness explicitly false.
- Three historical EOL-qualified scientific helper SHA values unchanged.

## Deviations and boundaries

The existing operational release PREFLIGHT is not a target GPS coverage proof.
The approved preflight increment is deliberately split at input binding rather
than inventing a generic population/DQ/sample validator. O4a's parent is a
frozen local mirror; no whole-run assumption is introduced. Two initial read
paths were absent and corrected read-only. Initial standalone probe exposed
the strict JSON helper's required label; fixed before tests. Initial Ruff
found one unused test import; removed. Formatter also reformatted two existing
administrative adapter method signatures. No scientific source/config edits,
raw/science access, historical replay, GPU change, push, merge or release.

Next: exact requested GPS/DQ/context gate from approved profile evidence;
clean-install numerical execution afterwards. Other-run/V1 decisions remain.
