# Profile-specific primary GPS coverage - 2026-10-02

Author decision A: common engine, unchanged approved selection per profile.
O3a remains diagnostically closed. No universal CBC_CAT1 filter is introduced.

## Operator command

```powershell
python scripts/run_dante_workflow.py coverage-readiness --repository-root C:\Users\atafe\PycharmProjects\dante-gravi-signal-ml --observing-run O4a --detectors H1 L1
```

The command resolves the explicit registered workflow and audited adapter,
without constructing an orchestrator, ledger or worker. Unknown/unbound
profiles and detector scopes do not fall back to O4a. Synthetic V1 test data
demonstrate detector locality, not scientific Virgo qualification.

## What is measured

The common inspector first checks the existing input binding. It then uses
explicit profile field selectors for primary population counts/digest, raw
manifest spans, analysis duration, padding and the original selector source.
No scientific numeric value is invented or selected from chat.

Half-open context intervals must match the declared geometry exactly and be
covered by the union of that detector's manifest spans. Touching/overlapping
spans may cover an interval; any gap, incomplete edge, foreign detector,
duplicate/reordered identity or changed full-row digest fails closed. There
is no tolerance or integer-rounding workaround. Referenced bytes are checked
before iteration and again at completion; unreadable inputs are errors.

Corrected-O4a reuses the unchanged `iter_scan_identities` in
`src/dante_light/o4a_corrected_protocol.py`, not `build_corrected_protocol`.
Its original eligible population requires complete context and no retained
raw-validity exclusion. The observed selector does not add CBC flag filtering.
The common inspector applies no additional DQ policy. The historical audit is
consumed as pinned metadata, not remeasured against physical samples.

## Bounded meaning of PASS

`PASS_PRIMARY_SCAN_MANIFEST_COVERAGE_ONLY` proves the declared primary metadata
population's GPS/context coverage and exact full identity digest/counts.
It is not complete public-run coverage, physical raw presence or sample-grid
validation, current DQ flag eligibility, calibration input coverage, runtime
equivalence, writer exclusion or scientific execution authorization.

`scientific_execution_ready`, `raw_samples_checked`,
`dq_flag_eligibility_checked`, `calibration_coverage_checked`,
`live_coverage_checked` and `runtime_equivalence_checked` remain false.
Files are observed during the inspection, not under an atomic snapshot or
writer-exclusion lock. This is not a reusable admission receipt.

The standalone command loads the existing scientific selector in the existing
scientific environment. The common package imports remain dependency-light;
they do not import that selector until this explicit coverage operation.
No calibration HDF5, runtime fingerprint, GPU job, download, scoring or outcome
reader is invoked. Metadata replay can read original pinned source/audit files
and read-only Git references. It is not a clean-install numerical execution.

## Evidence

Source freeze `9fc224e14f865b7b0fefc2516ed722eb7d8056c7`.

- 38 new coverage tests. Final sixteen-file common workflow regression:
  Windows318 PASS/OSexit0/55.71s; WSL317 PASS/one Windows-only skip/
  OSexit0/138.47s. Post-freeze input/coverage/CLI/packaging80 PASS/
  OSexit0/16.08s. Ruff five Python files lint/format PASS.
- One post-freeze standalone WSL metadata replay, observed OSexit0:
  `PASS_PRIMARY_SCAN_MANIFEST_COVERAGE_ONLY`, H1=401442, L1=409809,
  total811251, full identity JSONL SHA
  `24d6a3f628f2ab9192e5a17f013ca6b20d6d8e7c47257027323520f7a101e20e`.
  Contract file SHA `d88535676a73301c329e3f942a140b6557c6499a6fb2fc66eb966f4a7bb875dc`,
  seal `326495389f511b378c52b2a99f7771bd13d87d6852d4191a4f0fb61d6842d4fa`.
  Selector source SHA and overlapping-span audit SHA match the frozen contract.
- Base-package import without loading the scientific selector PASS. Three
  historical EOL-qualified scientific source SHA values remain unchanged.
- First full WSL suite had one UI detached-launch timeout at its unchanged
  15s limit:316 PASS/one skip/one failure. Isolated unchanged test then passed
  (1 PASS/9.97s), and the full repeat above passed. No timeout/test relaxation
  or UI/scientific code change; underlying transient latency is not established.

No productive analysis was started, no scientific config/source was edited,
and no outcome was read. Existing user folders remain untouched; local commits
only on `science/o3-transfer-readiness`, no push/merge/release.

## Next gate

Complete the approved profile's calibration input coverage, then bounded real
raw-to-result execution and independent verification from a clean install.
Other-run/V1 population, DQ, reference and statistical contracts require
separate qualification. This increment changes no scientific config/source,
registry activation or existing productive/retained stage command.
