---
phase: 08-multi-run-productization
plan: 17
date: 2026-10-02
status: implementation_passed_external_parent_blocked
source_freeze: cdca437
---

# Summary 08.17: approved native upstream lock extension

Source commit cdca437: shared O_RDONLY persistent-lock helper extracted from the
existing decision reader. Native scan/cohort/index/rescore gates acquire and bind
their existing marker bytes, propagate one explicit ExitStack through parents,
and hold locks through final inputs/sidecars/guards/source checks. Calibration and
initial/non-cooperative guards remain strict. No scientific source/config edits.

Changed 8 workflow sources, 8 test files, one exact new-test EOL attribute and
this plan (18 source-commit files, audited byte-exact Git). Added 28 tests. Existing
upstream adversarial tests retained; technical source-binding counts increased
for one actual executed helper. Original three LF-to-CRLF qualifications preserved.

WSL broad 1020 PASS/7 skips/11 warnings/OS exit0/457.84s; targeted561 PASS/5 skips/
11 warnings/exit0/336.46s plus helper8 PASS/exit0/1.05s. Windows broad544 PASS/
454 skips/exit0/171.08s, helper separately1 PASS/7 skips/exit0/0.10s. Post-freeze
helper+old native contract WSL18 PASS/exit0/3.84s, Windows11 PASS/7 skips/exit0/
2.08s. Ruff and scoped diff checks PASS. Platform skips explicitly acknowledge
the POSIX-only protocol, not false Windows lock validation.

Deviation: temporary parity fixture recreated INDEX without its marker; added
the required producer marker to that synthetic builder. Stale synthetic source
cardinality expectations increased by one. No historical repair/hash bypass.

Actual parent retry once, session93544, after audit/freezing: observed OS exit1,
FAIL_CLOSED/SQLite sidecar refusal. All12 persistent marker SHA/size/inode/mtime/
ctime/link-count metadata unchanged. No real-chain PASS inferred. Diagnostic
session9582 exit0 finds contract-derived SCAN8f0424e: DB matches expected SHA and
summary seal valid, WAL0 bytes/SHM32768 bytes; no Linux scientific Python process
or fuser owner observed. Does not prove global quiescence or authorize dropping
sidecars. No SQLite open/checkpoint, second retry or historic repair.

Next: author decision for separately specified isolated database evidence copy
with receipt/sidecar provenance, or canonical clean historical export. Neither
implemented. No snapshot, producer, scoring, fetch, null, push/main/merge/release
or user-file mutation. Whole workflow/all-run/Virgo readiness remains open.
