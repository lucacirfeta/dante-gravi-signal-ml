# DANTE reference artifact bundle

This bundle supplies the immutable dictionaries required by the canonical v6
scorer. It is separate from both the source-code release
(`10.5281/zenodo.21912589`) and the paper evidence bundle
(`10.5281/zenodo.21925453`), neither of which contains these NPZ files.

Contents:

- canonical O3b discovery dictionary: 275 centroids, legacy Q=[4,32];
- coherent O4a native DSD dictionary: 1,216 centroids, Q=[4,64];
- O4a background-time, build-environment and source-state provenance;
- the machine-readable per-index SHA-256 contract.

From a repository checkout, verify installed artifacts with:

```bash
python scripts/manage_reference_artifacts.py install-bundle /path/to/dante_reference_artifacts_v1.zip
python scripts/manage_reference_artifacts.py verify
```

The DINOv2 source and weights are not redistributed here. They are acquired
from the upstream pinned commit and public weight URL, then verified against
the independent hashes in `config/reference_artifacts.json`:

```bash
python scripts/manage_reference_artifacts.py acquire-model
```

This artifact enables exact scoring with the frozen dictionaries. It does not
redistribute GWOSC strain, PEM channels, credentials, or the complete O4a raw
corpus needed to rerun the historical scan from first principles.
