# Explicit isolated SCAN input admission — 2026-10-02

Author `procedi` approves phase08.19 after the verified byte-only input gate08.18.
Source freeze **79f3d80** on `science/o3-transfer-readiness`; local commits only.
This increment changes retained evidence readers, not scientific producers,
populations, thresholds, scoring, null construction or statistical parameters.

## Implementation

New `src/dante_workflow/o3a_scan_copy_admission.py` admits a copy only with both
an explicit directory and an externally supplied receipt SHA256. Retained
coincidence and snapshot-PEM APIs/CLIs expose the paired opt-in; omission preserves
the previous strict historical SQLite sidecar refusal. The author-approved
driver-only retained qualification is a separate opt-in, not implied by the copy.

Under the already-held original SCAN flock, admission reconstructs the exact
sealed summary, origin/contract identity, transport policy and17 frozen transport
source bindings, original DB/sidecar/lock pins and isolated file closure. It does
not reacquire the same flock or connect SQLite to the historical database.
Original and isolated bytes/metadata, receipt, source bindings and held-lock
registration are checked again through final parent verification.

Both SCAN and COHORT SQL use the admitted physical `scan.sqlite`; later readers
consume that same tracked `scan_database`. The historical container name remains
the sealed summary's `primary_scan.sqlite`, explicitly distinguished from the
physical copy name. This preserves full-summary identity without weakening SHA,
size, row or population checks. The receipt adds a separate
`isolated_scan_input_qualification` alongside any retained-runtime qualification.

Admitted existing input, not recaptured here:
`E:\dante_cache\dante_light\retained_scan_copy_20261002_v1`.

- Receipt SHA256: `17558e62547be42bbd2e5310d6fa8f93e06c8e0c3a7ae352115cce33ef252508`.
- Receipt seal: `78fdb9b109495a72c225ca568d197bfb1f7e436866d495d1fa98adcb77c31bc1`.
- Database SHA256: `1f222dfbc4066abf8fe2b2f3a09edb4a7ccbc83f79aac94ba9a54aa6b0844699`.
- Database size:213794816 bytes. Original WAL0/SHM32768 bytes remain preserved;
  copied WAL/SHM are inert provenance, never active SQL transaction sidecars.

Original `_no_journals` and `immutable_database` are unchanged. No original SQL
connection, checkpoint, deletion, producer invocation, source fetch, new encoder,
raw scoring/correlation, fresh null or sensor replay is authorized by this input.

## Empirical verification

- New admission tests:25 PASS on WSL, observed OS exit0,4.85s.
- Admission/transport/original native-contract tests:69 PASS before freeze,
  OS exit0,5.60s; post-freeze69 PASS, OS exit0,6.75s.
- Final broad WSL workflow/original native-contract/native-PEM/PatchProducer:
  **1079 PASS,7 skips,11 upstream warnings**, OS exit0,548.44s.
- Final platform-aware Windows workflow/original native-contract:
  **558 PASS,507 platform skips**, OS exit0,143.35s. POSIX-only behavior is not
  claimed validated on Windows. Earlier scoped Windows53 PASS/46 skips, exit0.
- Ruff lint and format PASS for16 Python files; source/staged diff checks PASS.
- All18 source-commit files byte-identical to Git79f3d80 after freeze. Six
  transport dependencies remain byte-identical to456a1ba; the existing receipt's
 17-source closure is unchanged. Native22/coincidence45/PEM51 reader bindings
  reflect the actual executed source union, not a scientific parameter change.
- Scientific-source/config diff empty; inherited exact LF-to-CRLF qualifications
  remain, including contracts.py, coincidence_physical.py and
  pem_coherence_analysis.py. No normalization or hash bypass.

Tests exercise strict defaults, paired argument refusal, external receipt pin,
summary substitution, origin/copy/receipt/sidecar drift, lock lifetime and actual
synthetic SCAN/COHORT gates. A spy confirms every SQL connection is to the copy;
both full historical summary reconstructions match. Driver qualification remains
separate and its final runtime-stability guard composes with copy pin checks.
Both CLI option wiring and public API propagation are tested.

Development corrections were synthetic fixture import/error handling and a stale
PEM binding-count expectation:51, not52, because evidence_snapshot was already
bound. The physical/logical database-name distinction was explicitly implemented
and tested. No historical artifact or scientific validator was repaired.

## Acceptance boundary and next step

This implementation does not establish full-workflow certification, global
upstream writer quiescence, fresh scientific replay, dispatcher adoption or
all-run/Virgo readiness. Local evidence replay is not a second source fetch.
User untracked `artifacts/dante_workflow/public_smoke_v1/` and `output/` are
preserved. No push/main/merge/release or public communication.

## Actual retained-chain retry: stopped, not PASS

Exactly one real retained coincidence invocation ran after79f3d80 in canonical
WSL Python, with all nine external roots explicitly supplied as
`/mnt/e/dante_cache/dante_light/o3a_native_v1`, the admitted copy directory and
receipt SHA above, and the separately approved `--allow-retained-driver-drift`.
Supervisor session80477 returned observed OS exit **1**:
`FAIL_CLOSED_O3A_COINCIDENCE_EVIDENCE`, ContractError,
`STOP_ENVIRONMENT_MISMATCH: O3a scoring requires the frozen WSL runtime`.
Stderr was empty; all12 observed persistent marker hashes and metadata were
unchanged. CLI stdout SHA256:
`3053dc9a4cb911dfdcb80515bbdb8394b0d496d3aa659c3b0bbdb8ec286c5f7b`.
The sanitized technical supervisor result is preserved in
`docs/evidence/DANTE_WORKFLOW_SCAN_COPY_ADMISSION_RETRY_2026-10-02.json`.
No successful retained-chain receipt or scientific outcome was produced/reported.

Read-only source diagnosis identifies an unqualified nested runtime check:
`o3a_score_verification._calibration_gate` first calls the retained-qualified
runtime loader, then calls original
`o3a_native_calibration_cohort._run_dir`. That helper independently calls
`load_runtime_contract(require_current=True)` while deriving the historical key,
so the strict original guard rejects the changed driver. It remains unchanged.
This is a remaining reader-wiring gap, not evidence of a new statistical mismatch
or permission to relax the productive runtime contract.

A separate runtime-only diagnosis exited0 and reconstructed the already-approved
driver qualification: frozen616.92, observed617.14; every other runtime field
matches exactly. Frozen environment digest
`582a9b99f689d36f126b75f95dd31763c2b399aab03180f06c9838eb1f8f1b58`, observed
`ebeae01fdbad49d252555e354daba1e69282ddfcdd89ee386ceeb3c184fb474f`.
This probe did not retry the chain, read scientific outcomes, prove numerical
driver equivalence or authorize fresh work.

STOP at the new structural/provenance checkpoint. Recommended next increment,
subject to author confirmation: make the retained reader's calibration-directory
resolution consume the already-validated frozen runtime identity explicitly,
with parity and strict-default tests. Leave the original productive resolver
and driver policy unchanged. Freeze before a separately authorized retry.
Real PEM snapshot capture and complete-chain replay remain unopened.
