# Common input binding readiness - 2026-10-02

Source freeze fd9e164. Windows280 PASS; WSL279 PASS/one Windows-only skip;
post-freeze WSL42 PASS, all OSexit0. Ruff five Python files lint/format PASS.
Standalone WSL metadata command OSexit0/input-binding PASS. These are software
and metadata checks, not fresh numerical or multi-run scientific qualification.

The author-approved common preflight increment adds `input-readiness`. It
inspects frozen input declarations without running a workflow or reopening
O3a. It does not replace the scientific preflight or authorize acquisition.

## Operator command

```powershell
python scripts/run_dante_workflow.py input-readiness --repository-root C:\Users\atafe\PycharmProjects\dante-gravi-signal-ml --observing-run O4a --detectors H1 L1
```

The installed entry point `dante-workflow input-readiness` accepts the same
arguments. Explicit run/detector selection is required; a missing registered
workflow, unsupported detector or unknown adapter never falls back to O4a.
Raw/cache/workflow paths are not inspected or created by this command.

## What passes

`PASS_INPUT_CONTRACT_BINDING_ONLY` means the scientific input contract matches
the workflow's exact file SHA and its own canonical seal, and every selected
input reference matches its declared file SHA. Contract JSON must be finite
and unique-keyed; references stay inside the checkout without symlink traversal.
The contract is rehashed at the end. This is an observation during inspection,
not an atomic snapshot, writer-exclusion proof or reusable admission receipt.

The common implementation has no scientific-library import or subprocess.
Each adapter explicitly supplies exact field selectors. The default has no
mapping and returns `BLOCKED_INPUT_CONTRACT_BINDING`. Selected declarations
are copied, not interpreted, rounded or replaced with shared defaults.

The existing corrected-O4a adapter selects eight declarations: analysis
duration, sample rate, left/right context, incomplete-context handling, frozen
mirror population scope, and scan/calibration identity digests. It hashes five
metadata inputs: raw manifest, DQ snapshot, canonical runtime contract,
reference manifest and raw-window validity audit. It never follows their raw
paths, opens HDF5 samples, reads scores or executes scientific helpers.

The O4a population explicitly remains its frozen local raw mirror, not the
whole observing run. A DQ snapshot may contain multiple run/flag inventories:
hashing that file does not select a flag or prove eligibility for any target.

## What remains open

The report always has `scientific_execution_ready:false`,
`exact_gps_coverage_checked:false`, `dq_eligibility_checked:false`,
`raw_samples_checked:false`, `runtime_equivalence_checked:false`, and
`writer_exclusion_established:false`. A PASS here is NOT full preflight PASS.
No existing productive or retained command, receipt interpretation, registry
binding, scientific policy, numerical parameter or UI activation is changed.

Subsequent08.24 adds a separate primary manifest GPS/context coverage gate:
see docs/DANTE_WORKFLOW_GPS_COVERAGE_2026-10-02.md. The flags above still describe
`input-readiness` itself; it does not absorb that new coverage proof. Calibration
coverage, raw/sample/runtime and bounded numerical execution from a clean
install remain open. A new population, DQ policy or sample validity rule
requires author review before implementation. Other-run/V1 contracts and their
scientific qualification remain separate; synthetic labels are not that
qualification. O3a diagnostic science is still closed.
