---
phase: 08-multi-run-productization
verified: 2026-10-06T02:13:30+02:00
status: passed
score: 3/3 must-haves verified
is_re_verification: false
---

# 08.38 verification: full preprocessing only

| Must-have | Status | Observed evidence |
|---|---|---|
|All frozen contexts yield unchanged worker images|VERIFIED|runOS0/PASS_COMPLETE;39891sealed receipts+39891NPY;bound39971identities19715H1+20256L1|
|All images independently reread/reconstructed|VERIFIED|standaloneOS0/PASS_VERIFIED; exact all-context uint8 equality, no sampling/tolerance|
|No exclusions/scoring/threshold/promotion/O4b|VERIFIED|sealed false boundary flags; unchanged parents,39863new+28prior and complete union|

Artifacts: versioned replay contract, substantive controller and standalone CLI,
sealed run/verification/binding and complete receipt/image inventories all exist.
CLI -> controller -> unchanged worker -> NPY/receipt wiring verified; standalone
h5py -> explicit SAME frozen scientific primitives -> exact image comparison.
Post-run WSL306PASS/11upstream warnings/19.89s, exec85168 observedOS0.
Ruff lint/format3files PASS. Read-only audit86486 OS0:14 source Git pins, parent
hashes/runtime,39891 sealed receipt union/aggregate and inventories match.
No anti-pattern blocker, remaining controller, failed or incomplete evidence.

Verification SHA3a96f012f5007b855db82df223372359661465203a3b6201a1bd0b144e9b4f7f;
seal4e31466a574ac8078ed377a8fbafafa105cecfb405666b678bcdef716f23a8d1.
Summary SHAa78c5f3896206d651d27d062861404a26c6046f0d4771c423030db233fb449c5;
seal29b9adedbe5a46adcc20151ab1a45da32ee069c27adb0aa97e5b3273cd9b456f.
Durable worker.supervisor.stdout.log records both exit0, observed directly in
full84146 tool result. First extra diagnostic audit's missing identity_keys
field was corrected without editing inputs or bypassing any provenance check.

Human scientific review, physical data quality/sensor safety and all subsequent
calibration/product/installation/O4b-specific gates are outside this verdict.
