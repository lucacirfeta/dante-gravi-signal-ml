import os
import shutil
import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

@pytest.fixture(scope="session", autouse=True)
def test_env_vars():
    """Set environment variables for testing."""
    os.environ["PYTHONPATH"] = os.path.abspath(".")

@pytest.fixture
def temp_workspace(tmp_path):
    """
    Creates a temporary workspace mirroring the 'data' structure
    but entirely isolated.
    """
    workspace = tmp_path / "data_test"
    workspace.mkdir()
    
    raw_dir_o4a = workspace / "raw" / "o4a" / "1234567890"
    raw_dir_o4a.mkdir(parents=True)
    
    raw_dir_o3b = workspace / "raw" / "o3b" / "1234567890"
    raw_dir_o3b.mkdir(parents=True)
    
    ref_dir = workspace / "reference"
    ref_dir.mkdir(parents=True)
    
    prod_dir = workspace / "production"
    prod_dir.mkdir(parents=True)
    rng = np.random.default_rng(42)
    
    # 1. Create dummy HDF5 raw files (128 seconds of data, 4096 Hz)
    from gwpy.timeseries import TimeSeries
    ts = TimeSeries(rng.standard_normal(4096 * 128), sample_rate=4096, t0=1234567890, name="H1:GWOSC-4KHZ_R1_STRAIN")
    ts.write(raw_dir_o4a / "H1_1234567890_1234568018.hdf5", format="hdf5", overwrite=True)
    ts.write(raw_dir_o3b / "H1_1234567890_1234568018.hdf5", format="hdf5", overwrite=True)

    # Independent calibration block outside the candidate guard interval.
    ts_background = TimeSeries(
        rng.standard_normal(4096 * 256),
        sample_rate=4096,
        t0=1234570000,
        name="H1:GWOSC-4KHZ_R1_STRAIN",
    )
    ts_background.write(
        raw_dir_o4a / "H1_1234570000_1234570256.hdf5",
        format="hdf5",
        overwrite=True,
    )
    ts_background.write(
        raw_dir_o3b / "H1_1234570000_1234570256.hdf5",
        format="hdf5",
        overwrite=True,
    )
        
    # 2. Create dummy npz reference indices
    # Primary index
    primary_index = ref_dir / "patch_compressed_index_o3b.npz"
    np.savez(
        primary_index, 
        embeddings=rng.standard_normal((10, 384)).astype(np.float32),
        labels=np.array(["Blip"] * 5 + ["Tomte"] * 5)
    )
    
    # Native index for domain shift
    for run in ["o4a", "o3b"]:
        native_index = ref_dir / f"patch_compressed_index_{run}_ex.npz"
        np.savez(
            native_index, 
            embeddings=rng.standard_normal((10, 384)).astype(np.float32),
            labels=np.array(["Blip"] * 5 + ["Tomte"] * 5),
            meta=json.dumps({
                "schema_version": 2,
                "run": run,
                "qrange": [4, 64],
                "colormap": "cividis",
            }),
        )
        native_index.with_suffix(".t_bg.json").write_text(
            json.dumps([1234580000.0]),
            encoding="utf-8",
        )

    # Per-index trust anchors used by the real PatchScorer constructors in
    # integration tests.  This mirrors config/reference_artifacts.json while
    # remaining fully hermetic.
    import hashlib
    def _sha256(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = workspace / "reference_artifacts.json"
    release_models = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "config"
            / "reference_artifacts.json"
        ).read_text(encoding="utf-8")
    )["models"]
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact_root": ".",
                "models": release_models,
                "reference_indices": {
                    "fixture_o3b": {
                        "path": "reference/patch_compressed_index_o3b.npz",
                        "sha256": _sha256(primary_index),
                        "embedding_dim": 384,
                        "n_centroids": 10,
                        "qrange": [4, 32],
                    },
                    **{
                        f"fixture_native_{run}": {
                            "path": f"reference/patch_compressed_index_{run}_ex.npz",
                            "sha256": _sha256(
                                ref_dir / f"patch_compressed_index_{run}_ex.npz"
                            ),
                            "embedding_dim": 384,
                            "n_centroids": 10,
                            "qrange": [4, 64],
                        }
                        for run in ("o4a", "o3b")
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Keep production-report morphcheck offline and hermetic.
    pd.DataFrame(
        {
            "event_time": pd.Series(dtype=float),
            "ml_label": pd.Series(dtype=str),
        }
    ).to_csv(ref_dir / "gs_classifications_O3b_H1.csv", index=False)
    
    # Hermeticity: point the production code at the MOCK reference dir.
    # Without this, tests silently pick up the real data/reference indices
    # (K=275 / K=1216) from the repo checkout — the old non-hermetic
    # test_pipeline_end_to_end[O4a] failure mode.
    old_ref = os.environ.get("DANTE_REFERENCE_DIR")
    old_manifest = os.environ.get("DANTE_ARTIFACT_MANIFEST")
    os.environ["DANTE_REFERENCE_DIR"] = str(ref_dir)
    os.environ["DANTE_ARTIFACT_MANIFEST"] = str(manifest)

    yield workspace

    # Teardown
    if old_ref is None:
        os.environ.pop("DANTE_REFERENCE_DIR", None)
    else:
        os.environ["DANTE_REFERENCE_DIR"] = old_ref
    if old_manifest is None:
        os.environ.pop("DANTE_ARTIFACT_MANIFEST", None)
    else:
        os.environ["DANTE_ARTIFACT_MANIFEST"] = old_manifest
    shutil.rmtree(workspace, ignore_errors=True)
