---
phase: 08-multi-run-productization
plan: 27
completed_at: 2026-10-03
status: awaiting_admission_decision
---

# 08.27 Summary: raw recovery numerical PASS, not admission

Tasks1/2 complete;checkpoint3 awaits author. Source commit71c9f5e.
New isolated run,one acquisition/one offline verify,both observed WSLexit0.
28 source frames/contexts/receipts;28/28 numerical SHA matches versus frozen
historical receipt,0/28 container SHA matches;zero failure/partial/lock.
Verification statusPASS_VERIFIED_RAW_NUMERIC_MATCH_ONLY,sealc03856b9...;
scientific/admission flagsfalse. Preserve old receipt and both sets of evidence.

Windows150 PASS/16.62s,WSL150 PASS/13.23s,post-freezeWSL14 PASS/2.86s,exit0;
Ruff3 files PASS,11 upstream WSL warnings,actual workers stderr empty.
Fixed helper import/lint exemption before freeze,all tests rerun. No runtime,
driver,selection,score,threshold,calibration changes,push or user-folder edits.

Next:author approval for new receipt schema/admission using explicit exact raw
numerical parity while preserving old container provenance. No automatic old
hash replacement. O4b requested next only AFTER common pipeline readiness and
scientific/data gates,not via unapproved legacy shadow promotion.
