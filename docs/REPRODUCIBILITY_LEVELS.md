# DANTE reproducibility levels

DANTE exposes three different reproducibility targets. They must not be
described as interchangeable.

## R1 — Paper-evidence recomputation

The public evidence record [`10.5281/zenodo.21925453`](https://doi.org/10.5281/zenodo.21925453)
contains the final detector-aware tables, trial summaries, PEM null records,
figures, manuscript sources and fail-closed verifiers. It supports auditing and
recomputing the numerical claims made in the v6 papers. It does not rerun the
encoder or the historical O4a scan.

```bash
python scripts/build_paper_reproducibility_bundle.py --check
python scripts/verify_c2_bgv3_artifacts.py --stage all
python scripts/verify_cqg_validation_artifacts.py --stage all
```

## R2 — Exact canonical scoring

Exact score replay additionally requires:

1. the O3b and coherent O4a NPZ dictionaries in the reference artifact bundle;
2. DINOv2 source commit `7b187bd4df8efce2cbcbbb67bd01532c19bf4c9c`;
3. weights SHA-256 `f433177089a681826f849f194ece3bb48f4d63fb38d32fc837e3dc7a4e5641fb`;
4. the Q-transform/rendering and GPS-window contract recorded in the artifacts.

The code verifies every one of these inputs before scoring:

```bash
python scripts/manage_reference_artifacts.py acquire-model
python scripts/manage_reference_artifacts.py install-bundle /path/to/dante_reference_artifacts_v1.zip
python scripts/manage_reference_artifacts.py verify
```

The two existing software/evidence Zenodo records do not contain the NPZ
dictionaries. The separate versioned GitHub release asset URL and SHA-256 are
recorded in `config/reference_artifacts.json`. R2 is accepted only after the
clean-clone runner self-downloads that asset and the public replay verifier
passes. This was completed at code commit
`9669fab678ce08fd5eac818ea530cc1ba1591ae6`; the hashed supporting record is
`artifacts/dante_light/public_replay_validation_v1.json`. A maintainer can
rebuild a candidate with:

```bash
python scripts/manage_reference_artifacts.py build-bundle
python scripts/manage_reference_artifacts.py verify-bundle \
  paper_draft/v6_paper/release/dante_reference_artifacts_v1.zip
```

## R3 — Full strain-to-result rerun

R3 requires the public GWOSC strain corpus, the observing-run configuration,
substantial compute/storage, and—for PEM—the NDS2 client plus whatever channel
access is available to the user. Missing PEM software or unavailable channels
are fail-closed; they are never converted into physical non-coupling evidence.

The CPU lock/container are reference environments for installation and replay
tests. Historical paper artifacts remain governed by their adjacent
`environment_*.json` records, including the exact CUDA nightly used at the
time. Bitwise equality across arbitrary hardware is not promised; the stored
score and tolerance contracts define numerical reproduction.
