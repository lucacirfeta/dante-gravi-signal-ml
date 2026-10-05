# 08.36 - v2 run PASS, audited verification restart active

Latest status2026-10-05: native_v2 full run PASS/39891receipt/observed OSexit0.
First verifier deliberately interrupted by author for shutdown after16563contexts,
SIGINT/KeyboardInterrupt/observed OSexit2; no failure/lock/completed verification.
Author `riprendi` permits audited full verification restart, not a resume from
16563 or repetition of the completed run. Receipt/summary/source/parent audit
and preservation of first-attempt progress/logs precede launch. Full independent
PASS remains unobserved. Historical v1 failure below is preserved unchanged.

Restart audit22637 OSexit0:39891 sealed receipts/union/aggregate and source10,
contract/binding/summary/parent pins match. Original progress/logs copied
byte-identically to external verification_attempts/attempt1_user_interrupt_20261004.
One standalone verifier active exec31599/launcher9732/LinuxPID427 at launch;
distinct worker.v2.verify_retry1 logs, monitor ACTIVE/30min. No verifier exit or
full PASS yet; no historical run/source changed, no downstream or O4b started.

Source freeze1fecbd3a0f6a2f6465ddeebd77db2b18b16ad40c.
Run E:/dante_cache/dante_workflow/expanded_context_replay_20261004/native_v1.
Observed run OSexit1,1116/39891 context receipts; no summary or verification.
Standalone verifier never started. Failure/logs/receipts preserved, no lock or
partial/tmp; parent08.34 admission and08.35 metadata binding remain unchanged.

Root cause:08.35 reader requires the new recovery-name template on both origins.
First prior context H1[1369569500,1369569540) retains H1:STRAIN, not the template
H1:GWOSC-16KHZ_R1_STRAIN. All28 prior contexts have preserved18H1:STRAIN and
10L1:STRAIN names; diagnostic container/native SHA/grid/finite audit passes.
Ten replay sources match Git freeze; evidence/contract pins match. No numerical
corruption established; this is a metadata validation-rule incompatibility.

Pre-run242 WSL PASS (31new)/11 upstream warnings, Ruff PASS did not cover real
mixed-origin names. No code/config changes or post-failure regressions claimed.
Monitor PAUSED; no automatic resume/restart or historical rename. Recommended
author choice: bind historical names to pinned prior containers separately from
the new template, retain all identity/numeric/provenance guards, then new tests,
freeze and isolated fresh replay. Failure remains immutable.

08.36 full native reader gap is NOT closed. Subsequent padded-context validity,
preprocessing, integration, fresh calibration and pre-O4b qualifications await
this decision. O3a closed; no productive promotion, push, O4b or shutdown.

## V2 correction authorized and tested

Subsequent author `quindi procedi` approves per-origin name repair.
250 WSL PASS/15new/11warnings, Ruff PASS; source freeze and fresh native_v2
required before real closure. V1 failure remains immutable, never resumed.

Source freeze76c42f0. Real v2 metadata binding and standalone replay OSexit0;
new preflight_v2.json sealed d43f6af6.../SHA83da191a..., full39971identities.
Fresh native_v2 replay active LinuxPID498/exec26831, full run/verifier pending;
not yet completion. Monitor ACTIVE at30min, no duplication or guard waiver.
