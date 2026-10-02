# Retained calibration directory runtime wiring — 2026-10-02

Author `procedi` confirms08.20 after08.19 stopped at the original nested runtime
check. Source freeze **f4f86bc**, branch `science/o3-transfer-readiness`, local
commits only. This is retained evidence reconstruction, not new scientific work.

## Narrow correction and unchanged defaults

Only `src/dante_workflow/o3a_score_verification.py` production-facing reader code
changes. Its calibration gate passes the already-loaded runtime into a retained
directory resolver. With explicit driver opt-in, the resolver requires completed
retained qualification, a valid frozen environment seal, equality to the qualified
frozen digest and equality to the calibration contract's runtime parent digest.
It then derives the exact historical stage/contract/frozen-runtime run key using
the original `o3a_native_calibration_cohort._run_dir` formula.

Without retained runtime opt-in, resolution still delegates to that original
resolver and its exact-current-runtime guard. Copy-only admission does not imply
driver permission. The productive resolver, all scientific contracts/configs,
driver policy and previously frozen isolated copy/receipt are unchanged. No
productive monkeypatch, arbitrary runtime waiver, current-runtime refreeze or
changed historical run identity. Final observed runtime stability remains checked.

## Verification before the real retry

- Seven added tests: strict default calls original resolver; golden original-key
  parity and input preservation; three substituted seal/environment/parent cases;
  absent qualification refusal; linked synthetic calibration gate passes while
  the original strict resolver rejects the changed driver. The integration test
  reconstructs rows and summary and preserves temporary input bytes/metadata.
- WSL scoped runtime/copy/score/decision/taxonomy/coincidence/snapshot-PEM plus
  original native-contract/native-PEM/PatchProducer: **478 PASS,5 skips,11 upstream
  warnings**, observed OS exit0,343.96s. No full-repository certificate claimed.
- Final portable-fixture WSL runtime/original native-contract:46 PASS, exit0,3.80s.
- Final Windows platform-aware retained reader/native-contract suite:
  **167 PASS,295 skips**, exit0,82.90s. No Windows POSIX lock certification.
- Post-freeze final WSL runtime/score suite: **119 PASS**, exit0,53.47s.
- Ruff lint/format three Python files PASS; source/staged diff checks PASS.
- Four source-commit files byte-exact Gitf4f86bc. Six original transport dependencies
  remain exact456a1ba, preserving17-source receipt closure. Original scientific
  sources/configs and inherited exact LF-to-CRLF qualifications remain unchanged.

Development deviation: four new portable unit tests initially invoked the WSL
contract rebuilder on Windows. Read-only diagnosis found only
`execution.root_wsl` slash-to-backslash conversion and its derived contract digest.
No scientific field/source hash differed. Portable key tests now read the versioned
contract and independently validate its seal before testing the original formula;
they do not claim Windows productive contract rebuild equivalence. The original
WSL validation and strict productive guard remain unchanged. WSL targeted tests and
Windows scoped tests reran successfully; the final post-freeze119 suite includes
the final portable fixtures and the linked calibration gate.

## Acceptance boundary

The new resolver does not authorize fresh scoring, raw correlation, sensor/null
replay, source fetch, writer repair, historical artifact modification, dispatcher
adoption, global upstream quiescence or full-workflow/all-run/Virgo certification.
No snapshot capture or PEM outcome read is part of this increment. Existing user
untracked `artifacts/dante_workflow/public_smoke_v1/` and `output/` are preserved.
No push/main/merge/release/public communication.

The real retained coincidence retry is a separate acceptance check after freeze,
with all nine external roots explicit, the already-verified isolated DB receipt
externally pinned and the separate retained driver flag. One invocation only;
new mismatch requires stop, preserved evidence and author review, not an automatic
retry or expanded waiver. A successful result remains retained-ledger-only, not
a raw scientific replay or complete pipeline certificate.

## Real retained coincidence acceptance: PASS

Exactly one invocation afterf4f86bc, supervisor session62224, returned observed
CLI and supervisor OS exit **0**:
`PASS_O3A_READ_ONLY_COINCIDENCE_RETAINED_LEDGER_REPLAY_ONLY`.
The supervisor independently recomputed the full canonical receipt seal in memory,
checked the selected SQL path, admitted copy receipt/DB pins and false full-workflow
boundaries before printing only technical qualifications. No outcomes were printed.

- Reader receipt seal: `1d74f9574a197efcc87c6ea85b877a735fbdc53600e84eaa9158a5470a8c00f9`.
- CLI stdout SHA256: `6a6029041b89c9006254d4116f3148b7dfc1dc593f85bdc85f170a360a50b218`.
- Reader source bindings:45, unchanged closure cardinality; executed helper bytes
  and frozen parents checked by the reader through final validation.
- All12 observed marker hashes and dev/inode/size/mtime/ctime unchanged; stderr empty.
- SQL input: `/mnt/e/dante_cache/dante_light/retained_scan_copy_20261002_v1/scan.sqlite`,
  SHA256 `1f222dfbc4066abf8fe2b2f3a09edb4a7ccbc83f79aac94ba9a54aa6b0844699`,
  213794816 bytes, historical filename `primary_scan.sqlite`.
- Copy receipt SHA256: `17558e62547be42bbd2e5310d6fa8f93e06c8e0c3a7ae352115cce33ef252508`;
  transport seal `78fdb9b109495a72c225ca568d197bfb1f7e436866d495d1fa98adcb77c31bc1`.
  Original empty WAL/32768-byte SHM remain bound and unchanged; journal absent.
- Runtime qualification separately records frozen616.92/observed617.14, every
  non-driver field exact, stable observed fingerprint, unchanged policy SHA256
  `a1a8b5ea12ba3cba6a9d5b7ccd8577db79adb995f27fc9eb8c89dde7f28b504e`.

The sanitized supervisor record is retained as
`docs/evidence/DANTE_WORKFLOW_RETAINED_CALIBRATION_RETRY_2026-10-02.json`.
It records the observed full receipt's seal/hash, not the full parent-input closure;
it must not be treated as a new standalone sealed reader receipt.

The reader reconstructed threshold block-bootstrap, classifications, taxonomy and
retained null ledgers. It did not execute encoder/preprocessing/raw scoring/raw
correlation/source fetch. Historical evidence mutation, global upstream quiescence
and full-workflow verification flags remain false. Earlier failed invocations and
checkpoints are preserved, not rewritten as successes.

## Next increment

Prepare the exact real historical PEM snapshot capture plan, owned-byte capture
and bounded retained snapshot replay using the now-verified parent path. Keep its
capture guarantees separate from non-cooperative historical writer exclusion and
from fresh raw sensor/null replay. No real snapshot has been captured here. Later
profile/preflight, clean-install and all-run/detector scientific gates remain open.
