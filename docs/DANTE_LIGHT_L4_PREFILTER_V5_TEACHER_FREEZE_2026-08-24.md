# DANTE-Light L4 prefilter v5 teacher freeze

Status: `FROZEN_TRAINING_ONLY`

## Decision

The sole teacher target is the continuous `native` O4a novelty score emitted
by the exact DANTE-Light routing path. The O3b `primary` score remains an audit
and localization reference in DANTE-Light, but it is not a v5 training target.
This choice was explicitly approved before any training teacher ledger was
built.

Training a surrogate against `primary` would optimize agreement with a
historical reference score rather than the score that decides operational
routing. A high fidelity result against that target would therefore not answer
the v5 question. The frozen target is instead
`native_o4a_novelty_score`, computed with the shared DINOv2 encoder and the
detector-aware O4a native index in `score_only` mode. No routing threshold is
applied when producing the continuous target.

## Boundary

- Only the 19,200 frozen O4a training-background identities may be scored.
- Development, confirmation and O4b identities are rejected before strain
  preparation.
- No morphology label enters the target or loss.
- The teacher is an existing pipeline decision score, not physical truth.
- Teacher generation does not authorize student training, development,
  confirmation, O4b evaluation or routing.

The exact contract is
`config/dante_light_prefilter_v5_teacher_contract.json`. Large target ledgers
and cached canonical whitened strain remain under the run-keyed
`DANTE_V5_CACHE_ROOT`; only the final compact manifest is intended for Git.
Changing the contract, split, representation, teacher implementation or ledger
builder changes the full cache key, and incompatible cached blocks are rejected.

## Verification

The implementation first writes a complete strain shard and teacher record for
each detector/GPS block. Each block is atomic and independently hash-checked,
so interruption is resumable without mixing results from different contracts.
The verifier recomputes the frozen training identities, validates all block and
strain-shard hashes, checks every float32 target representation and requires
empty development, confirmation and O4b access lists.

Commands:

```text
python scripts/freeze_dante_light_prefilter_v5_teacher.py
python scripts/build_dante_light_prefilter_v5_teacher_ledger.py --device cuda --workers 8
python scripts/verify_dante_light_prefilter_v5_teacher_ledger.py
python -m pytest tests/test_dante_light_prefilter_v5_teacher.py -q
```

The production run should set `DANTE_DATA_DIRS` to the local O4a raw mirror and
`DANTE_V5_CACHE_ROOT` to the E: cache. A limited run is explicitly labelled
`SMOKE_ONLY` and cannot create the complete repository manifest.
