---
phase: 08-multi-run-productization
plan: 34
verified: 2026-10-04
status: passed
score: 4/4
gaps: []
---

# 08.34 verification

1. VERIFIED: author-approved calibration-only policy binds unchanged parents,
   old baseline and full identity domain; old manifest/provider not redirected.
2. VERIFIED: substantive CLI wiring and69 new positive/negative tests, real
   synthetic direct HDF5/GWPy replay, failure preservation and drift checks.
   Full Windows1014/WSL1515 PASS with508/7 explicit skips; post-freeze126 PASS,
   11 upstream warnings,Ruff PASS;17source bytes+policy exactly matchGit745366c.
3. VERIFIED: actual pinned plan23452 observed OSexit0;39971identities,
   39863new+28prior contexts,707frames with coverage/official MD5. Conservative
   disk bound fits; one WSL recovery started with exclusive external namespace.
4. VERIFIED: acquisition4883, standalone38777 and admission32297 observed OSexit0.
   PASS_VERIFIED_CALIBRATION_NATIVE_RAW_ONLY and
   PASS_ADMITTED_CALIBRATION_EXACT_NATIVE_INPUTS_ONLY;39971 identities,
   39863 new+28 prior contexts,707 frames. Native SHA/GWPy replay consistent.
   Final audit confirms all seals/pins,17 sources+policy byte-identical to freeze,
   prior28 receipt unchanged, zero failure/partial/tmp/lock and empty stderr.
   Post-gate WSL126 PASS/11 upstream warnings; Ruff lint/format PASS, OSexit0.
   Admission seal97d856bcd3440d67788345adf9fbc60c1f9dbe17fde5a65d6e82245981a63665.

No stub or default runner redirection. This gate still cannot certify productive
full calibration, validity, another run or O4b. Source/identity/native mismatch
must preserve evidence and stop, not silently repair a scientific difference.
