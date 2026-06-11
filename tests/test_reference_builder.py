import tarfile
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

from src.pipeline_v1_legacy.reference_builder import extract_from_tar, build_reference_index_from_paths

@pytest.fixture
def sample_metadata():
    return pd.DataFrame({
        "gravityspy_id": ["abc12345", "abc12345", "xyz67890", "id1", "id2", "id3", "id4", "id5"],
        "label": ["Blip", "Blip", "Scratchy", "Blip", "Blip", "Blip", "Blip", "Blip"],
        "sample_type": ["train", "train", "train", "train", "train", "train", "train", "train"],
        "ifo": ["H1", "H1", "L1", "H1", "H1", "H1", "H1", "H1"]
    })

def test_extract_from_tar_filters_duration(tmp_path, sample_metadata):
    tar_path = tmp_path / "test.tar.gz"
    output_dir = tmp_path / "output"
    
    with tarfile.open(tar_path, "w:gz") as tar:
        for fname in [
            "Blip/train/H1_abc12345_spectrogram_1.0.png",
            "Blip/train/H1_abc12345_spectrogram_0.5.png",
            "Scratchy/train/L1_xyz67890_spectrogram_1.0.png",
        ]:
            file_path = tmp_path / "dummy.png"
            file_path.write_bytes(b"dummy image data")
            tar.add(file_path, arcname=fname)
            
    paths, labels = extract_from_tar(
        tar_path=tar_path,
        output_dir=output_dir,
        metadata=sample_metadata,
        max_per_class=10,
        duration="1.0"
    )
    
    assert len(paths) == 2
    assert len(labels) == 2
    assert "0.5" not in [p.name for p in paths]
    assert "Blip" in labels
    assert "Scratchy" in labels

def test_extract_from_tar_max_per_class(tmp_path, sample_metadata):
    tar_path = tmp_path / "test2.tar.gz"
    output_dir = tmp_path / "output2"
    
    with tarfile.open(tar_path, "w:gz") as tar:
        for i in range(1, 6):
            fname = f"Blip/train/H1_id{i}_spectrogram_1.0.png"
            file_path = tmp_path / "dummy.png"
            file_path.write_bytes(b"dummy image data")
            tar.add(file_path, arcname=fname)
            
    paths, labels = extract_from_tar(
        tar_path=tar_path,
        output_dir=output_dir,
        metadata=sample_metadata,
        max_per_class=3,
        duration="1.0"
    )
    
    assert len(paths) == 3
    blip_count = sum(1 for l in labels if l == "Blip")
    assert blip_count == 3

def test_extract_from_tar_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        extract_from_tar(
            tar_path=Path("non_existent.tar.gz"),
            output_dir=Path("out"),
            metadata=pd.DataFrame()
        )

def test_build_reference_index_npz_format(tmp_path, monkeypatch):
    class MockEncoder:
        def __init__(self):
            pass
        def extract_batch(self, paths, batch_size):
            return np.zeros((3, 384), dtype=np.float32)

    monkeypatch.setattr("src.reference_builder.DINOv2Encoder", MockEncoder)
    
    # Mock skimage.io
    class MockIO:
        @staticmethod
        def imread(path):
            return np.zeros((600, 800, 3), dtype=np.uint8)
        @staticmethod
        def imsave(path, arr):
            pass
            
    monkeypatch.setattr("skimage.io.imread", MockIO.imread)
    monkeypatch.setattr("skimage.io.imsave", MockIO.imsave)

    output_path = tmp_path / "ref.npz"
    image_paths = [tmp_path / f"{i}.png" for i in range(3)]
    for p in image_paths:
        p.write_bytes(b"dummy")
        
    labels = ["A", "B", "C"]
    
    meta = build_reference_index_from_paths(
        image_paths=image_paths,
        labels=labels,
        output_path=output_path,
        batch_size=32
    )
    
    assert output_path.exists()
    assert output_path.with_suffix(".json").exists()
    
    data = np.load(output_path)
    assert "embeddings" in data
    assert "labels" in data
    assert "image_paths" in data
    
    assert data["embeddings"].shape == (3, 384)
    assert meta["n_samples"] == 3
    assert meta["n_classes"] == 3
