# Local L1 follow-up: matched native input gate

## Scope and immutable scientific boundary

This increment implements the transport/replay step authorized after the
outcome-blind input metadata checkpoint. It does not compute local coherence,
the reference-tail screen, bootstrap output, a veto or any physical inference.
The approved method and its two-target family remain unchanged in
`config/dante_o3a_l1_local_followup_v1.json` (source freeze `775ca7e`).
GPS 1238508320 remains INCONCLUSIVE for insufficient same-segment controls.
Only GPS 1241808544 has resolvable, eligible controls. Neither target is an
independent preselected discovery candidate; both were selected post hoc.

The transport-only contract is `config/dante_o3a_l1_local_samples_v1.json`.
It binds the verified input metadata summary seal
`c8373038cf651baeffff651c5fb89358a0ae05ddb45b6c63431dba3ed2c01ea2`
and file SHA256
`fddeaf1073a1c3ef751c6b364a95fcb4e60d2a3be36091a2b161e04100c8fe84`.
This separate input contract permits acquisition, not Gate C measurement;
the original method's unopened measurement gate is not bypassed or rewritten.

## Executable plan

### Task 1 — native transport adapter and synthetic regressions

Files: the transport contract, `src/dante_light/o3a_l1_local_samples.py`,
`scripts/run_dante_o3a_l1_local_samples.py`,
`tests/test_dante_o3a_l1_local_samples.py`, and the CLI ignore exception.

Action: inherit exactly the metadata-approved 426 blocks/1,278 control
contexts. Merge only adjacent accepted contexts into 53 download containers;
keep original statistical identities and never fill a rejected gap. The
five native L1 channels require 265 auxiliary series and 3,266,445,312
sample bytes before headers. Native rates, NDS2 host, chunks and retry policy
come from hash-bound parent contracts. No casting, filtering or resampling.
The excluded EX_VMON and EY_MAINSMON channels remain excluded.

The event's exact five native series are verified and referenced from the
historical common-PEM parent; there is no event refetch or historical write.
Official O3a_4KHZ_R1 strain comes from the pinned MD5 manifest, exact HDF5
metadata and the existing deterministic v2 probe inside a used interval.
There are 53 control strain spans plus one 32-second event strain span.

Verify: synthetic geometry, gap preservation, identity/rates/exposure,
immutable historical event bytes, complete file and receipt accounting,
offline replay, altered native samples, orphan/partial/lock rejection,
sealed-summary mutation, and both infrastructure/structural failures.
Run the WSL local-follow-up/common-PEM/native-PEM/PatchProducer regressions
and Ruff before source freeze and any productive controller.

Done: green tests and a reviewable local Git source-freeze commit. No real
local statistic may be inspected during this task.

### Task 2 — one acquisition, independent local replay and checkpoint

Action: execute `--stage plan`, audit its source hashes, exact population,
event references, manifest coverage and run key. Start one WSL controller
only, using the exact planned directory under
`E:/dante_cache/dante_light/o3a_l1_local_followup_v1/matched_samples`.
Retain stdout/stderr, OS exit codes, sealed progress and all receipts.

Verify: after completion and controller termination require exit OS 0,
`PASS_MATCHED_NATIVE_SAMPLES_COMPLETE_ONLY`, all planned official frames,
54 complete strain receipts, 265 native control files/receipts, five intact
borrowed event references, and zero failure/partial/lock. Execute one
standalone `--stage verify` and require exit OS 0 and
`PASS_VERIFIED_MATCHED_NATIVE_SAMPLES_ONLY`. The producer and verifier replay
every used strain/auxiliary sample through separate reader paths; the
standalone replay makes no NDS2/GWOSC fetch and is **not a second source
measurement**. Run post-tests and audit current source bytes against the
sealed plan and Git freeze. Record the result in this checkpoint, STATE and
the local JOURNAL.

Done: a verified matched-input receipt, not a PEM result. A later measurement
adapter must bind this receipt, preserve the approved full-context
preprocessing and numerical rule, pass synthetic/regression tests and freeze
its sources before opening real local outcomes. Positive screens still
require separate channel-safety and physical-coupling review.

Failure handling: preserve everything and diagnose. The runner refuses any
terminal rerun, active lock or failure; it has no automatic failure archival
or resume procedure. Exhausted transport is distinguished from structural/
provenance defects. Do not clear a failure or lock to force execution.

## Plan review

Requirements, task completeness, dependency ordering, input binding, scope
and goal-backward acceptance checks are covered. Transport merging changes
containers only, not the statistical population or validation construction.
All numerical science parameters remain in the approved method contract.
The first target cannot be made negative by insufficient data; family size
remains two. This gate cannot establish sensor safety, formal significance,
astrophysical origin or a discovery.

## Validation and execution evidence

Pre-run WSL regression: **168 passed**, 11 upstream warnings, 42.20 seconds,
OS exit 0. Ruff lint/format PASS. Source freeze: `3a9303e`; plan documentation
commit: `bacdac4`. The real `--stage plan` finished with OS exit 0 and
`FROZEN_MATCHED_NATIVE_SAMPLE_PLAN_NO_OUTCOMES`.
The initial synthetic fixture errors concerned its temporary root and absent
fixture status; they were repaired before any live acquisition. The targeted
matched-input suite subsequently passed all 25 tests.

Plan/run directory:
`E:/dante_cache/dante_light/o3a_l1_local_followup_v1/matched_samples/samples_e55ae7830250617c9c9ece1e6984285ed249c73e38a4d44740be4e4c715d4c86`.
The plan accounts for 20 official strain frames, 54 full-used strain spans
and 265 native control auxiliary series. All 17 sealed source hashes match;
the three new contract/module/runner files are byte-identical to Git freeze.
The five borrowed historical event files passed native sample replay.
Git audit: 16 sealed sources are byte-identical to the freeze. The existing
`src/dante_light/contracts.py` working bytes are reconstructed exactly by
LF-to-CRLF conversion of Git bytes, matching the upstream qualification;
the file was not normalized or modified. No unexplained source mismatch.

One WSL `--stage run` controller was started with stdout/stderr retained and
supervision session 51240 for its OS exit. No duplicate controller was found;
initial stderr was empty and E: had about 620 GiB free. Acquisition/replay
completion is still pending. No real local PEM statistic has been computed.
