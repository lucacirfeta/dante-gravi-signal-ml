## Current Position
- **Milestone**: O3a transfer readiness
- **Phase**: O3a diagnostic checkpoint closed; no downstream stage active
- **Localized L1 follow-up approved method (2026-09-30)**: Author approved the
  same-five-channel study AND its concrete numerical decision rule. The method uses the frozen one-second
  Top-k region, local Welch coherence and a two-target corrected reference-tail
  screen D <= 0.01; it makes no formal p-value/FWER claim. Synthetic/PEM/
  PatchProducer regression: 124 PASS, 11 upstream warnings; Ruff PASS.
  Metadata-only preflight finds at most 31 candidate-clean 96-second control
  blocks for GPS1238508320, versus 199 required; this design is INCONCLUSIVE
  there. GPS1241808544 has 437 before CAT2/3 checks. Existing comparative
  backgrounds are in different CAT1 segments. Gate C remains disabled.
  Method source freeze `775ca7e`; real outcome-blind matched-control input gate
  and separate offline verifier exited OS 0/PASS. Of the second target's
  437 candidate-clean blocks, 11 fail local BURST_CAT2/3 coverage and 426
  have complete DQ/five-channel metadata coverage. No event coverage gap.
  Run key `18a26a65`, zero failure/partial/lock. Regression 143 PASS,
  post-final-CLI targeted 19 PASS; 11 upstream warnings; Ruff PASS.
  Matched native sample transport and byte replay are now complete.
  A separate transport-only
  contract/adapter now preserves these 426 blocks in 53 adjacent-context
  containers (265 native auxiliary series), with five immutable historical
  event references and full-span strain replay. Targeted synthetic tests:
  25 PASS; full WSL regression 168 PASS, 11 upstream warnings; Ruff PASS.
  Source freeze `3a9303e`; plan exit OS 0, key `e55ae783`, 20 strain frames,
  54 strain spans, 265 native control series and five replayed historical
  event references. All 17 source hashes match, new sources Git-byte-identical.
  Acquisition exit OS 0 (recovered session 51240); standalone verifier exit
  OS 0 (session 34719), PASS_VERIFIED_MATCHED_NATIVE_SAMPLES_ONLY. Exact
  20 frame/54 strain receipts/265 native control files and receipts/five
  unchanged event references; zero failure/partial/lock, both stderr empty.
  Summary seal `4e4c0269`, file SHA `5f737268`; post-run 168 PASS, 11 upstream
  warnings, Ruff PASS. Git source audit: 16 byte matches, contracts.py exact
  LF->CRLF reconstruction unchanged. Monitor suspended after checkpoint.
  Next: fully tested/source-frozen local measurement adapter and verifier
  bound to this input receipt. Gate C remains closed; no local outcome read.
  See `docs/DANTE_O3A_L1_MATCHED_SAMPLES_2026-09-30.md`.
  The earlier metadata gate alone did not establish sample bytes; the new
  sample gate does establish local numerical integrity, not veto safety. See
  `docs/DANTE_O3A_L1_LOCAL_FOLLOWUP_GATE_B_2026-09-30.md`.
- **O3a diagnostic closure (2026-09-29)**: The frozen O3a scan,
  detector-aware native stages, classification, taxonomy, coincidence and
  O3a-only PEM are verified. The later five-common-channel O3a/O4a PEM
  comparison is also verified; it does not compare prevalence across the
  different target populations. L1 GPS 1238508320 and 1241808544 remain
  CAT2/3-clean descriptive residuals with NO_CORRELATION in the five tested
  public channels, not promoted candidates. Physical cause, localized timing
  and globally calibrated significance are not established. No new protocol
  is opened by this closure; O3b is outside its scope. See
  `docs/DANTE_O3A_DIAGNOSTIC_CLOSURE_2026-09-29.md`.
- **O3a/O4a common PEM verified diagnostic comparison (2026-09-29)**:
  Separate O3a and O4a runs completed under source freeze `d019d2d` and
  sealed plan `69e581fa`, with OS exit 0 and independent standalone verifier
  exit 0/PASS_VERIFIED for 12 and 65 event receipts respectively. Zero
  failure, partial files or locks; seven source hashes match. Post-run WSL
  regression: 106 passed, 11 upstream warnings; Ruff PASS. O3a primary:
  H1 one COUPLED/one NO_CORRELATION, L1 nine NO_CORRELATION; one H1 diagnostic
  NO_CORRELATION. O4a primary: H1 one COUPLED/one SUSPECT/one NO_CORRELATION,
  L1 two COUPLED/four NO_CORRELATION. O4a diagnostic: H1 two COUPLED/two
  SUSPECT/27 NO_CORRELATION, L1 one COUPLED/one SUSPECT/23 NO_CORRELATION.
  This is five-public-common-channel, diagnostic-only method parity over
  different frozen target sets, not prevalence, global significance or
  astrophysical inference. See
  `docs/DANTE_O3A_O4A_COMMON_PEM_RESULT_2026-09-29.md`.
- **O3a/O4a common PEM productive preflight prepared (2026-09-29)**: A
  separate-run, sealed-receipt runner is prepared under a versioned
  execution contract. It binds the historical event adapters, five-channel
  null core and verified local strain/auxiliary parents without retuning.
  Preflight requires full target/exclusion identity, live O3a CAT1 equality,
  O4a context replay and source freeze before outcomes. Synthetic and
  regression checks: 106 PASS, 11 upstream warnings; Ruff PASS. No real
  execution plan or paired PEM outcome is yet claimed. See
  `docs/DANTE_O3A_O4A_COMMON_PEM_EXECUTION_PREFLIGHT_2026-09-29.md`.
- **O3a/O4a common PEM background strain binding (2026-09-29)**: The
  public paired-measurement entry now accepts the sealed 77-span/325-frame
  parents as its only background strain transport. Exact target/interval,
  parent/source/receipt and numerical replay checks fail closed, with no
  frame-download fallback. Read-only real-source constructors bound a
  frozen span in each run; WSL regression: 102 PASS, 11 upstream warnings; Ruff
  lint/format PASS. This does not open the five-channel null or outcomes.
  See `docs/DANTE_O3A_O4A_COMMON_PEM_BACKGROUND_INPUT_BINDING_2026-09-29.md`.
- **O3a/O4a common PEM local auxiliary binding (2026-09-29)**: A versioned
  transport-only contract pins the verified 750-series native auxiliary
  parent. The comparative measurement entry point now accepts auxiliary
  samples only through a receipt-checked local reader; no NDS2 fallback.
  Read-only source checks bound all 77 target contexts to their exact five
  event plus five background intervals, and one real sample read preserved
  native float32 rate. WSL regression: 99 PASS, 11 upstream warnings;
  Ruff lint/format PASS. See
  `docs/DANTE_O3A_O4A_COMMON_PEM_AUX_INPUT_BINDING_2026-09-29.md`.
  The productive paired runner, five-channel null, outcomes and significance
  remain unopened pending the remaining gate-3 checks.
- **O3a/O4a common PEM auxiliary native samples (2026-09-28)**: The
  author approved a single exact NDS2 native-rate sample acquisition plus
  independent local-file numerical replay, not a second source fetch. The
  metadata parent is verified for all 77 targets. Source freeze `957d030`;
  pre-run WSL common-PEM/PatchProducer tests: 85 passed, 11 upstream warnings;
  Ruff PASS. Real plan exited 0 after parent metadata re-query with 750
  native series and run key
  `df2a8c05f158d491d577ecf80cebae0ac2ea61b9158c2ef61fb96bedf4081b11`.
  The sole acquisition exited 0 with sealed summary PASS_COMPLETE, 750
  receipts/files, zero failure/partial/lock. Standalone local replay exited 0
  with `PASS_VERIFIED_AUX_NATIVE_SAMPLES_ONLY`; post-run 85 tests and Ruff
  passed, source hashes match. This is not a second NDS2 fetch. No five-channel
  null, comparative outcome or significance is claimed. See
  `docs/DANTE_O3A_O4A_COMMON_PEM_AUX_SAMPLES_2026-09-28.md`.
- **O3a/O4a common PEM auxiliary metadata gate (2026-09-28)**: The
  source-frozen metadata-only gate `904d8f9` passed for all 77 frozen
  targets, checking exact five-channel NDS2 availability over each event
  and four-hour background interval. The single run exited 0 with 77
  sealed receipts; an independent live metadata replay exited 0 with
  `PASS_VERIFIED_AUX_METADATA_COVERAGE_ONLY`. Zero failure/partial/lock;
  source hashes match. Post-run WSL regression: 77 passed, 11 upstream
  warnings; Ruff PASS. No auxiliary samples, five-channel null or paired
  PEM outcomes are verified. See
  `docs/DANTE_O3A_O4A_COMMON_PEM_AUX_AVAILABILITY_2026-09-28.md`.
- **O3a/O4a common PEM full-span gate (2026-09-28)**: A separate
  no-download streaming producer, sealed 77-span runner, contract and tests
  were source-frozen in `97b30b2`. WSL O3a/O4a PEM/provenance suite: 72
  passed, 11 upstream warnings; Ruff lint/format PASS. The real plan passed
  with exit 0; its run key is
  `034102715295eec0a8937fb67233d7515933addeb98bee35fbe9d3aac3566c0d`.
  The run produced 12 O3a and 65 O4a sealed full-span strain receipts with
  summary PASS_COMPLETE. A second read-only standalone --stage verify
  returned exit 0/PASS_VERIFIED_BACKGROUND_SPANS_ONLY for all 77 spans;
  the first verifier also reported PASS but its OS exit code was not retained.
  Zero failure, partial files or lock; three plan source SHA-256s match.
  This closes background strain only: auxiliary receipts, PEM null and
  comparative outcomes remain unopened. See
  `docs/DANTE_O3A_O4A_COMMON_PEM_SPAN_REPLAY_2026-09-28.md`.
- **O3a/O4a common PEM background acquisition (2026-09-28)**: The v1
  transport-only run `5308cec1e4d935cdd5b7c93b4df60369e9814fc2a63fe0741c8208abb40edb9e`
  failed structurally after 14 frame receipts because its probe examined a
  frame-start second outside the selected span. The failure and run are
  preserved, not resumable. A separate v2 source/contract in commit `ad9373f`
  corrects only the deterministic probe location to the earliest one-second
  planned span overlap per frame; 43 targeted/common-PEM WSL tests pass (11
  upstream warnings). Its source-bound real plan passed with 47 O3a plus 278
  O4a frames under run key
  `7d21f9c38e8b29a5029d604528b78e1f5f7e30c48bf3870a414890dd7aa29e95`.
  The v2 controller completed with PASS_ACQUIRED_BACKGROUND_FRAME_BYTES_V2_ONLY;
  standalone --stage verify exited 0 with
  PASS_VERIFIED_BACKGROUND_FRAME_BYTES_V2_ONLY. Exactly 325 frame files and
  325 sealed receipts are present, with zero failure, partial files or lock.
  Post-run WSL PEM/provenance suite: 68 passed, 11 upstream warnings; Ruff
  lint and format pass. Plan source hashes match current bytes; tracked Git
  files are clean. No paired PEM outcome is open. Complete four-hour spans,
  auxiliary receipts, null and independent outcome replay remain pending. See
  `docs/DANTE_O3A_O4A_COMMON_PEM_BACKGROUND_ACQUISITION_2026-09-28.md`.
- **O3a native calibration selector and arXiv v3 follow-up (2026-09-27)**:
  The approved native-calibration amendment and frozen cohort use the
  corrected-O4a deterministic, evenly spaced complete-block selector with
  context fallback, not the hash-stratified selector used in O3a initial
  calibration. This is documented parity, not a new method change. The public
  arXiv:2606.25702 record is still v2; no minimal v3 draft was located in
  this project and no v3 is publicly submitted. Internal target: prepare a source-checked
  O4a-provenance v3 draft by 2026-09-29 18:00 Europe/Rome. External submission
  remains gated on author review and approval. The comparative PEM input
  contract and raw context replay are verified. A separate O4a event-strain
  adapter passed synthetic exact-numerical parity with the historical reader
  and fail-closed tests (combined targeted suite 38 passed, Ruff PASS), but
  the full paired measurement/null adapters and gate-3 tests are not yet
  verified or source-frozen; no comparative result has been run. A separate
  five-channel measurement draft now rejects incomplete event coverage,
  changed exclusions, missing channels and stale caches, and injects an
  explicit verified background-strain reader into the unchanged historical
  null core. A draft official-background reader validates published MD5,
  HDF5 geometry and numerical span hash without using unreceipted local
  strain. The latest combined O3a/O4a PEM provenance suite passed 68 tests
  (11 upstream warnings); Ruff lint and format pass. Live public O3a
  CBC_CAT1/BURST_CAT1 exactly matches the frozen DQ snapshot for H1
  (545 segments, 11,218,675 s) and L1 (535, 11,956,179 s). The background
  source contract pins the complete public manifests and release/channel
  metadata; frozen selector replay matched all 12 O3a and 65 O4a spans,
  covered gap-free by 47 and 278 unique official frames. This is read-only
  coverage, not a scientific outcome. Four bounded one-second real-frame
  probes (O3a/O4a × H1/L1) subsequently passed public MD5, metadata and
  independent numerical replay; no full background span has passed yet. Historical
  O3a 512 Hz auxiliary channels remain eligible under the corrected
  completeness gate. Real background bytes, auxiliary receipts and
  independent end-to-end replay remain open;
  no real comparative outcome has been opened.
- **O4a numerical-context replay verified (2026-09-27)**: The v2 run
  `raw_replay_fb2af10f4feff811cd624526444d6890c610e5bf5a1c23bc4fc4d25bd16eb457`
  is PASS_COMPLETE; independent WSL `--stage verify` exited 0 with
  PASS_VERIFIED for 64 official frames and all 65 historical 40-second
  contexts. Post-run 43 tests and Ruff passed. Historical local HDF5
  whole-file byte parity is not claimed. Adapter parity and gate-3 checks
  remain before any paired PEM result. See
  `docs/DANTE_O3A_O4A_PEM_RAW_CONTEXT_REPLAY_VERIFIED_2026-09-27.md`.
- **O3a/O4a raw replay URL correction (2026-09-27)**: The first v1 O4a
  acquisition stopped at HTTP 404 before verifying a frame; its zero-frame
  run is preserved. The author approved a URL-only v2. The versioned v2
  addendum digest is
  `76bf71c828afbc79da2864fa7f3d7dc8ea805057a6e4e8173b6c89634bbb203e`;
  its raw replay contract digest is
  `8d8708ce5a809ee3259dfff4d14222a67ecfac5d5b2f59fb2bcfbd2c81690df0`.
  Both required H1/L1 archive URL HEAD checks returned 200; 43 combined
  O3a/O4a/PEM/provenance tests passed. Full 65-target numerical replay
  remains pending.
  See `docs/DANTE_O3A_O4A_PEM_RAW_REPLAY_URL_CORRECTION_2026-09-27.md`.
- **O3a/O4a common-channel PEM input freeze (2026-09-27)**: The approved
  diagnostic comparison now has a versioned input contract digest
  `aa25cff27ea5af0884da16dd12d5fe579154fae5f835c88aa95d9e46df2b2f7a`.
  It independently replays 12 O3a/65 O4a target identities and the full
  8,900/10,942 run-specific candidate-exclusion populations; five public
  channels per detector and measurement parameters are parity-checked against
  frozen parents. WSL 32 targeted tests passed; raw-replay preflight maps
  65 contexts to 64 official frames, without opening strain or outcomes.
  See `docs/DANTE_O3A_O4A_COMMON_PEM_INPUT_FREEZE_2026-09-27.md`. The
  65-target numerical-context replay completed later on 2026-09-27 as noted
  above; paired PEM remains unopened.
- **O3a 12-target diagnostic closure (2026-09-27)**: Per-record crosswalk of
  frozen Top-k time, GWOSC CBC/BURST CAT2/3, Gravity Spy window/trigger time,
  local null and PEM is complete in the visual-review checkpoint. Eight of
  12 full windows contain BURST_CAT2/3 failures, but only three frozen 1-s
  Top-k subwindows overlap those failures; a fourth subwindow fails CBC_CAT2/3
  only. Both detector subwindows at GPS 1243231936 overlap BURST failures:
  strong mundane DQ warning, not retroactive veto or proof of shared cause.
  L1 1238508320 and L1 1241808544 are whole-window CAT2/3-clean and above
  their local null, with no verified causal explanation or nearby catalogued
  trigger for their Top-k features. A read-only comparison found them 38.20
  days apart in distinct CBC_CAT1 segments, with similar low-frequency arches
  and 33/68 shared patch-grid positions but no evidence of a shared L1
  instrumental state or cause. They remain descriptive residuals, not
  promoted candidates. Review closes diagnostically; any dedicated protocol
  is a new scientific choice for the author, not started here.
- **O3a public DQ and frozen-method audit (2026-09-27)**: Read-only inspection
  of original GWOSC HDF5 1-Hz masks found DATA/CBC_CAT1/BURST_CAT1 true
  throughout all 12 windows; eight have local BURST_CAT2/3 failures.
  Crucially, H1 and L1 both fail BURST_CAT2/3 around the GPS 1243231936
  impulse at +22.6 s; the loud L1 GPS 1239628448 impulse at +3 s is also
  inside a BURST_CAT2/3 failure. The latter's Top-k coordinates are
  arithmetically consistent: only three of 68 patches fall near +3 s,
  ranked 53/63/68, while the top ten are late. H1 GPS 1253581920 PEM
  coherence is full-window spectral, not time-localized to its arch.
  These are diagnostic annotations, not retrospective vetoes or new rules;
  details in the 12-target visual-review checkpoint.
- **O3a public Gravity Spy cross-check (2026-09-27)**: Original Zenodo O3a
  H1/L1 CSV files passed published size/MD5 checks. Exact 32-s window joins
  found 24 Omicron/Gravity Spy triggers in 10 of the 12 target records,
  including 17 Scattered_Light labels across six records. This is an
  external cataloguing of the same strain, not independent instrumental
  attribution or a DANTE patch label. The H1/L1 GPS 1243231936 records have
  nearby Omicron triggers with distinct Koi_Fish/Extremely_Loud ML labels;
  L1 GPS 1239628448 shows a confirmed time-location discrepancy between
  its loud visual impulse and frozen Top-k median. Details and caveats are
  in `docs/DANTE_O3A_TWELVE_TARGET_VISUAL_REVIEW_2026-09-27.md`.
- **O3a 12-target visual replay (2026-09-27)**: Eleven official O3a 4 kHz
  source frames, all 12 raw 40-s contexts and all 12 production Q-images
  replayed with exact frozen SHA-256 matches. Full-window and Top-k-centered
  contact sheets plus receipt are in `docs/o3a_visual_review/`; descriptive
  review is in `docs/DANTE_O3A_TWELVE_TARGET_VISUAL_REVIEW_2026-09-27.md`.
  Repeated low-frequency arches in several windows are visually compatible
  with scattered-light morphology but not identified as such; the H1/L1
  GPS 1243231936 pair shows two narrow structures, not proven one event.
  H1 GPS 1253581920 has PEM COUPLED peak at 390.5 Hz outside its frozen
  Top-k band 20-92.5 Hz, so the flag does not yet explain its low-frequency
  arch. L1 GPS 1239628448 has a dominant visible impulse far from its
  Top-k time localization; cause untested. Instrumental attribution,
  physically valid timing and independent significance remain open. No
  new class, threshold or candidate promotion was made.
- **O3a 12-target ledger review (2026-09-27)**: Read-only joins of the
  frozen classification, taxonomy, coincidence and PEM ledgers are complete
  with zero identity/score/context/threshold mismatch. Seven of 11 primary
  targets and the one diagnostic target also exceed their own per-event
  coincidence null; four primary targets only exceed the pooled diagnostic
  p99. H1/L1 each have a ROBUST seed in GPS window 1243231936, but their
  separately localized subwindows do not establish one physical transient.
  Three nearby L1 targets share a PEM background span. The full ledger and
  caveats are in `docs/DANTE_O3A_TWELVE_TARGET_LEDGER_REVIEW_2026-09-27.md`.
  An official GWOSC GPS-range query, positive-controlled on a known O3a
  event, returned no catalogued event inside any of the 11 distinct 32-s
  target windows; this is not a significance or no-signal claim.
  The visual review is now complete as recorded above; independent
  instrumental attribution remains open. No candidate was promoted and no
  new scientific rule was introduced.
- **O3a-only PEM verified (2026-09-27 Europe/Rome)**: The frozen run
  `75a40541a8122aceb35e3c68a723f6a75108b0f5cf9f14ca65529151e5e0eb3e`
  finished with `PASS_COMPLETE_O3A_NATIVE_PEM_V1`; standalone `--stage verify`
  exited 0 and produced `PASS_VERIFIED_O3A_NATIVE_PEM_V1`. All 12 targets
  were calibrated (11 ROBUST primary, one AMBIGUOUS diagnostic); all 8,900
  O3a classified seed identities remained in the background exclusion. The
  raw transient cache is empty and no failure file exists. Primary H1:
  one COUPLED, one NO_CORRELATION; primary L1: nine NO_CORRELATION;
  diagnostic H1: one NO_CORRELATION. The COUPLED H1 target is GPS 1253581920,
  with top tested channel H1:LSC-POP_A_LF_OUT_DQ. This is a diagnostic
  environmental-coupling result, not astrophysical confirmation or global
  significance. Compact artifact digest
  `263ed1744dc2dece021d8dd298ad5b5d5c3c8439f78258db4bc9368cc8471e03`.
  Post-run WSL suite: 194 passed, 11 upstream warnings; Ruff passed.
  The O4a comparative/provenance gate remains separate and unopened.
- **O3a-only PEM execution (2026-09-26)**: After source freeze commit
  `eb7f6d4`, the single WSL controller began `--stage run` under key
  `75a40541a8122aceb35e3c68a723f6a75108b0f5cf9f14ca65529151e5e0eb3e`
  at `E:\dante_cache\dante_light\o3a_native_v1`. Launcher PID 24796;
  process was alive with empty stderr at the first check. This historical
  launch record is superseded by the verified completion above. The hourly
  monitor is suspended after verification. Source commits remain on this
  branch only; no push to main.
- **O3a-only PEM source freeze (2026-09-26)**: Versioned contract digest
  `a7f4202ff8d85ffb46efdb456ebcb25cc1a14b27b30cea0a64ee7ab198d05a87`;
  parent-only preflight digest
  `02e36df7a1a6d5074c22ca1c4b93e827666dfa118eaafd42257633acbe843cc6`.
  Exactly 12 targets and all 8,900 exclusion identities are sealed; 11
  distinct raw frames total 1,427,071,982 source bytes. E: has ample free
  space. The adapter includes raw-context hash replay, NDS2 event-coherence
  measurement, a fresh O3a family-wise null and quiet zero-lag control,
  atomic event outputs, same-key resume, and a standalone structural verifier.
  Synthetic tests cover raw replay, calibration and tamper failure. Complete
  post-freeze WSL O3a/PatchProducer suite: 194 passed, 11 upstream warnings;
  Ruff PASS. This evidence predates the active run described above.
- **O3a-only PEM preflight (2026-09-26)**: The author prioritized an O3a-only
  diagnostic result before any O4a paired comparison. A separate candidate
  contract and input adapter select the 12 verified O3a coincidence
  threshold exceeders (11 ROBUST primary, 1 AMBIGUOUS diagnostic), joined to
  the full 8,900-row O3a classification ledger and its frozen raw-context
  source metadata. Input preflight PASS, no strain opened. The five public
  channels per detector are the previously audited subset; the event/null
  numerical method is checked against the versioned corrected-O4a contract,
  but no O4a scientific rows or thresholds are imported. WSL targeted
  O3a tests: 21 passed, 11 upstream warnings; Ruff passed at that initial
  checkpoint. This historical preflight note predates the verified O3a PEM
  run recorded above and the later O4a policy-gate resolution recorded below.
  The paired O4a comparison has not started.
- **Raw replay implementation checkpoint (2026-09-26)**: A new, separate
  O4a 4 kHz R1 raw-context replay adapter and contract map 65 historical
  targets (66 local pieces) to 64 official frames with gap-free coverage.
  Five targeted tests and one real-frame MD5/metadata/context check pass.
  The existing O4a PEM suite has four failures because four O3a-specific
  `.gitattributes` LF rules on this branch are not in the old reconciliation
  allowlist (no historical rule was removed). No bulk fetch or new PEM run
  was started. A wider 2026-09-27 WSL regression reproduced the same gate
  (6 failed, 11 passed); the exact four rules and decision boundary are in
  `docs/DANTE_O3A_O4A_PEM_PROVENANCE_POLICY_GATE_2026-09-27.md`. The author
  approved exactly those four additions on 2026-09-27; the updated WSL suite
  now has 18 pass, 0 fail, and the frozen reconciliation reference is
  unchanged. The separate 65-target raw-context replay and comparative PEM
  remain pending.
- **Raw provenance gate (2026-09-26)**: The first reacquired O4a L1 GWOSC
  frame reproduces the frozen 40-second numerical context hash, but its
  reserialized whole-file SHA-256 differs from the frozen local HDF5 receipt.
  The original byte-identical file has not been found in the obvious local
  checkout and E: archives; the raw cleanup manifest lists its removal.
  The author approved a new versioned, diagnostic-only source receipt and
  independent numerical-context equality for all historical O4a PEM targets,
  preserving the old receipt. The current frame is official O4a 4 kHz R1:
  its MD5 matches GWOSC's published list, but this does not prove historic
  whole-file equality or explain the mismatch. No comparative PEM run has
  started. See `07-20-PLAN.md` for exact gates and interpretation boundary.
- **PEM common-channel checkpoint (2026-09-26)**: The author approved a new
  O3a/O4a paired follow-up on the exact publicly common five channels per
  detector, not a nominally equal PEM label over unequal channel sets.
  Public O3a NDS2 inventory lacks 4/9 H1 and 2/7 L1 original O4a channels;
  physical nonexistence and a valid alias are not inferred. All 12 O3a
  targets have five-channel event-window coverage and a CAT1-clean 4-hour
  background block with complete five-channel NDS2 metadata coverage.
  O3a CBC_CAT1 and BURST_CAT1 public segment lists are exactly equal over
  the full run for both detectors. Historical O4a outputs show all five
  common channels available for its 65 targets, but its original
  family-wise null cannot be reused after removing channels. Details and
  execution gates are in `07-20-PLAN.md`. No new PEM measurement has run.
- **Status**: O3a coincidence v2 is PASS verified, without a global
  significance or astrophysical claim. All 6,408 frozen seed workloads
  (5,850 ROBUST primary; 558 AMBIGUOUS diagnostic) completed in 201 shards;
  cache is empty, zero current failures, and standalone `--verify` exited 0.
  Summary digest `79bb6d04efac92a1cebf44fea29bc140b0e3d1cda5e67c20e76c220446db5c5a`;
  compact digest `3c3b3a878ae50753ab8ba99a70acf9898c4ad9b138acde2fb4c9ad8d7116afc9`.
  Post-run WSL tests: 187 passed, 11 upstream warnings; Ruff passed.
  All 15 frozen source hashes match current bytes and reconstruct from Git
  (nine exact, six exact LF-to-CRLF), but clean-LF replay is not claimed.
  Primary: 4,607 measured, 1,243 partner-unavailable, 11 above the
  diagnostic pooled-null p99; diagnostic: 445 measured, 113 unavailable,
  one above that threshold. The p99 is computed from measured ROBUST
  per-seed null maxima only and is not a global false-alarm threshold.
  A separate public-channel/method-parity PEM preflight is next. The first
  O3a coincidence run is FAILED, not an adopted scientific stage.
  Its v1 run key is
  `713609d1605d2b2a0d2871829a2b91288ce6330510a296021b86977b3c6c4a53`;
  the sealed failure is a structural cache-cap ContractError after nine
  32-seed shards. The run directory and 8.65 GB transient raw cache are
  preserved on E:, with no final threshold or PEM shortlist. A metadata-only
  plan audit found v1 peak 90,116,154,146 bytes because ROBUST and
  AMBIGUOUS seeds were batched in separate chronological passes. The author
  approved v2 global chronology, preserving the same populations/method,
  with projected peak 5,293,641,251 bytes including the pre-pinned frame,
  below 8 GiB. Pre-freeze 187 WSL tests and Ruff passed. The v2 contract
  was frozen with digest
  `05565c848b08efda6d71b7acf434809f93e5db638d623ca994824d1e520d991a`;
  source-only preflight passed with digest
  `590242c981544aa09e623ab8931a98bf5ef0e95423b7714a72996a62963dc63d`.
  The separate v2 run key is
  `d42ab62e620f86a5b4c84852e74dff80bcf45ccd1beef39edcb5082979cd3e89`.
  Source freeze commit `3f310fd` was pushed before the v2 run. One Linux
  controller began measuring; the sealed cache plan passed at 5,293,641,251
  peak bytes, zero of 201 batches above cap. At 3,648/6,408 seed workloads,
  a GWOSC HTTP 502 transport failure was sealed as InfrastructureError
  (digest `1669a4b14e813ab3f2c6109feb71e3df28207ed6172b3f5771a071de0e52e3a6`).
  The runner verified and archived this failure, preserved all 114 shards,
  and resumed the same v2 run key from those shards. That controller then
  completed and standalone verification passed. The failed v1
  key will not resume. The author approved exact corrected-O4a physical-coincidence
  method parity for O3a on 2026-09-25. The statistical limitation of at most
  eight eligible within-seed shifts, an O3a-only pooled p99 over measured
  ROBUST seed maxima, uncertain tail precision, and diagnostic-only scope
  was preregistered before outcomes. Contract digest
  `d0734ae8e6a946d8d741211321f0dce7fc59acf53f76986564ba4a2956962ecf`;
  source-only preflight digest
  `1e8109c39b2f23d44a7da10ecbe26ba78690f28b318bdab1cdade2e05749c649`.
  Pre-run WSL suite: 185 passed, 11 upstream warnings; Ruff PASS. Source
  freeze `f79692b` was pushed before the failed v1 execution. No interim
  coincidence outcome is reported. The O3a-only native index and 10,000-row native-calibration
  identity ledger remain adopted and unchanged. The score-only v3 contract
  (`85028c59d55fbc95c9b2b056eb0e783dfbffb3b7f446feb1befd8c2e1ff2f20c`)
  has PASS manifest and real HDF5/CUDA preflight, including stitched context,
  raw-file and image SHA-256 replay. Its frozen workload is 18,900 rows and
  4,324 unique raw frames; these are workload counts, not scientific outcomes.
  The post-run WSL O3a/PatchProducer suite passed 103 tests (11 upstream
  deprecation warnings). Scoring is complete under run key
  `e9b75ee479f5fa6850accb2178d00fa752954519fe7db768629ef1422c4c27e0`.
  All 18,900 rows and 591 score shards are complete; the transient cache is
  empty. The runner reports PASS_VERIFIED and standalone --verify passed
  with exit code 0 on 2026-09-24. The score-replay gate is closed successfully.
  The summary artifact digest is
  `4b1eff34f618005a2b881e3dd29e4dc0b25f1c6e5b5b5d19a23c0a833245503a`.
  Three infrastructure failures (502, 503, connection timeout) were archived
  by the runner before same-key resumes. Rescore v1 and v2 are preserved as
  failed structural preflights with zero
  scientific score shards. Native classes and morphology taxonomy are now
  verified; no coincidence, PEM or astrophysical interpretation has been performed.
  All 15 frozen rescore source hashes match; six
  require an exact, verified LF-to-CRLF reconstruction from Git. A clean-LF
  checkout is not directly hash-equivalent; clean-clone replay remains a
  separate follow-up (see the 2026-09-23 read-only audit).
  The new native-threshold adapter is tested (19 targeted tests; 122 complete
  O3a/PatchProducer tests, 11 upstream warnings). Its contract is frozen as
  `10d6279a2b637309d3d955881cf0a3d2f450f6a66adfb9de9fd2613ea3b65c5c`.
  Source freeze committed and pushed as b87db6a before fitting. The --run
  worker started at 18:00 Europe/Rome on 2026-09-24, with one WSL instance
  observed and an empty stderr log. Run key:
  `1bd630e29eda34be625f6bbd325b60d114d7f4dc2508a8c09c81263127f35405`.
  Fit completed at 18:04:49 Europe/Rome with PASS_COMPLETE, no failure file
  and empty stderr. The launch did not persist its OS exit code; do not
  claim that code was observed. Summary digest:
  `30671367d022c1a935a446313ea65f4b0457f6b85b2cc8f2107e94055b1d1d79`.
  Independent --verify completed at 19:05:41; session 70020 returned exit0
  and deterministic replay matched. Compact artifact digest:
  `32890633207ebb91839131b972dc0ca18650ceb3fe18383fb9adee3bed6ce281`.
  Post-run WSL regression: 122 passed, 11 upstream warnings (86.74s).
  H1 p99=0.4057316654920578; CI width=0.008046090602874756 (1.983106%).
  L1 p99=0.41683934092521674; CI width=0.00732177317142485 (1.756498%).
  Exact 5000 point/4998 bootstrap rows and 294 blocks per detector;
  receipt, summary and frozen-source audit PASS. No post-hoc width cutoff.
  The earlier authorization covered CLASSIFY only. Later explicit
  authorizations covered O4a-method-parity TAXONOMY and, on 2026-09-25,
  diagnostic COINCIDENCE followed by exact-parity PEM subject to its own
  public-channel preflight. A2 promotion and external candidate communication
  remain closed.
  The classification adapter now has 33 passing targeted tests and 155
  passing full O3a/PatchProducer tests (11 upstream warnings, 99.32s).
  Contract digest:
  `9aaeff60fd078538355d724f4102b39886dca97fef7474d394e2ee4109f5f1a2`.
  No real classification outcome has been opened before this source freeze.
  Source committed/pushed as 03a38ab before execution; all three new source
  hashes match Git bytes exactly. --run completed at 20:15:30 Europe/Rome
  and standalone --verify at 20:20:13 on 2026-09-24.
  Run key: `5cedef7de1c036f49a2c33acfeaa64198a67b31bed1c1109c6b34004faf6c044`.
  Supervisor session 54398 returned CLASSIFY_RUN_EXIT_CODE=0 and
  CLASSIFY_VERIFY_EXIT_CODE=0 (retrieved at the 20:48 status check).
  Summary digest:
  `24bfce9f2b7661ab5c4c9193d5d1200a9416df6d1704d8b80eadd7b91636c4e2`.
  Verified compact:
  `65d67d4c4dac2ff53893d3d23b3f308e5008c436b684a4247c8e927b662de3ac`.
  Post-run WSL regression: 155 passed, 11 upstream warnings, 107.59s.
  All 8900 output rows independently checked against unchanged input fields,
  per-detector thresholds and expected labels; exact Git/source/file hashes
  and seals pass. No failure artifact; both stderr logs empty.
  H1: 2291 ROBUST, 263 AMBIGUOUS, 1070 BACKGROUND (3624 total).
  L1: 3559 ROBUST, 295 AMBIGUOUS, 1422 BACKGROUND (5276 total).
  Total: 5850 ROBUST, 558 AMBIGUOUS, 2492 BACKGROUND (8900 seeds).
  These classes are not global significance or astrophysical detections.
  Classification execution is complete; its monitor was suspended at that
  checkpoint. TAXONOMY source/contract freeze was committed in 76a3552 before
  real execution, including the pre-registered dominant-family expectation.
  Standalone --run and --verify exited 0 under run key
  `f475a46f829c9afd78994898f6be5f9499483e401152e0f5f148a11f00b0c629`.
  The verified compact receipt digest is
  `9f947eeca4d8609f2ae96659d6364cf6a303d4ab411121f74c84e4332e287b41`.
  All 8900 O3a rows retain their native scores/classes; taxonomy has one
  8899-member family and one singleton, confirming the pre-registered
  single-linkage chaining expectation. Independent row, vector-hash and graph
  connectivity checks passed; post-run WSL suite: 170 passed, 11 upstream
  warnings. This was the taxonomy completion checkpoint; COINCIDENCE source
  freeze and authorization are recorded above, with no outcomes opened yet.

## Preserved completed evidence
- Multiscale efficiency v2 phases 6.1-6.4 remain complete and independently
  verified. Their canonical run and artifact identities remain in the phase
  verification records and are not modified by O3a work.
- O3a uses fresh run-specific populations. O4a scientific rows and outputs
  are not imported.
