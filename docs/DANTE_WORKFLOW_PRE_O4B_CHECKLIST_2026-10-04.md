# Pipeline readiness before O4b - approved sequence

Author instruction2026-10-04: proceed through all points autonomously; stop for
critical scientific/structural decisions or immediately before actual O4b start.
This is an execution checklist, not a claim of certification or launch authority.
O3a is closed; local commits only, no implicit push/main. Historical artifacts
and unrelated user untracked files stay untouched. Prior shutdown was one-shot.

Latest author2026-10-05: automatic work only until2026-10-06 08:00Europe/Rome
(06:00UTC). At deadline no new stage/test/edit; pause monitor, report retained
state and active processes, do not signal controllers or shut down the PC.

| Order | Gate | Current evidence / completion condition |
|---|---|---|
|1|Exact full native reader|COMPLETE2026-10-05:08.34 admission/08.35 binding PASS;08.36 v2 run OS0 and retry31599 independent verifier OS0/PASS_VERIFIED_EXPANDED_NATIVE_CONSUMER_ONLY.39891contexts/all39971identities, zero failure/partial/tmp/lock. Post-run250WSL PASS/11warnings,Ruff4files PASS,source10/parent4 match. V1 failed and interrupted first verifier preserved. Not preprocessing/scientific certification.|
|2|Complete padded-context validity and preprocessing|COMPLETE2026-10-06:08.38 run/standalone verifier both observedOS0/PASS_VERIFIED_EXPANDED_CALIBRATION_PREPROCESSING_ONLY;39891receipt+39891NPY,all39971bound identities. Zero failure/partial/tmp/lock/controller;14Git source/parent/runtime auditOS0.306post-runWSL PASS/11warnings/19.89s,Ruff3files PASS. Exact uint8 equality using SAME frozen scientific primitives, no new DQ filter/population reduction. Not physical DQ/sensor safety or full calibration.|
|3|Isolated productive integration|INPUT BOUNDARY VERIFIED2026-10-06:08.39 bind/standalone verify bothOS0,39891contexts/all39971identities;437post-runWSL PASS/11warnings,RuffPASS,16Git source/parent audit match. Explicit separate provider/profile with per-read guards, isolated output and single writer; no legacy/global redirection. Numerical productive calibration integration is the next separate increment, not implied by metadata PASS.|
|4|Full fresh calibration|OPEN. Entire frozen reference population, freshly computed embeddings/scores/thresholds as contracted, independent verifier, separate per-detector/session receipts. No historical score/threshold transplant.|
|5|Complete model/index/runtime qualification|OPEN beyond the bounded28-input proof. Full native representation/index/encoder/scoring/calibration dependencies and reproducibility gate. Driver recorded at actual runtime with fresh numeric proof, not permanently blocked by driver version.|
|6|Common CLI/UI end-to-end|OPEN. Correct adapters/prerequisites/receipts and stop/failure/resume behavior; no scientific stage opened by UI administrative PASS alone.|
|7|Clean scientific installation|OPEN beyond bounded proof. Fresh installed-reader/model/dependency replay; clean install green tests alone is not full scientific certification.|
|8|O4b-specific frozen scientific contract|OPEN. Explicit public release, detectors/GPS, DQ, population/reference/calibration and validation rules. Use versioned config, no O4a threshold reuse. Any not-yet-approved scientific choice requires author before execution.|
|9|O4b source/data/runtime/disk preflight|OPEN. Exact scientific contract, source/runtime/input receipts, completeness, independent replay and reviewable readiness summary.|
|10|STOP before actual O4b|Never launch from this authorization. Present verified checklist/results and request explicit start approval.|

H1/L1 are the primary supported detectors. V1 may be included only where data
exist and with dedicated calibrated representation/reference/null rules; never
silently reuse a H1/L1 bipartite null for V1 or a network statistic. A new method,
threshold, reference population or experimental-to-active promotion is critical.

Operational actions within existing contracts continue without another `procedi`.
Every scientific increment still requires tests before production, source freeze,
observed execution evidence and its named verifier before PASS. On a failed
provenance/scientific gate preserve everything, diagnose and request direction;
never bypass a pin, tune after outcomes, reset failure or invent an observed exit.
