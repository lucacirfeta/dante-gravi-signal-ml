import logging
from pathlib import Path
from datetime import datetime, timezone

import h5py
import numpy as np

from src.utils import setup_logger

logger = setup_logger(__name__)

class ProductionWriter:
    """Manages continuous, append-only persistence of novelties to HDF5."""
    
    def __init__(self, output_dir: str | Path, session_id: str, detector: str):
        self.output_dir = Path(output_dir)
        self.session_id = session_id
        self.detector = detector
        
        # Subdirectories
        self.checkpoints_dir = self.output_dir / "checkpoints"
        self.logs_dir = self.output_dir / "logs"
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        self.hdf5_path = self.output_dir / f"novelties_{self.session_id}_{self.detector}.h5"
        self.checkpoint_path = self.checkpoints_dir / f"last_gps_{self.session_id}_{self.detector}.txt"
        
    def _init_hdf5(self, metadata: dict, background_scores: np.ndarray, threshold: float):
        """Initializes the HDF5 structure if it doesn't exist."""
        if not self.hdf5_path.exists():
            with h5py.File(self.hdf5_path, 'w', libver='latest') as f:
                # Metadata group
                meta_grp = f.create_group("metadata")
                for k, v in metadata.items():
                    meta_grp.attrs[k] = v
                
                # Background sample group
                bg_grp = f.create_group("background_sample")
                bg_grp.create_dataset("novelty_scores", data=background_scores, dtype='float32')
                bg_grp.attrs["threshold"] = threshold
                bg_grp.attrs["calibration_timestamp"] = datetime.now(timezone.utc).isoformat()
                
                # Novelties group (resizable datasets)
                nov_grp = f.create_group("novelties")
                nov_grp.create_dataset("gps_times", shape=(0,), maxshape=(None,), dtype='float64', chunks=True)
                nov_grp.create_dataset("mil_vectors", shape=(0, 384), maxshape=(None, 384), dtype='float32', chunks=True)
                nov_grp.create_dataset("nov_scores", shape=(0,), maxshape=(None,), dtype='float32', chunks=True)
                nov_grp.create_dataset("top_k_idx", shape=(0, metadata.get('k', 68)), maxshape=(None, metadata.get('k', 68)), dtype='int32', chunks=True)
                
    def verify_and_init(self, metadata: dict, background_scores: np.ndarray, threshold: float):
        """Checks MD5 compatibility if resuming, or initializes new file."""
        if self.hdf5_path.exists():
            with h5py.File(self.hdf5_path, 'r') as f:
                existing_md5 = f["metadata"].attrs.get("reference_md5")
                if existing_md5 != metadata["reference_md5"]:
                    raise RuntimeError(f"Cannot resume: existing HDF5 has reference MD5 {existing_md5}, but current is {metadata['reference_md5']}")
                logger.info(f"Verified existing HDF5 index MD5: {existing_md5}")
        else:
            self._init_hdf5(metadata, background_scores, threshold)
            
    def append_novel(self, gps_start: float, result_dict: dict):
        """Appends a novel segment directly to the HDF5 file using SWMR."""
        # Open in append mode with SWMR enabled
        with h5py.File(self.hdf5_path, 'a', libver='latest') as f:
            f.swmr_mode = True
            nov_grp = f["novelties"]
            
            # Current size
            n_current = nov_grp["gps_times"].shape[0]
            n_new = n_current + 1
            
            # Resize
            nov_grp["gps_times"].resize(n_new, axis=0)
            nov_grp["mil_vectors"].resize(n_new, axis=0)
            nov_grp["nov_scores"].resize(n_new, axis=0)
            nov_grp["top_k_idx"].resize(n_new, axis=0)
            
            # Assign
            nov_grp["gps_times"][n_current] = gps_start
            nov_grp["mil_vectors"][n_current] = result_dict["mil_vector"]
            nov_grp["nov_scores"][n_current] = result_dict["novelty_score"]
            nov_grp["top_k_idx"][n_current] = result_dict["top_k_indices"]
            
            # Flush changes to disk
            f.flush()

    def save_checkpoint(self, gps_start: int):
        """Saves the last processed GPS to the checkpoint file."""
        with open(self.checkpoint_path, "w") as f:
            f.write(str(gps_start))

    def load_checkpoint(self) -> int | None:
        """Loads the last processed GPS from the checkpoint file."""
        if self.checkpoint_path.exists():
            with open(self.checkpoint_path, "r") as f:
                content = f.read().strip()
                if content:
                    return int(content)
        return None
