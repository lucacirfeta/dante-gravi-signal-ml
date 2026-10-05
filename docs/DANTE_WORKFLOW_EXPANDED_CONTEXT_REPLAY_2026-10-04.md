# Full expanded native context replay - 2026-10-04

Scope: the08.35 opt-in reader must actually read every admitted context, not
merely bind metadata. This is calibration-input-only, not reopening O3a.

## Frozen inheritance

-Unchanged08.35 consumer contract SHA
 `42a8927251b81134dcfda479630ad1678421166650a3205c4b8669fff919535c`.
-08.35 sealed binding fileSHA
 `6731ced30a0adf17f3054932c7be343da624539640feda3b30e3bb96f9daa9b4`.
-08.34 completed admission/plan/summary/verifier pins remain unchanged.
-Expected full domain from those parents:39971 identities19715H1+20256L1,
 39891 unique contexts39863new+28prior. No deduplication of scientific identity;
 repeated identity-to-context use is retained in the frozen binding.

## Method and limits

New separate source-frozen runner calls the unchanged consumer for every exact
context, preserving per-read receipt/source/container/native hash checks.
It emits sealed native-only context receipts, progress and a final aggregate.
Standalone verifier traverses all retained native containers with direct h5py,
not consumer.read/GWPy, and checks exact dataset grid/dtype/sample hashes against
each receipt and the admitted historical native SHA. The08.34 official-frame
reader proof is inherited, not repeated or relabelled as another source fetch.

No per-read guard caching waiver, sampled proof or automatic resume. Outputs
are isolated, never inside preserved parents or checkout. Existing output,
lock/failure/partial evidence and any provenance drift fail closed. Keep all
evidence on failure, do not reset or re-run without diagnosis.

This does not verify full padded-context DQ, whitening/Q crop, model/index,
scoring, thresholds, full fresh calibration, all-run certification or O4b.
Those are separate subsequent gates. No provider registry/default change.

## Pre-run evidence

242 targeted WSL PASS (31 new),11 upstream warnings; Ruff lint/format PASS.
Real full-domain run and independent verifier still pending at source freeze.
The initial synthetic read found retained GWPy metadata uses x0/dx rather than
the official-frame Xstart/Xspacing; corrected this new reader before real use.

## Live execution (not completion)

Source freeze1fecbd3a0f6a2f6465ddeebd77db2b18b16ad40c; new contractSHA
`1f934f040e31087b86a71306f18694bd3799d793903635fa51021030bcd0f926`.
Run `E:/dante_cache/dante_workflow/expanded_context_replay_20261004/native_v1`.
One LinuxPID544 under exec16946, hidden launcher24080. Binding digest
`84545eb094ed81ac209d5199f49905ac1056e79e9792785deb3a122b68904c0f`.
Observed64/39891 native context receipts10:06UTC, matching lock, stderr empty.
No final run/verification status or OS exit observed yet; do not invent them.

Logs are outside run under the task directory: worker.stdout.log/stderr.log;
worker.verify.stdout.log/stderr.log appear only when standalone starts.
Supervisor launches verifier once only after run OSexit0/PASS/no failure/lock,
with actual summary SHA; it prints RUN_EXIT_CODE and VERIFY_EXIT_CODE.
Monitor ACTIVE at30min, silent unless meaningful phase result/error/decision.
No fixed ETA from short startup sample; full-domain per-read guards preserved.

## Failure checkpoint - supersedes live execution status

Exec16946 completed with observed OSexit1 and RUN_EXIT_CODE=1 after1116 context
receipts. No verifier started; no summary.json/verification.json. Controller is
stopped, controller.lock absent, zero partial/tmp. Preserve native_v1 and logs.
Failure sealed digest
`0f9a4b89afb501501fbd44b9639ab5878af7cfc9f4503711e45067479e4eb570`,
InputCoverageError `consumer native/name identity mismatch`.

First rejected context H1[1369569500,1369569540) is a prior reference: actual
name H1:STRAIN versus required H1:GWOSC-16KHZ_R1_STRAIN. The08.35 reader applies
the new-recovery policy name template unconditionally to both origins. A
read-only diagnostic checked all28 prior files against their existing pins:
18H1:STRAIN+10L1:STRAIN, container/native SHA, t0/rate/sample count and finite
samples all match. This is not evidence of raw or numerical corruption, and
these diagnostic checks are not the08.36 independent full-domain verifier.

Ten source SHA still match Git1fecbd3; replay contract and08.34/08.35 evidence
pins unchanged. Synthetic prior fixture names used the new template and missed
the real mixed-origin mismatch; pre-run tests therefore do not close this gate.

Monitor PAUSED pending author decision. Recommended repair: explicit per-origin
name binding, prior names from sealed historical containers and the inherited
template for new containers, preserving numerical and provenance guards. Do not
accept arbitrary names, remove the guard or rewrite prior containers. Approval
requires mixed-origin synthetic tests, new source freeze and a fresh isolated
run; the failed native_v1 is not resumed or reinterpreted. No code/config/input
changes made here.08.36 remains incomplete and downstream gates are blocked;
O3a remains closed/O4b not started, no push or repeated shutdown.

## Author-approved v2 technical repair

Author `quindi procedi` approves per-origin names, repairing an over-strict
metadata guard, not a scientific criterion. Ordinary technical bugs can be
fixed and regression-tested without repeated scientific approval; preserve
failure evidence and stop on actual critical scientific/structural changes.

V2 retains08.34 pins/geometry. Prior exact name from SHA-pinned historical
HDF5 is sealed in binding/receipt; new name uses unchanged recovery template.
Independent h5py checks names and native grid/dtype/hashes. No alias, rename,
arbitrary-name fallback or guard removal. V1 contracts/binding/failure remain
reproducible at their old freeze. Fresh native_v2 reuses no1116 v1 receipts.
Pre-run250 WSL PASS/15new/11 upstream warnings,15.82s; Ruff4files PASS.
Synthetic PASS is not full real-domain PASS. Freeze before binding/execution.
Provider contractSHA d256bd969fe910605ba7ad8b37123a43a1eca4b456101552e0ac80d777d4da58;
replay contractSHA 7cc3280238c4cf724d4a480e3ccb0216a978a9817fa948c5e0712d53dd5b5e3d.

## V2 live checkpoint (not full completion)

Freeze `76c42f064ba99c3ad0ffe3c8588c8e6560eb5d10`. Real binding preflight96231
and standalone binding verification under26831 each observed OSexit0, same
PASS_EXPANDED_CONTEXT_CONSUMER_BINDING_ONLY. New external
`E:/dante_cache/dante_workflow/expanded_context_provider_20261004/preflight_v2.json`,
SHA `83da191a5107029a0bd6934f70a1eebfb6694317b81806ad21dda16caf28dfae`,
seal `d43f6af6c1cff6cbc84dafac16e4888ab6047a75b9f79f82cad9b159e3ffc7f8`.
All39971 identities/39891 unique contexts metadata bound;28 prior names remain
18H1:STRAIN+10L1:STRAIN. Ten source SHA matchGit freeze; all08.34 pins and v1
contracts/failure untouched. This is binding evidence, not full native PASS.

Supervisor exec26831 started one LinuxPID498 full run in fresh
`E:/dante_cache/dante_workflow/expanded_context_replay_20261004/native_v2`.
Startup repeats parent binding before lock/receipt creation. Task-directory
logs `worker.v2.stdout.log`/`worker.v2.stderr.log`; standalone binding logs
`worker.v2.binding_verify.*`; future native verifier logs `worker.v2.verify.*`.
Durable `worker.v2.supervisor.stdout.log` retains observed OSexit messages.
Native verifier starts once only after run0/PASS/no failure/lock/verification;
both full-stage exits still pending. Monitor ACTIVE/30min; general readiness
continuation remains authorized, no fixed ETA from startup. Next after verified
native PASS: inherited full padded-context validity/preprocessing, not O4b.

## Run completion, user interruption and restart (2026-10-05)

The native_v2 full consumer run subsequently completed all39891contexts with
PASS_COMPLETE_EXPANDED_NATIVE_CONSUMER_ONLY and observed RUN_EXIT_CODE=0.
Summary seal5f8d44228d1b4ddf5e60cb9c8bb2bc0337005c397fefbae8adea23aaf269742b,
fileSHA108823e4cffd9c5622827bdbd5f80e7b8e0cfbc0ccab56fd3f07ffc5c7c914f5.

The author needed shutdown and confirmed controlled interruption on4October.
SIGINT was sent to the exact identified standalone verifierPID4076. It exited
with observed VERIFY_EXIT_CODE=2; retained stderr ends KeyboardInterrupt while
resolving an input path. Sealed progress16563/39891 has digest
ddba303e14c02c7d99b9df8e53d8cf7f93c813b1e1c83014edd7d2b389d118fc.
No controller.lock, failure.json or verification.json remained. All completed
run receipts and original logs are retained. This is a deliberate interruption,
not evidence of a numerical failure and not PASS_VERIFIED. Monitor was paused.

On5October author `riprendi` authorizes a safe restart. Before launch: no active
controller, existing quiet guards, source/contract/binding/parent/summary pin
checks and a read-only all-receipt seal/identity-union/aggregate audit. Preserve
first-attempt progress/logs outside native_v2 before retry rewrites its progress.
The unchanged standalone verifier then reads every context from the beginning
with distinct logs and durable OS exit capture. No automatic context-level
resume, repeated raw acquisition/full run, lock/failure deletion, source/config
change, new scientific decision or downstream execution. Full verifier PASS
remains pending; local replay is not a second GWOSC fetch.

Restart audit22637 completed with observed OSexit0: all39891 receipt seals,
unique context union and aggregate match the frozen summary/binding; all39971
identities,19715H1+20256L1. Ten sourceGit/contract/binding/summary pins and four
08.34 parent evidence file hashes match. No controller/lock/failure/partial/tmp
or completed verification before launch. This is not independent numeric PASS.

Original progress and three first-attempt logs were copied byte-identically to
E:/dante_cache/dante_workflow/expanded_context_replay_20261004/verification_attempts/attempt1_user_interrupt_20261004;
originals remain in place. Archived progress fileSHA
34c1c84de5fc9bab8d9d44723015fa4655916091450f44abaa7f2d12805fd19a.
Exactly one unchanged standalone verifier restarted under exec31599,
Windowslauncher9732/LinuxPID427 at launch. Separate logs are
worker.v2.verify_retry1.stdout.log, worker.v2.verify_retry1.stderr.log and
worker.v2.verify_retry1.supervisor.stdout.log; the latter captures actual OSexit.
Startup stderr empty; full retry exit/PASS still pending. Monitor ACTIVE/30min
confirmed. No full consumer/raw run repeated, new shutdown or O4b launch.
