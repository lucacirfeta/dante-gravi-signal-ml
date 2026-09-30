# Local L1 Gate C: approved execution plan

The author approved exact relative half-open sample boundaries and historical
strain-only native-rate highpass, antialiased resampling, then local cropping.
The new execution contract records the parity rationale and hash-bound O3a/O4a
source symbols. The frozen Gate B method and transport parents are immutable.
No local outcome has been inspected while preparing this plan.

## Task 1 — adapter, independent verifier, synthetic validation and freeze

Files: versioned local measurement config, module, runner, synthetic test file,
CLI ignore exception and this plan (six implementation files).

Implement offline identity-bound native readers for each individual context;
preprocess full contexts identically for events and controls; select timestamps
in `[start,end)` using relative ceil/ceil, not absolute-GPS subtraction or GWPy
crop. Bind the unchanged method, verified parent receipts, source bytes, Git
freeze and runtime. No fetch fallback. Independently reconstruct Welch from
demeaned periodic-Hann FFT segments; additionally require exact producer replay.
Independently replay block maxima, conservative ties, two-target multiplicity
and the already approved decision rule. Resample only whole paired 96-second
blocks for the descriptive bootstrap. Save all replicate exceedance counts;
no new confidence-level convention is introduced. Missing/unavailable contexts
are accounted whole-block exclusions; input provenance failures stop the run.

Verify: synthetic boundary, parity, alias rejection, locality, independent
spectrum, block and target accounting, bootstrap, threshold equality, missing
data and tamper/failure tests; full WSL local/common/native PEM/PatchProducer
regressions and Ruff. Done: green evidence and local source-freeze commit
before any event or control coherence is measured.

## Task 2 — exact input-bound plan, run and standalone verifier

Depends on Task 1 and the verified matched-sample checkpoint `8592cfb`.
Files: external sealed run artifacts, result checkpoint, STATE and JOURNAL.

Plan replays the verified input parent offline and preserves both target
identities, including the first target's metadata-only INCONCLUSIVE disposition.
One run accounts all eligible blocks; partial runs are uninterpretable and
cannot resume automatically. One independent verifier rereads the native
inputs and checks every context, block, decision, bootstrap and sealed summary.
Capture actual OS exits for plan, run and verifier. Only after exit 0/PASS
report results, update checkpoint/STATE/JOURNAL and commit locally. No push,
public communication, discovery claim, additional channels or retuning.

Verify: parent/source/file/sample seals; exact target/control identities; zero
failure, partial or lock; independent numerical replay plus exact producer
replay; regression and Ruff. Done: verified diagnostic result, or preserved
failure with a concrete blocker. Negative results clear only the tested channels;
positive screens require separate detchar, coupling and channel-safety review.

## Plan check

PASSED: requirement coverage, task completeness (Files/Action/Verify/Done),
acyclic dependency, input-to-adapter-to-verifier links, two-task scope and
goal-derived acceptance criteria. No blockers; no warnings. The approved
numerical policies are explicit before Gate C, not selected from its results.

## Pre-run evidence

WSL local-followup/common-PEM/native-PEM/PatchProducer regression: `210 passed,
11 warnings in 46.43s`, OS exit 0, including 42 new tests. Ruff lint and format
PASS. Fixture-only preliminary defects were corrected before the source freeze;
no real local event/null outcome was inspected. Installed versions are pinned
in the execution contract, with numeric implementation hashes recorded in the
plan. Git-source EOL qualifications are retained, never normalized in place.
