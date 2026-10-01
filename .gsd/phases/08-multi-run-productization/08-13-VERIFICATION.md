---
phase: 08-multi-run-productization
plan: 13
verified: 2026-10-01
status: passed
scope: isolated_snapshot_foundation_bytes_only
score: 5/5
is_re_verification: false
---

# 08.13 snapshot foundation verification

This status applies only to the isolated byte-container increment, not the
complete native PEM adapter or Phase 08 scientific readiness.

## Observable truths

| Truth | Status | Evidence |
|---|---|---|
| Every declared member matches an externally pinned byte plan | VERIFIED | Plan included in archive; external plan SHA, internal seal, exact membership/size/SHA tests; resealed changed-member manifest still refused against original plan |
| Admitted consumers do not consult live origins | VERIFIED | Owned immutable byte tuples; origin modification/deletion tests; filesystem APIs forbidden after admission; detached JSON/manifest/receipt copies |
| Unsafe capture/archive states fail closed | VERIFIED | Component-relative nofollow capture, single-link regular files, size/hash/signature and final reread; traversal/duplicates/symlink/hardlink/FIFO/compression and resource-limit tests |
| Publication cannot overwrite an existing target or intentionally write within input roots | VERIFIED | POSIX descriptor-relative exclusive-create, explicit external destination; CLI no-overwrite and input-overlap tests; unsupported Windows publication refused |
| Byte success cannot masquerade as scientific/full-workflow PASS | VERIFIED | Dedicated unregistered CLI/status, all scientific/quiescence flags false, receipt has no outcome fields; original scientific code/config unchanged |

## Artifacts and wiring

Policy, module, separate CLI and tests exist and are substantive. CLI capture
loads a pinned plan and explicit roots, calls capture, independently admits the
created blob and exclusively publishes a new output. CLI verify admits only a
pinned supplied blob, never invokes capture/publication. Module consumers read
only the detached byte view. No scientific dispatcher/adoption was added.

## Qualifications

- Metadata rereads/hash closure detect divergence; they do not establish live
  producer exclusion or globally atomic capture. Caller-supplied plan authority
  and complete scientific parent closure are not certified by the byte gate.
- Selected failure/lock/partial member names refuse. Unselected directory
  guards/caches and stage-specific populations still require the next adapter.
- Immutable Python bytes isolate trusted consumer code, not arbitrary hostile
  code in the same process. ZIP is never extracted or executed.
- Capture/publication tested on temporary POSIX filesystem fixtures. No
  historical snapshot, E: publication, complete scientific replay, fresh
  sensor/null measurement, public activation or multi-run/Virgo certification.
- Windows tests certify portable byte admission and explicit capture refusal.
- The next increment must wire complete frozen native PEM/upstream bindings and
  retained decision parity to this view before any historical evidence replay.

Empirical commands/counts and source freeze are recorded in 08-13-SUMMARY.md.
