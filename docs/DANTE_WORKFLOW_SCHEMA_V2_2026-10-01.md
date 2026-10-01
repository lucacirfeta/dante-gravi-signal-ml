# Workflow schema v2: sealed per-profile graphs

Author: Luca Cirfeta. Checkpoint: 2026-10-01. Author decision: **A**.
Local feature freeze: `b9cbbc1`. No push or release.

## Delivered boundary

The shared workflow loader now supports a separately versioned v2 contract.
Each workflow references an explicit profile graph rather than weakening
the frozen v1 contract's exact fifteen-stage requirement. This is software
plumbing, not approval of new scientific methods or completion of the O3a
adapter. The existing O3a diagnostic study remains closed and unchanged.

| Layer | Identity and validation |
| --- | --- |
| Workflow v2 | Existing workflow fields plus required `graph_profile`; canonical `contract_digest` over every field except that digest |
| Profile reference | Exactly `path` and `sha256`; checkout-relative POSIX path under `config/`, exact file SHA-256; symlink escape rejected |
| Profile graph v1 | Exactly `schema_version`, `profile_id`, `observing_run`, `detectors`, `adapter`, `stages`, `contract_digest`; independently sealed canonical body |
| Stages | Entire workflow stage array must equal the sealed profile array, including dependencies, verifier commands, configuration references, inputs/outputs, visibility and resumability |
| Executability | Separate exact adapter factory; parsing a graph does not register an adapter or create scientific execution permission |

Profile `schema_version` is integer 1; workflow `schema_version` is integer 2.
Versions are distinct because these are different documents. Canonical digests
use the existing `canonical_json_sha256` function, with finite JSON and the
document's own `contract_digest` field removed. Profile raw-file SHA is an
additional check, not a substitute for the canonical seal. Duplicate JSON
fields are rejected in both v2 documents. The profile is parsed from the same
bytes whose file SHA was checked.

Existing pinned scientific configuration validation and all enabled product
policies remain required. Generic graph checks reject cycles, duplicate stages
or producers, unknown/self parents, missing upstream inputs and invalid artifact
gates. Where `NATIVE_CALIBRATION` is present, verified COHORT and content-digested
INDEX `index_window_manifest` remain mandatory. Where RESCORE is present, verified
INDEX and NATIVE_CALIBRATION remain mandatory. V1 still requires all fifteen
stages, so those historical checks are not weakened.

An O4a adapter cannot execute a profile naming another run/detector scope or
a shortened executable graph. Equivalent O4a commands are preserved in synthetic
v2 tests, but v2 has a **new identity/run key**: it must not silently reuse a
v1 run. No production v2 profile or registry binding was created here.

## Evidence and qualifications

| Check | Observed result |
| --- | --- |
| Complete Windows controller regression | 224 PASS, OS exit 0, 35.37s |
| Complete WSL controller regression | 223 PASS, one Windows-only no-signal skip, OS exit 0, 115.79s |
| Post-freeze schema-v2/v1/profile tests | 112 PASS, OS exit 0, 3.90s; includes 56 new v2 cases |
| Ruff lint for modified/new code | PASS in existing WSL environment |
| Ruff format for new module/tests | PASS |
| Frozen scientific config/scripts/source/data diff | Empty |

Negative tests include re-signed workflow/profile mutations, malformed versions
and scope, exact-file versus canonical-seal disagreement, duplicate JSON keys,
path/symlink escape, malformed graph/policy fields, parent/hash-gate removal,
and rejection of unsupported adapters before state creation. Tests use synthetic
temporary profiles, not numerical strain analyses or production runners.

The frozen `config/dante_workflow_productization_v1.json` has checkout SHA-256
`7148db11ea455ff97319ac763ca420874711d3e5dcaea6f7968f85df01a75e06`.
Its Git blob SHA-256 is
`9ad4286b08a611c18cc73a4493fa47ac57e052d1a4048c0be0b456b4b36c0c70`.
The checkout is an exact LF-to-CRLF reconstruction of that blob, not raw-byte
identical to it. This inherited qualification is preserved; no scientific file
normalization or Git-setting change was made. Native Python lacks Ruff; existing
WSL Ruff was used without installing dependencies. Earlier detached-UI timing
qualification from 08-01 is not claimed repaired by these passing suites.

## Next bounded increment

Map existing O3a versioned contracts and real receipt/verifier interfaces to
the applicable production graph and implement its adapter. Keep full execution
distinct from independently verified adoption of historical artifacts. Do not
make comparative PEM or the post-hoc two-target study universal mandatory stages
merely because they occurred in this study; do not represent unsupported stages
as successful placeholders.

O3a numerical adapter, production profile binding, multi-run GUI selection,
exact-interval/DQ/context preflight and clean-install bounded numerical replay
remain open. Other runs and V1 still need approved scientific contracts. Public
availability or schema acceptance does not authorize transplanting H1/L1
thresholds/nulls to Virgo, changing populations, or asserting network significance.
Any new scientific or applicability decision remains an author checkpoint.
