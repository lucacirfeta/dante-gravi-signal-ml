---
phase: 08-multi-run-productization
plan: 18
verified: 2026-10-02
status: passed
scope: isolated_scan_database_bytes_only
score: 5/5
---

# Verification 08.18

1. Original data and sidecars unchanged: synthetic byte/metadata assertions plus
   real source pin rechecks in capture/standalone verify; both OS exits0. No
   historical SQL connection/checkpoint/update/delete path exists in transport.
2. Exact DB bytes from sealed historical summary: real size213794816 and expected
   SHA1f222dfb match; receipt externally pinned SHA17558e62. Origin eligibility
   excludes nonempty WAL, any journal, unsupported SHM; defaults stay unchanged.
3. Exclusive safe new output: descriptor-relative nofollow readers/publisher,
   single-link regular files, overlap/overwrite refusal, receipt-last completion,
   incomplete output preserved; adversarial synthetic tests PASS.
4. Verifier is substantive and wired: CLI separate capture/verify operations,
   standalone verify reconstructs expected identity/policy/source/origin closure
   and validates every published file and externally pinned receipt. Real verify
   exit0/PASS_VERIFIED_ISOLATED_SCAN_DATABASE_BYTES_ONLY_V1,17 bindings.
5. Regressions and provenance: final WSL320 PASS/1 skip, Windows98 PASS/47 skips;
   post-freeze transport34 PASS, Ruff PASS, six files exact Git, original science
   and inherited EOL qualifications unchanged, user untracked folders preserved.

No stubs or new scientific/structural decision beyond the approved isolated copy.
Boundary false flags explicitly deny scientific closure/runtime equivalence/
global quiescence/transaction replay/full-workflow verification. No human action
needed for this scoped transport increment. Next reader admission and complete
historical chain remain open and must not inherit this byte-only PASS as their
own scientific certificate.
