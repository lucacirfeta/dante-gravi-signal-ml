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
