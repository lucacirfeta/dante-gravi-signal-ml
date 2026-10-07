# O4b metadata proposal - 7 October 2026

## Outcome and boundary

Metadata capture and independent accounting PASS. Scientific selection is
blocked at an explicit CW-injection-policy checkpoint; no strain or outcomes
were read, no reference/calibration/evaluation members selected, and no O4b
execution or active provider promotion occurred. The literal all-injection-free
draft inventory is not suitable for an H1 background population: only five
seconds of released H1 DATA pass every published NO-hardware-injection mask.

The author's daytime `procedi` authorized the explicit metadata-only next step
following final16kR1/official-run/DATA-floor/separate-injection/disjoint-role/
separateV1 recommendations. It did not authorize a CW exception, population
sizes/epochs, context/filter/null choices or scientific launch. The overnight
deadline has expired; this work uses new daytime authority. Monitor remains
PAUSED, as independently read from its persisted automation status this turn.

## Frozen request and actual collection

- Source freeze: `4bdb8b61e69ebcda49f735a60a4f76a043976081`.
- Request: `config/dante_o4b_metadata_proposal_v1.json`, SHA256
  `47cf5882cd2c669e2fb03c1150502007f0d01ac599081af6984916b6e37d9ff0`.
- Tool: `scripts/snapshot_dante_o4b_metadata_proposal.py`, raw SHA256
  `1051f4e73ed6a01bdce920826645433f48d623d8de7ed135b07f122a94a64f84`.
- Fresh archive: `E:\dante_cache\dante_workflow\o4b_metadata_proposal_20261007\snapshot_v1`.
- Dataset definition: `O4b_16KHZ_R1`, 16,384 Hz. Official observing bounds:
  `[1396796418,1422118818)`, excluding earlier released days. Source:
  [official release](https://gwosc.org/O4/O4b/).
- Timeline namespace is `O4b`, not the strain dataset name. The published
  [technical notes](https://gwosc.org/O4/o4_details/) describe equivalent
  4k/16k metadata bit definitions. This does NOT inspect or certify individual
  16k strain files, finite strain, window-grid or padded-context coverage.
- Once-only live command used Windows Python311, `--request` above and
  `--output` the fresh archive. Terminal session58049 returned actual OSexit0
  with all three detector duration rows. No retry, resume or second snapshot.
- Preserved request bytes, dataset bytes and42timeline JSON responses
  (14flags x3detectors), each URL/query-bound and SHA-recorded in proposal.json.
  Exclusive creation prevents existing snapshot mutation. On failure, owned
  partial files and traceback remain; there is no automatic cleanup/relaunch.
- Dataset SHA256:
  `7bac030eb7c96783a534f94236d2d097c6695622e521d3abee2e961b01a79c00`.
- Proposal SHA256:
  `5233f7567afaaa354115f2178f30da39e69b8af1ea55901d23e8dc795d7dfc0e`.
- Dataset-definition text includes its published `Release 1 (test run)` label;
  this is source metadata, not a scientific qualification claim.

## Full integer interval inventory

All values are seconds of half-open integer metadata intervals, not numbers
of analysis windows or admitted population members.

| Detector | DATA | DATA passing all five NO-injection masks | DATA passing the four non-CW NO masks |
| --- | ---: | ---: | ---: |
| H1 | 12,219,205 | 5 | 12,219,205 |
| L1 | 17,112,628 | 1,073,086 | 17,112,628 |
| V1 | 17,920,765 | 17,920,765 | 17,920,765 |

The final column is an independently computed **alternative metadata
inventory**, not a selected background population or approved CW waiver.
Within DATA, the NO_CW mask alone accounts for the all-mask reduction. All
other published DQ flags are retained with passing-DATA durations and
`used_as_veto:false`; no additional DQ exclusion was applied.

The [official hardware-injection notes](https://gwosc.org/O4/o4_inj/) state
that the released observing-time O4 data have no transient CBC, burst,
stochastic or detector-characterization hardware injections, while CW
injections occur in the LIGO instruments. Their lists can also mark times
outside publicly available DATA. This explains why full-range DETCHAR/STOCH
mask gaps do not remove released DATA here. The statement does not certify
individual strain samples, injection morphology or immunity of DANTE scores.
It also means released O4b transient hardware injections cannot be assumed
to supply a morphology-validation cohort; any separate validation design
needs its own approved input/protocol.

## Independent audit and regression evidence

Pre-capture WSL new30fixtures plus targeted existing profile/inputcoverage
regression: **110 passed in42.56s**, terminal81428 actual OSexit0, Ruff lint
and formatting PASS, Git diff check OS0. Initial29fixtures had passed1.11s
before addition of the end-to-end synthetic metadata fixture. These are not
the historical489scientific or100administrative suites.

Post-capture targeted metadata fixtures: **30 passed in1.17s**, actual OSexit0;
RuffPASS/diffcheckOS0. Script and request raw hashes remain identical to the
pre-capture freeze. No additional historical scientific suite was launched.

Independent read-only audit did not import producer interval helpers. It
performed an event sweep over **every interval endpoint**, checking exact
coverage for the candidate intersection and its DATA complement, each DQ
annotation, and both alternative inventories above. Raw-file SHA, all42
query identities/URLs/segment rows,43raw-file cardinality and request SHA
match. It observed terminalOS0 and:

```text
METADATA_AUDIT_PASS raw43/timeline42/exact_endpoint_sweep/all_DQ_annotations/no_execution
SOURCE_RAW_PIN_PASS=18
```

DATA partition complements are H1=12,219,200s, L1=16,039,542s, V1=0s;
candidate+complement equals DATA exactly in each detector. No sampling,
numeric tolerance, old score/threshold transplant or scientific replay was
used. All18historical raw scientific source pins remain exact. New code is
outside the production package; registry/source/method pins remain untouched.

`population_allocation:null`, `context_coverage_verified:false`,
`scientific_execution_ready:false`, `strain_files_inspected:0` and
`known_injection_morphologies_verified:false` remain explicit. Existing
untracked output/public_smoke and all historical failed/interrupted runs are
preserved. The author-stopped native verifier remains not PASS_VERIFIED.

## Required author choice

1. Recommended for discussion: keep CW state as an explicit annotation,
   rather than an unconditional time veto, while retaining DATA admission
   and separate transient-injection bookkeeping. This preserves an operating
   detector-noise population, **not an all-injection-free population**.
   Assess CW/line effects under a separately approved method/validation plan;
   do not silently notch, subtract signals or claim irrelevance to scoring.
2. Require all hardware-injection-free intervals. The current H1 availability
   is only5s, so this cannot support the intended substantial H1 populations.
   A different data scope or scientific design would require author approval.

No choice is implemented. After a decision, exact temporal allocation,
padding/disjointness, native16k filter qualification, detector-specific
reference/calibration/null and installed scientific boundary still precede
any O4b launch. V1 availability is not V1 method/null qualification and never
authorizes reuse of H1/L1 nulls.
