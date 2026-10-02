---
phase: 08-multi-run-productization
plan: 17
verified: 2026-10-02
status: passed_scoped_implementation_external_parent_blocked
source_freeze: cdca437
real_complete_chain_verified: false
---

# Verification 08.17: native upstream cooperative read-only lock extension

| Truth | Evidence and scope |
| --- | --- |
| SCAN/COHORT/INDEX/RESCORE markers are held, not ignored | Original producer flock code inspected; shared unchanged O_RDONLY nonblocking protocol; 20 new wiring/refusal tests |
| Lock lifetime includes final receipt checks | Explicit outer ExitStack through ancestors; final `_Evidence.unchanged` contention tests; release on normal/error exit and replaced-inode refusal |
| Exception is limited to a held directory | 8 shared-helper tests: registration disappears on exit, duplicate acquisition refuses, other run and late failure/partial guards refuse |
| Non-cooperative ancestry stays strict | Calibration marker refusal through both calibration/rescore scopes; generic initial `_clean` unchanged; own legacy PEM guard unchanged |
| Implementation is wired and source bound | Native source closure includes shared helper, inherited by all downstream; 47 PEM bindings; all 18 source commit files byte-exact Git |
| Scientific interpretation and historic bytes remain | Empty scientific-source/config diff; inherited three exact EOL qualifications intact; no original producer invocation in new tests or actual retry |

WSL broad workflow/native contract/native PEM/PatchProducer: 1020 PASS/7 skips/
11 upstream warnings, OS exit 0, 457.84s. WSL targeted readers 561 PASS/5 skips/
11 warnings, OS exit 0, 336.46s; new shared helper 8 PASS, OS exit 0, 1.05s.
Windows workflow/native contract 544 PASS/454 skips, OS exit 0, 171.08s;
new helper separately 1 PASS/7 skips, OS exit 0, 0.10s. Post-freeze helper plus
original contract: WSL18 PASS/exit0/3.84s; Windows11 PASS/7 skips/exit0/2.08s.
Ruff lint/18-file format and diff checks PASS. No all-repository/platform claim.

Initial synthetic stale source-count assertions and missing rebuilt fixture lock
were repaired, not hash checks bypassed. Source binding counts reflect one added
executed helper. New regression count is 28 (20 upstream wiring +8 helper).

Actual retained coincidence retry (session93544) ran exactly once after source
freeze with all explicit roots and approved driver-only opt-in. Observed OS exit1,
FAIL_CLOSED/InitialEvidenceError: SQLite transaction sidecar present. All12 marker
bytes/metadata unchanged, stderr empty. Source audit PASS18 files before retry.
Read-only diagnosis (session9582 OS exit0): contract-derived SCAN directory8f0424e,
sealed summary valid and DB SHA1f222dfb... matches expected; WAL0 bytes, SHM32768
bytes. No matching Linux scientific Python process and fuser no observed owner.
These are observations, not permission to ignore/drop transaction sidecars.
No SQLite open/checkpoint/historical edits/retry; unchanged policy remains strict.
Full snapshot/real PEM chain, dispatcher adoption, all-run/Virgo scientific
readiness remain unverified. No push, capture, raw scoring, fresh null or sensor
fetch. Stop for author choice on isolated receipt-bound database evidence versus
canonical clean historical export. Neither new input-policy option implemented.
