# Native upstream read-only persistent locks — 2026-10-02

## Approved scope

Author `preocedi` approves extension of the already-tested retained-only flock
protocol to original SCAN, COHORT, INDEX and RESCORE producers. Each opens a
persistent `run.lock`, obtains a nonblocking exclusive flock, and unlocks without
unlinking it. SCAN/COHORT write their PID only after acquisition; INDEX/RESCORE
need not write a PID. Presence is not evidence of a current
writer; successful lock acquisition is required, not a stale PID inference.

Shared `src/dante_workflow/o3a_locking.py` contains the unchanged O_RDONLY protocol
previously held in decision verification. Original scientific producers,
contracts, populations, score interpretation and statistical checks are untouched.
One explicit ExitStack is propagated through the full retained parent chain.
Locks remain held through final input hashes, SQLite sidecars, failure/partial
guards, source hashes and receipt construction; exit checks inode identity and
metadata before unlock. No lock is created, overwritten, deleted or repaired.

Held native locks are recorded as SHA256-bound input bytes. A directory can use
the presence exception only while its exact lock belongs to the current stack;
the registration is removed on exit. Duplicate acquisition refuses. Missing,
busy, symlinked, hardlinked or replaced lock files refuse. Partial/failure markers
remain failures even while a cooperative lock is held.

Native calibration has no matching producer protocol and retains the original
strict guard. Initial calibration/threshold checks are unchanged. An unlocked
directory, another run, or a directory after stack exit never inherits the
exception. This is cooperative writer exclusion for these producers only, not
global quiescence, atomic snapshot capture or fresh numerical validation.

## Evidence and verification

Twenty new upstream wiring tests cover final-check lifetime, release, contention,
missing/unsafe/replaced files and strict non-cooperative calibration. Eight shared
helper tests cover stack ownership, duplicate acquisition, late guards and scope.
Existing adversarial decision-lock tests now exercise the same extracted helper.
Windows tests that require POSIX flock explicitly skip; they are not a Windows
validation of this protocol. Executed source closure includes the helper:
17 native, 21 index, 26 score, 31 decision, 35 taxonomy, 40 coincidence, 47 PEM.

Original `contracts.py`, `coincidence_physical.py`, `pem_coherence_analysis.py`
remain exact Git LF-to-CRLF reconstructions, not byte-identical Git files. Their
existing qualifications are preserved, never normalized. Scientific source diff
is empty. Regression/source-freeze and actual parent retry results are recorded
below after observation; no real-chain success is inferred from synthetic tests.

## Decision after actual parent refusal

The existing retained coincidence CLI was retried once after green regressions
and local source freeze, with nine explicit roots and the approved driver-only
waiver. Its independent SQLite sidecar refusal is preserved. No historical
repair, key substitution or marker deletion. Before another retry, author approval
is required for a separately specified isolated, byte-bound database evidence
copy (including explicit sidecar provenance), or a demonstrably canonical clean
historical export. Neither option is implemented. A positive parent proof would
still require a reviewed real capture plan and bounded snapshot replay. No
productive run, measure, fetch, publication, push or readiness certificate implied.

## Observed regression and source freeze

- Local source freeze `cdca4375f732a4a6c70522221e92d7f3cd4e9958`; 18 files
  audited byte-identical to Git before the actual retry, OS exit 0 for that audit.
- WSL upstream/decision/taxonomy/coincidence/snapshot PEM readers: 561 PASS,
  5 skips, 11 upstream warnings, OS exit 0, 336.46s. Shared helper: 8 PASS,
  OS exit 0, 1.05s.
- WSL full workflow + original native contract/native PEM/PatchProducer:
  1020 PASS, 7 skips, 11 upstream warnings, OS exit 0, 457.84s.
- Windows workflow + original native contract: 544 PASS, 454 platform skips,
  OS exit 0, 171.08s. The subsequently added shared helper was checked separately:
  1 PASS, 7 POSIX skips, OS exit 0, 0.10s. Not Windows historical flock proof.
- Post-freeze helper + original native contract: WSL 18 PASS, OS exit 0, 3.84s;
  Windows 11 PASS/7 POSIX skips, OS exit 0, 2.08s.
- Ruff lint and format: PASS, 18 files formatted; scoped diff check PASS.

Development initially exposed four stale synthetic source-count assertions and
a rebuilt synthetic INDEX fixture missing its producer lock. Expected source
cardinality was updated for the actually executed new helper; the temporary
fixture now carries its required marker. No digest comparison was bypassed and
no historical marker was added or repaired.

Actual retry session 93544 returned observed CLI/supervisor OS exit 1,
`FAIL_CLOSED_O3A_COINCIDENCE_EVIDENCE`, `InitialEvidenceError`:
`SQLite transaction sidecar present; no repair attempted`. Stderr empty. All
12 observed persistent markers retained identical SHA/size/inode/mtime/ctime/
link-count metadata before/after. Captured CLI stdout SHA256:
`108cc6d66dfb9e137b40ea81f6c7976333129e5fd579d7e9d67e020aec204aef`.

Read-only diagnosis, session 9582 OS exit 0, derives the SCAN path from the frozen
contract/runtime, not chat:
`E:/dante_cache/dante_light/o3a_native_v1/primary_scan_8f0424e5f3ea2b94449eaddb0e1ccf61c5fd7ba91d54c839bfa89d0e26efad35`.
Summary seal valid; database SHA equals its historical expected SHA:
`1f222dfbc4066abf8fe2b2f3a09edb4a7ccbc83f79aac94ba9a54aa6b0844699`.
Regular `primary_scan.sqlite-wal` is 0 bytes (empty SHA256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`);
regular `primary_scan.sqlite-shm` is 32768 bytes, SHA256
`fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb`.
No matching Linux scientific run/verify Python process at observation; `fuser`
reported no current owner, exit 1 with empty stdout/stderr. This is a momentary
diagnostic, not proof of global quiescence or permission to discard sidecars.

No SQLite connection, checkpoint, deletion, historical mutation or second actual
retry was attempted. The unchanged immutable-reader policy refuses even an empty
WAL alongside SHM; successful file hash alone does not silently waive that gate.
Scoped lock implementation PASS; real parent chain remains blocked and snapshot
capture, all-run/Virgo scientific readiness remain open.
