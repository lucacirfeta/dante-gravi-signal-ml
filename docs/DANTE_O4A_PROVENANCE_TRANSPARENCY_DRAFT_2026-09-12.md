# DANTE O4a native-source provenance transparency note

Status: complete draft pending public cross-reference review

Prepared: 2026-09-12

Canonical rerun completed: 2026-09-14

## Purpose

This note records a provenance limitation in the corrected O4a native-index
chain, the earlier attempt to reconcile it, and the complete rerun undertaken
to close the uncertainty. It will be published as an append-only correction to
the project record regardless of whether the rerun changes any output.

## What was not retained

The original native cohort, native index, and first native rescore contracts
recorded the SHA-256 digest
`2c20d4e89b48060986770127bf41c2d860d22efc4f98f430cb152cfb71f39dcf`
for the working-tree bytes of `src/core/patch_producer.py`. Those exact bytes
were used as a run-time provenance gate, but they were not committed or retained
as a separate source snapshot and are not recoverable from reachable or
unreachable Git objects currently available to the project.

The retained canonical LF-normalized source has digest
`67b858e2ed6e6b0451cf29040f0a39ba98b29828460b5094be6d2f47012f7fef`
and is recoverable from Git. The lost digest is neither this LF digest nor the
digest of a uniform CRLF conversion. The project therefore cannot prove from
retained bytes alone that the lost working-tree source was semantically
identical to the canonical tracked source.

## Why the 2026-09-04 reconciliation was insufficient

The reconciliation published on 2026-09-04 correctly stated that the original
byte representation was not retained and identified a canonical tracked source.
It also performed a successful 12-window WSL replay. However, it classified the
gap as a line-ending reconciliation, declared no full rerun necessary, and
treated the subset replay as sufficient to close the provenance question.

That conclusion was too strong. The subset replay provides useful evidence of
agreement on those 12 windows, but it cannot establish the identity of an
unretained source over the complete 1,294-window index cohort and all downstream
scores, thresholds, classes, taxonomy, coincidence, PEM, and comparison outputs.
The earlier reconciliation remains preserved as historical evidence and is not
silently replaced.

## Public records affected by the incomplete explanation

The following records were created while the 2026-09-04 reconciliation was the
project's stated resolution of the source-identity gap and therefore require an
explicit transparency cross-reference:

- the corrected-science preprint record, arXiv:2606.25702;
- the workflow-architecture preprint, arXiv:2609.08695;
- GitHub release `v3.8.0`;
- Zenodo record 22681395, DOI `10.5281/zenodo.22681395`;
- the project discussion associated with IGWN thread 1544, to the extent that
  it cites results derived from the affected chain.

This does not by itself establish that any reported scientific value is wrong.
It establishes that the source identity supporting the chain was not as fully
reproducible as the public reconciliation implied.

## Remediation protocol

The project froze a new fail-closed protocol before inspecting new outcomes. It
recomputes, with Git-recoverable canonical source and separate immutable output
roots:

`COHORT -> INDEX -> NATIVE_CALIBRATION -> RESCORE -> THRESHOLDS -> CLASSIFY -> TAXONOMY -> COINCIDENCE -> PEM -> COMPARE`.

The scientific populations, preprocessing, representation, clustering, scoring,
block-bootstrap, thresholds, classification, taxonomy, coincidence, PEM, and
comparison rules remain unchanged. Each stage is verified independently and its
new output is compared with the retained historical output at byte level or
under an already versioned numerical tolerance. No tolerance may be introduced
after outcomes are inspected.

The first `INDEX` launch stopped before creating a run identity or scientific
artifact because the host NVIDIA driver no longer matched the historical
runtime contract (`610.74` versus the then-current driver). The master rerun
protocol and historical runtime contract remain immutable. Following explicit
authorization to support routine driver updates, the project froze a separate,
INDEX-scoped runtime amendment for driver `616.92` and chained stage-scoped
amendments for the later GPU-dependent stages. Their validation requires all
other operating-system, Python, package, CUDA, cuDNN, device, representation,
and numerical-policy fields to remain identical; they do not add or relax a
scientific tolerance. Every resulting artifact remains subject to the same
byte/numerical comparison against its historical counterpart.

## Rerun result

The outcome-blind `COHORT`, representation-building `INDEX`, outcome-blind
`NATIVE_CALIBRATION`, score-only `RESCORE`, detector-specific `THRESHOLDS`,
deterministic `CLASSIFY`, morphology-only `TAXONOMY`, and physical
`COINCIDENCE` stages are now complete. The canonical cohort
contains 647 H1 and 647 L1 windows and its ledger is
byte-identical to the retained historical ledger. The canonical index replay
ledger is also byte-identical to the historical replay ledger. Its centroid
array, raw-embedding sample, and labels are byte-identical to the corresponding
historical NPZ members.

The complete NPZ container hash differs because three bound metadata values now
identify the canonical cohort, remediation contract, and amended runtime. No
scientific array differs. All 1,199 raw-source hashes, 1,294 clean-window
replays, 1,771,486 patch tokens, and the frozen K=1216 and 50,000-row sample
gates passed with zero raw, clean-window, context, or encoder failure. Compact
evidence is recorded in
`artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/corrected_native_index.json`.

The canonical native-calibration cohort contains 5,000 H1 and 5,000 L1
identities. Its ledger is byte-identical to the retained historical ledger
(SHA-256 `31438cd2d2df2014732467b99cf15dbcffd5f38cddf4784f1dc74fbe5ab47c00`).
Before selection, the remediation independently verified that the 1,294
outcome-blind identities in the INDEX consumption manifest exactly equal the
verified COHORT identities; this provides the frozen cross-detector 128-second
guard population required by the calibration contract. No score, threshold, or
class was read or computed by this stage. Compact evidence is recorded in
`artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/corrected_native_calibration.json`.

The canonical `RESCORE` replay contains 5,000 H1 and 5,000 L1
native-calibration rows plus 10,942 primary candidates (4,720 H1 and 6,222 L1).
All image, context-provenance, finiteness, and identity gates passed. The H1
calibration, L1 calibration, and candidate ledgers are each byte-identical to
their retained historical counterparts. No historical score or threshold was
read during the recomputation, and no threshold or class was computed in this
stage. Compact evidence is recorded in
`artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/corrected_native_rescore.json`.

The canonical `THRESHOLDS` replay used only the 5,000 calibration scores for
each detector. It retained the frozen non-overlapping block-bootstrap method
(block length 17, 1,000,000 replicates, seed 42), percentile 99 point estimate,
and 95% interval. The complete H1 and L1 input score-vector digests, method,
gates, point thresholds, and confidence bounds are identical to the retained
historical result. Candidate and historical scores were not used to derive the
thresholds, and no classification was performed. Compact evidence is recorded
in
`artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/corrected_native_thresholds.json`.

The canonical `CLASSIFY` replay deterministically classified all 10,942
candidates with the unchanged detector-specific confidence-bound rule. The
complete classified ledger is byte-identical to the retained historical ledger
(SHA-256 `4369a099e1cbb310ba936088e88f8a17cdcd23c71ca5dc539750d5c93ada092c`).
It contains 5,406 ROBUST, 2,344 AMBIGUOUS, and 3,192 BACKGROUND candidates.
No historical class, taxonomy, coincidence, or PEM disposition was read while
constructing it. Compact evidence is recorded in
`artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/corrected_native_classification.json`.

The canonical `TAXONOMY` replay used the unchanged primary-scan MIL vectors,
cosine distance, 0.25 distance threshold, single linkage, and historical family
naming over all 10,942 classified candidates. Its complete output ledger is
byte-identical to the retained historical ledger (SHA-256
`42ebf22a38ff20bdae8c9f2f92ef6c8b78ef336ec059e4ef00834bedb1f89bd8`),
and an independent label-invariant partition digest also agrees. The retained
single-linkage result is three clusters: one 10,940-member family and two
singletons. This reproduces the known chaining behavior; it is a morphology
taxonomy and not evidence of physical coincidence. Compact evidence is
recorded in
`artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/corrected_native_taxonomy.json`.

The canonical `COINCIDENCE` replay retained the asymmetric seed design: 5,406
ROBUST candidates were primary seeds, 2,344 AMBIGUOUS candidates were evaluated
as a separate diagnostic population, and 3,192 BACKGROUND candidates were not
processed. The partner detector was evaluated independently of its class or
catalogue presence. The complete primary ledger, diagnostic ledger, and
5,246-row raw-source receipt are byte-identical to their retained historical
counterparts. The unchanged pooled-null diagnostic threshold selected 9 ROBUST
and 56 AMBIGUOUS events for PEM follow-up; these are not described as globally
significant coincidences. All identity, replay, population, and physical
measurement gates passed, with maximum seed-score replay delta 0.0. The L1
feature localized at GPS 1382955253.17 remains in the ROBUST seed population;
its analysis window starts at GPS 1382955232. Compact evidence is recorded in
`artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/corrected_native_coincidence.json`.

The canonical `PEM` replay evaluated the unchanged shortlist of 9 ROBUST primary
targets and 56 AMBIGUOUS diagnostic targets. The target, primary-result, and
diagnostic-result ledgers are byte-identical to their retained historical
counterparts. All 65 targets were calibrated: the primary population contains
3 COUPLED, 1 SUSPECT, and 5 NO_CORRELATION verdicts; the separate diagnostic
population contains 3 COUPLED, 9 SUSPECT, and 44 NO_CORRELATION verdicts. The
excluded channel policy, family-wise alpha, block-based null calibration, and
diagnostic-only interpretation remain unchanged. These verdicts do not provide
astrophysical confirmation and do not cover unreleased sensors. Compact
evidence is recorded in
`artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/corrected_native_pem.json`.

The final `COMPARE` stage is complete. It replayed the frozen detector plus
normalized-analysis-GPS union, class-transition, adjusted-Rand-index,
identity-set coincidence, fail-closed PEM, and singleton rules. All three
candidate ledgers and the singleton record are byte-identical to the retained
historical outputs. All metrics and scientific-boundary fields are exactly
equal. The final comparison therefore retains 10,022 shared identities, 407
historical-only identities, 920 corrected-only identities, 1,626 class
changes, adjusted Rand index 1.0, 65 corrected pooled-null threshold exceeders,
and one normalized detector-GPS overlap between the corrected and historical
PEM target populations. No cross-contract PEM outcome comparison was made.

The L1 feature at GPS 1382955253.17 remains ROBUST in the analysis window
starting at GPS 1382955232, does not exceed the pooled coincidence threshold,
and is not a PEM target. The H1 historical singleton at normalized GPS
1369305280 remains ROBUST, exceeds that diagnostic threshold, and has the
unchanged primary PEM verdict COUPLED. Neither statement is a claim of global
significance or astrophysical confirmation.

The first final-comparison launch was stopped by missing adapter row-count
metadata before any scientific output was written. A second complete launch
reproduced every JSON value but serialized the singleton record with WSL LF
line endings rather than the historical Windows CRLF representation. Both run
directories and their explicit failure/supersession records are retained. A
third contract froze explicit CRLF serialization before rerunning; it then
reproduced all four historical output files byte for byte without a tolerance
or scientific change.

The verified canonical run and contract identifiers are:

| Stage | Run key | Contract digest | Historical comparison |
|---|---|---|---|
| COHORT | `0b76b9852c825fe26344f6468ff464865f10471d8b289912680225d08b447397` | `ddca4c6e8e791f1242c2b289d51781ea874f0b5031a187c887fe029472acbe80` | byte-identical ledger |
| INDEX | `750681d0e35f1a9f766e37e6d3b858280b903d50dbbc982458f0662c6553488b` | `7c2446b50f4c3abe2d182954ef9d9ed460b84ffb7f37271efea6ceca75c4eaa9` | scientific payload byte-identical |
| NATIVE_CALIBRATION | `152d077c0c2211b3d7574ad230e0a672e69027c1eaa220a9af20df9e5b7f7b4a` | `e79fe3f6fef1af5d84e9aab6e535761cd52f13c61ac7a588eeebad7ec5c32327` | byte-identical ledger |
| RESCORE | `cfb5620e028cd8d1b2c5930aa55ec774e886bde0bc9acfb5a00a5cb10a892077` | `22c8d336990527adc4f7145aaa81d16a657dcece47ef1b2077742bc60e5f3754` | byte-identical ledgers |
| THRESHOLDS | `b6fae7d8534e08c0f84889a8734e12b7ecc3801d52f1f700594765684c33eb77` | `56f4c33d07c4d45847e0ac31699ff1facddc285b224ef2d71f75cade0f4b8c54` | scientific output identical |
| CLASSIFY | `4b5132b3086057ed8981eba954c8aa9b29f51d05496b4269bf095fe7e4198548` | `8ad71d6c10db704f41889697aa7fd9dae083886711c64617307d654b8436dabb` | byte-identical ledger |
| TAXONOMY | `02b60e82e59c198187cb4cb295ee3149c9bc7c2c0635b6c8bc720f8e37d5712c` | `381d05639a9c311cfca60b401855cdac15b152782d3c1ae65c5c49c18bbcb231` | byte-identical ledger |
| COINCIDENCE | `fa847338ac1e59008c07434510233e991da00d626435805f1f5ffadd8fe50e8e` | `269e6df82bf7db71bfead36d331de6045439de35732f3d81e4bb96355bf753fc` | byte-identical ledgers and receipt |
| PEM | `529a3149d746ef03fdbabef13936ae9f479a8efae39692a05e5f862d47c7bf02` | `1d4ba0a6ff51ee020496cb46ae8611b42a5179696d24da3885b6209072b694f9` | byte-identical ledgers |
| COMPARE | `7db808838ce9f0ca4149048ec6257695b9dccfb3e3b16ce382b8e350d2d03371` | `ffe704a9771048274a55f03d809deb9c37940081df02e363f96c8b5cd571c548` | byte-identical outputs |

Compact evidence for the final stage is recorded in
`artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/corrected_final_comparison_v2.json`.

## Interpretation and record updates

The complete canonical rerun establishes empirical equivalence of the retained
scientific payload under the frozen protocol. It found zero changed cohort or
calibration identities, scores, thresholds, classes, family assignments,
coincidence selections, PEM dispositions, or final-comparison values. The only
non-byte-identical containers were already-declared provenance metadata and the
superseded LF serialization attempt; their scientific arrays or JSON values
were identical.

This result does not recover the lost `2c20...` source bytes, prove what those
bytes contained, or retroactively make the 2026-09-04 explanation precise. It
does show, by complete recomputation with the retained Git source rather than a
12-window subset, that the published corrected scientific outputs are
unchanged. Consequently no numerical scientific correction is indicated by
this rerun. A public transparency cross-reference remains required because the
earlier provenance explanation was incomplete, independent of the unchanged
scientific result.

The final note and any GitHub, Zenodo, arXiv, or IGWN update will be prepared for
human review and will not be published automatically.
