---
phase: 08-multi-run-productization
plan: 14
verified: 2026-10-01
scope: retained_native_pem_snapshot_and_parent_handoff
status: passed
score: 5/5 implementation truths with fixture and platform qualifications
source_freeze: f254b2b
overall_multi_run_productization_complete: false
---

# Verification 08.14: retained native PEM decisions on isolated bytes

| Required truth | Evidence and qualification |
| --- | --- |
| Original readers use owned bytes only | Unpatched contract/inventory/preflight/event helpers run on the virtual view; live Path readers and all original productive/fetch/measure/null/writer functions prohibited; no fspath or write fallback |
| Actual parent chain is wired and protected | Implementation calls actual 08.12 with every explicit root and the same ExitStack; linked fixture executes that gate and observes its three locks at PEM handoff, then intentionally refuses; earlier ancestry isolated, not a complete-chain positive certificate |
| Exact retained targets/exclusion/decisions/output seals | Main own-stage original unpatched preflight, complete exclusion population, source coverage, detector-local channels and strict boundaries; original calibration/maximum/tier validator, canonical JSONL, full summary/compact and grouped/per-event correspondence; resealed drift negatives |
| Changed/incomplete/unsafe evidence refuses without writing | Archive/plan pins, exact parent/member/consumed/source closure; missing/extra/source/parent/guard/cache negatives, live parent final rehash and mid-replay guard failures, link refusals; own live outcome mutation cannot alter snapshot proof; successful bytes/mtimes identical |
| Separate bounded CLI and empirical tests | No productive options, stdout scoped success/refusal, Windows early POSIX refusal; complete targeted and workflow regressions, Ruff; no dispatcher/adoption or scientific source/config change |

## Three-level artifact and wiring checks

Module, CLI and 69-test file exist, contain substantive validation and are wired.
The CLI calls `verify_pem_evidence`; it invokes snapshot admission, actual parent
gate, original pure PEM helpers on virtual paths and final evidence/source/guard
checks. There is no implementation monkeypatch, archived-source execution,
productive verifier, downloader, sensor coherence/null recalibration or writer.
Existing parent locks are not recreated/removed; legacy PEM lacks such a lock,
so its observations are explicitly not live-writer exclusion. No stub/TODO found.

## Observable validation

WSL target: 68 PASS/one skip/11 upstream warnings, OS exit 0, 91.13s.
Windows target: 47 PASS/22 platform skips, OS exit 0, 63.03s.
WSL full workflow+original native PEM+PatchProducer: 952 PASS/seven skips/
11 upstream warnings, OS exit 0, 508.94s.
Windows complete workflow: 718 PASS/220 platform-conditioned skips, OS exit 0,
316.53s. These are not whole-repository/all-platform scientific certificates.
Ruff complete workflow/test/new CLI lint PASS and three-file format PASS/exit 0.
Post-freeze target checks are recorded after completion below.

Reproduction of the reported broad commands:

```text
# WSL Bash in the repository, its existing scientific environment:
/home/atafe/miniconda/envs/dante_env/bin/python -B -m pytest -q --tb=short tests/test_dante_workflow*.py tests/test_dante_o3a_native_pem.py tests/test_patch_producer_context.py
# Windows PowerShell expands paths with rg rather than a literal pytest glob:
$taskWorkflowTests = @(rg --files tests -g 'test_dante_workflow*.py')
& 'C:/Users/atafe/AppData/Local/Programs/Python/Python311/python.exe' -B -m pytest -q --tb=short $taskWorkflowTests
```

## Source evidence

Local source freeze f254b2b. Three new Python files equal Git byte-for-byte.
Original native PEM module/entry/tests and null-calibration helper also equal Git.
Coherence helper SHA48c557db470441c38a0c1bd24e8a07abfca21616f7bdcc3304d2eea3b707652b
matches frozen contract but differs from Git blob. Exact Git LF-to-CRLF
reconstruction equals working bytes, diagnosed without normalization/bypass.
Checkpoint records Git hash/sizes. Earlier contracts.py/physical-helper EOL
qualifications preserved; not a claim of all-source Git byte identity.

## Scope and human review needs

Main fixture isolates coincidence ancestry, but not own original PEM scientific
loaders; it mixes frozen source/DQ/method metadata with disposable scaled event/
calibration values. A contract-only frozen metadata smoke does not read old PEM
outcome files. Linked test runs actual coincidence and stops deliberately at own
contract handoff; taxonomy ancestry/old fixture loaders remain isolated. No
positive actual historical/full-population/whole-parent-chain replay was performed.
The original native PEM regression may read historical parent selection metadata;
the complete suite must not be described as exclusively synthetic.

No physical-cause, sensor-safety, global significance or astrophysical conclusion
is supported here. Source freeze and unit/integration regressions do not adopt
this stage into public workflow or certify all runs/Virgo. A separately reviewed
real capture plan, bounded complete-chain execution, profile/preflight wiring and
clean-install scientific replay remain necessary. Original O3a diagnostic closure,
scientific contracts and user-owned files are unchanged. No push/merge/release.

## Post-freeze

WSL 68 PASS/one Windows-only skip/11 upstream warnings, observed OS exit 0,
87.16s. Windows 47 PASS/22 platform skips, observed OS exit 0, 55.26s. All 69
collected on both. No source edit after f254b2b; final three-source Git byte audit
matches. This PASS is restricted to the implementation truths and stated fixture/
platform boundaries, not actual historical complete-chain or multi-run readiness.
