# Isolated SCAN database byte input — 2026-10-02

Author `procedi` approves the recommended isolated byte-identical copy following
08.17's strict historical SQLite sidecar refusal. Source freeze **456a1ba** on
`science/o3-transfer-readiness`; local commits only, no push/main.

## Observed result

One real capture via `scripts/copy_dante_o3a_scan_evidence.py --stage capture` in
canonical WSL Python completed with observed OS exit **0** (session38694).
One standalone `--stage verify`, explicitly supplied the capture's receipt SHA,
completed with observed OS exit **0** (session57580):
`PASS_VERIFIED_ISOLATED_SCAN_DATABASE_BYTES_ONLY_V1`.

New isolated directory:
`E:\dante_cache\dante_light\retained_scan_copy_20261002_v1`.
Its complete closure is `scan.sqlite`, `origin_wal.bin`, `origin_shm.bin` and
`receipt.json`. WAL/SHM copies are inert provenance, not active SQLite sidecars.

- Database size: **213794816 bytes**.
- Database SHA256: `1f222dfbc4066abf8fe2b2f3a09edb4a7ccbc83f79aac94ba9a54aa6b0844699`.
- Receipt SHA256: `17558e62547be42bbd2e5310d6fa8f93e06c8e0c3a7ae352115cce33ef252508`.
- Receipt seal: `78fdb9b109495a72c225ca568d197bfb1f7e436866d495d1fa98adcb77c31bc1`.
- **17** bound transport policy/source files.

SCAN identity was derived using original frozen contracts, not a chat run key.
Original source directory:
`E:\dante_cache\dante_light\o3a_native_v1\primary_scan_8f0424e5f3ea2b94449eaddb0e1ccf61c5fd7ba91d54c839bfa89d0e26efad35`.
The sealed original summary provides the expected database SHA and size.
Capture and verifier compare source bytes/metadata before and after their work
while holding the original existing O_RDONLY nonblocking exclusive flock.
Original WAL is **0 bytes**, original SHM **32768 bytes**, rollback journal absent;
all are explicitly bound, including absence. No historical SQLite connection,
checkpoint, deletion, overwrite, producer, sensor fetch or scoring invocation.

## Implementation and acceptance boundary

Separate module `src/dante_workflow/o3a_scan_copy.py`, CLI and frozen policy
`config/dante_workflow_o3a_scan_copy_v1.json`. Technical maximum database bytes
536870912, metadata bytes8388608; these are resource limits, not scientific
parameters. POSIX descriptor-relative nofollow reads/publication reject unsafe
links and hardlinks. New output must be outside historical/repository inputs;
no overwrite/resume. Receipt published last, after input and output checks and
successful cooperative lock release; incomplete new output remains unsealed.
Standalone verification requires an externally supplied receipt SHA, exact
source/policy/origin identity, file hash/size and complete closure. Source closure
is transport-specific and does not bind unrelated downstream reader edits.

The generic historical `_no_journals` and `immutable_database` are unchanged.
Nonempty WAL, any rollback journal, unsupported SHM, failure/partial markers,
busy locks, altered summaries or changed files continue to fail closed.
No new productive exception to transaction handling was introduced.

This is **byte transport only**: neither scientific parent closure nor runtime
equivalence, global writer quiescence, transaction replay, numerical PEM replay
or full-workflow certification is established. Local replay is not a second
source fetch. The earlier driver-only retained waiver remains separate.

## Verification evidence

- New transport suite: **34 PASS** on WSL after source freeze, OS exit0,2.86s.
- Final scoped WSL regression (transport, locks, snapshot, retained runtime,
  native/index readers, original native contract): **320 PASS,1 skip**, OS exit0,
  63.91s. Earlier run on the final design had the same count,67.64s; transport
  source closure was subsequently narrowed to its actually executed dependencies
  and the final full scoped suite rerun before freeze.
- Windows platform-aware suite (transport, locks, snapshot, retained runtime,
  original native contract): **98 PASS,47 skips**, OS exit0,2.99s. POSIX capture
  cases intentionally skip; CLI operation wiring and policy checks are portable.
- Ruff lint/format PASS; scoped staged diff check PASS.
- All **6** source-commit files byte-identical to Git before/after actual capture.
- No original scientific source/contract edits. Existing upstream exact
  LF-to-CRLF provenance qualifications remain unchanged; no normalization.
- User untracked `artifacts/dante_workflow/public_smoke_v1/` and `output/` preserved.

Tests include exact source preservation, immutable SQL on synthetic isolated
bytes, strict original sidecar refusal, WAL/journal/SHM eligibility, externally
pinned receipt, resealed false boundaries, source/sidecar drift, extra/partial
output, hardlinks/symlinks, busy locks, failure markers, overlap/overwrite and
CLI capture/verify wiring. Initial four failures were fixture expectations of
raw OSError versus the existing lock context's wrapped InitialEvidenceError;
only expectations were corrected, with no guard bypass.

## Next increment

Wire an explicit receipt-pinned isolated database input into retained coincidence
and PEM snapshot readers. Keep their default historical database/sidecar refusal
strict; ensure SCAN and COHORT both use the admitted byte-identical input, retain
original sidecar/lock qualification and propagate it into receipts. Test opt-in,
identity mismatch and full parent wiring before one real retained parent retry.
No full-chain PASS or dispatcher/all-run/Virgo readiness claim is available yet.
