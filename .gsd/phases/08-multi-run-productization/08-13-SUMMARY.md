---
phase: 08-multi-run-productization
plan: 13
completed_at: 2026-10-01
scope: isolated_snapshot_foundation_bytes_only
---

# Summary 08.13: isolated retained byte snapshot foundation

Author approved A with `procedi` after the explicit native PEM safety choice.
Source freeze: `9f15560` on science/o3-transfer-readiness; local only, no push.

## Completed increment

- Versioned technical policy, independent module, capture/admit CLI and 63 tests.
- Externally pinned capture plan included byte-for-byte in ZIP; exact name/order,
  member size/hash and closure, policy identity and seals verified before receipt.
- Detached immutable byte consumer; copied JSON/manifest/receipts cannot mutate
  retained bytes. No live origin access, extraction, archived code execution,
  fetch, scientific measurement or historical verifier call after admission.
- POSIX descriptor-relative nofollow capture and exclusive publication; links,
  special files, drift, unsafe/extra/partial members, compression and resource
  violations refused. Output outside input roots and never overwritten/removed.
- Explicit byte-only receipt; no scientific parent closure, original capture
  quiescence, live writer exclusion, PEM/null replay or full-workflow PASS.
  No dispatcher adoption, new scientific choice or historical snapshot capture.

## Empirical verification

Broad pre-freeze regressions (not the entire repository scientific suite):

```text
WSL: python -B -m pytest -q --tb=short tests/test_dante_workflow*.py tests/test_dante_o3a_native_pem.py tests/test_patch_producer_context.py
884 PASS, 6 platform skips, 11 upstream warnings, OS exit 0, 377.77s

Windows: explicit rg-discovered test_dante_workflow*.py argument array
672 PASS, 197 POSIX-only skips, OS exit 0, 228.18s
```

These broad processes were already in flight when publication was hardened to
POSIX descriptor-relative output. They are not described as post-freeze final
publisher checks. Dedicated final source-frozen tests below exercise that change,
including explicit Windows refusal. No earlier scientific source changed.

Post-freeze target, separate observed OS results:

```text
WSL: 62 PASS, 1 Windows-only skip, OS exit 0, 1.80s
Windows: 54 PASS, 9 POSIX-only skips, OS exit 0, 0.46s
```

Ruff workflow module lint plus new CLI/tests PASS; three-file format check PASS.
All three new Python files and the policy are byte-identical to their Git blobs.
Previous upstream EOL qualifications remain untouched. Scoped diff-check PASS.

Initial broad launchers both exited 1 before any test ran: wrong PatchProducer
filename in WSL and literal wildcard not expanded in Windows. Fixed only command
construction: actual context-test filename, WSL Bash glob and Windows rg array.
Initial lint found E402 from a late test import; moved it to the import block,
without waiver. Admission review added the original pinned plan bytes to ZIP,
so a resealed replacement manifest cannot claim an unchanged external plan pin.
No scientific gate relaxed or dependency installed.

## Qualifications and next step

New snapshot tests are disposable/synthetic only. The original native PEM suite
includes optional real-parent metadata preflight if the external root is mounted;
do not describe all broad-suite tests as having read no historical metadata.
No productive historical run or new outcome inspection was initiated here.

The transport/isolation foundation is complete, not the native PEM adapter.
Next: complete frozen PEM/upstream/source closure and retained decision-parity
adapter using this immutable view, with synthetic refusal/parity tests before
historical replay. Complete profile/preflight adoption, quiescent clean-install
scientific replay and multi-run/Virgo readiness remain open. Original O3a closure,
historical producers/config/artifacts and unrelated user folders are preserved.
