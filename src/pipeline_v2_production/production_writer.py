import logging
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import h5py
import numpy as np

from src.core.utils import record_environment, setup_logger

logger = setup_logger(__name__)

class ProductionWriter:
    """Manages continuous, append-only persistence of novelties to HDF5."""
    
    def __init__(self, output_dir: str | Path, session_id: str, detector: str):
        self.session_id = session_id
        self.detector = detector
        self.output_dir = Path(output_dir) / session_id
        
        # Subdirectories
        self.checkpoints_dir = self.output_dir / "checkpoints"
        self.logs_dir = self.output_dir / "logs"
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        self.hdf5_path = self.output_dir / f"novelties_{self.session_id}_{self.detector}.h5"
        self.checkpoint_path = self.checkpoints_dir / f"last_gps_{self.session_id}_{self.detector}.txt"

        # The scores about to be written depend on the installed gwpy, which
        # supplies both the whitening and the Q-transform. Record the version
        # set alongside them so this session stays regenerable.
        record_environment(self.output_dir, f"scan_{self.session_id}_{self.detector}")
        
    def _init_hdf5(self, metadata: dict, background_scores: np.ndarray, threshold: float, background_gps: np.ndarray = None):
        """Initializes the HDF5 structure if it doesn't exist."""
        if not self.hdf5_path.exists():
            with h5py.File(self.hdf5_path, 'w', libver='latest') as f:
                # Metadata group
                meta_grp = f.create_group("metadata")
                for k, v in metadata.items():
                    if v is None:
                        meta_grp.attrs[k] = "None"
                    elif isinstance(v, (dict, list, tuple)):
                        import json
                        try:
                            meta_grp.attrs[k] = json.dumps(v)
                        except TypeError:
                            meta_grp.attrs[k] = str(v)
                    else:
                        meta_grp.attrs[k] = v
                
                # Background sample group
                bg_grp = f.create_group("background_sample")
                bg_grp.create_dataset("novelty_scores", data=background_scores, dtype='float32')
                if background_gps is not None:
                    bg_grp.create_dataset("gps_times", data=background_gps, dtype='float64')
                bg_grp.attrs["threshold"] = threshold
                bg_grp.attrs["calibration_timestamp"] = datetime.now(timezone.utc).isoformat()
                
                # Novelties group (resizable datasets)
                nov_grp = f.create_group("novelties")
                nov_grp.create_dataset("gps_times", shape=(0,), maxshape=(None,), dtype='float64', chunks=True)
                nov_grp.create_dataset("mil_vectors", shape=(0, 384), maxshape=(None, 384), dtype='float32', chunks=True)
                nov_grp.create_dataset("nov_scores", shape=(0,), maxshape=(None,), dtype='float32', chunks=True)
                nov_grp.create_dataset("top_k_idx", shape=(0, metadata.get('k', 68)), maxshape=(None, metadata.get('k', 68)), dtype='int32', chunks=True)
                
                # Use variable-length string dataset for serialized ablation dictionary
                dt_str = h5py.string_dtype(encoding='utf-8')
                nov_grp.create_dataset("ablation_k_scores", shape=(0,), maxshape=(None,), dtype=dt_str, chunks=True)

                processed = f.create_group("processed_windows")
                processed.attrs["schema_version"] = 1
                processed.attrs["window_length_s"] = 32.0
                processed.attrs["gps_semantics"] = "analysis_window_start"
                processed.attrs["detector"] = self.detector
                processed.create_dataset(
                    "gps_times",
                    shape=(0,),
                    maxshape=(None,),
                    dtype="float64",
                    chunks=True,
                )
                self._set_committed_state(f, 0, 0, None)
                
    def load_threshold(self):
        """Loads the threshold from existing HDF5 file if present."""
        if self.hdf5_path.exists():
            with h5py.File(self.hdf5_path, 'r') as f:
                if "background_sample" in f and "threshold" in f["background_sample"].attrs:
                    return float(f["background_sample"].attrs["threshold"])
        return None

    def verify_and_init(self, metadata: dict, background_scores: np.ndarray, threshold: float, background_gps: np.ndarray = None):
        """Checks index compatibility if resuming, or initializes a new file.

        A provenance mismatch is not corruption: it is a fail-closed request
        error and the existing HDF5 is left untouched.
        """
        is_corrupted = False
        if self.hdf5_path.exists():
            try:
                with h5py.File(self.hdf5_path, 'r') as f:
                    if "novelties" not in f or "metadata" not in f:
                        is_corrupted = True
                    else:
                        existing_sha256 = f["metadata"].attrs.get("reference_sha256")
                        requested_sha256 = metadata.get("reference_sha256")
                        if existing_sha256 is not None and requested_sha256 is not None:
                            if existing_sha256 != requested_sha256:
                                raise RuntimeError(
                                    "Cannot resume: existing HDF5 has reference "
                                    f"SHA-256 {existing_sha256}, but current is "
                                    f"{requested_sha256}"
                                )
                            logger.info(
                                "Verified existing HDF5 index SHA-256: %s",
                                existing_sha256,
                            )
                        else:
                            existing_md5 = f["metadata"].attrs.get("reference_md5")
                            requested_md5 = metadata.get("reference_md5")
                            if existing_md5 != requested_md5:
                                raise RuntimeError(
                                    "Cannot resume legacy HDF5: existing reference "
                                    f"MD5 {existing_md5}, current {requested_md5}"
                                )
                            logger.warning(
                                "Resume uses legacy MD5 provenance because the "
                                "existing HDF5 predates SHA-256 metadata: %s",
                                existing_md5,
                            )
            except RuntimeError:
                raise
            except (OSError, KeyError) as e:
                is_corrupted = True
                logger.warning(f"Failed to read HDF5: {e}")
                
            if is_corrupted:
                raise RuntimeError(
                    "Existing HDF5 is corrupted or incomplete; refusing to "
                    f"delete it automatically: {self.hdf5_path}"
                )
                
        if not self.hdf5_path.exists():
            self._init_hdf5(metadata, background_scores, threshold, background_gps)

        with h5py.File(self.hdf5_path, "a", libver="latest") as handle:
            self._ensure_writer_state(handle)
            self._recover_uncommitted(handle)

    @staticmethod
    def _novelty_datasets(group):
        names = (
            "gps_times",
            "mil_vectors",
            "nov_scores",
            "top_k_idx",
            "ablation_k_scores",
        )
        return [group[name] for name in names if name in group]

    def _ensure_processed_group(self, handle):
        group = handle.require_group("processed_windows")
        group.attrs["schema_version"] = 1
        group.attrs["window_length_s"] = 32.0
        group.attrs["gps_semantics"] = "analysis_window_start"
        group.attrs["detector"] = self.detector
        if "gps_times" not in group:
            group.create_dataset(
                "gps_times",
                shape=(0,),
                maxshape=(None,),
                dtype="float64",
                chunks=True,
            )
        return group

    def _set_committed_state(
        self,
        handle,
        novelty_rows: int,
        processed_rows: int,
        last_gps: float | None,
    ) -> None:
        handle.attrs["writer_commit_schema"] = 1
        handle.attrs["writer_committed_novelty_rows"] = int(novelty_rows)
        handle.attrs["writer_committed_processed_rows"] = int(processed_rows)
        handle.attrs["writer_committed_last_gps"] = (
            np.nan if last_gps is None else float(last_gps)
        )

    def _ensure_writer_state(self, handle) -> None:
        novelty = handle["novelties"]
        datasets = self._novelty_datasets(novelty)
        novelty_lengths = {dataset.shape[0] for dataset in datasets}
        if len(novelty_lengths) != 1:
            raise RuntimeError(
                "Novelty datasets have inconsistent lengths and no safe commit "
                f"boundary can be inferred: {sorted(novelty_lengths)}"
            )
        processed = self._ensure_processed_group(handle)["gps_times"]
        if "writer_commit_schema" not in handle.attrs:
            self._set_committed_state(
                handle,
                novelty_lengths.pop(),
                processed.shape[0],
                None,
            )
            handle.flush()
        if int(handle.attrs["writer_commit_schema"]) != 1:
            raise RuntimeError("Unsupported ProductionWriter commit schema")

    def _recover_uncommitted(self, handle) -> None:
        committed_novelty = int(handle.attrs["writer_committed_novelty_rows"])
        committed_processed = int(handle.attrs["writer_committed_processed_rows"])
        changed = False
        for dataset in self._novelty_datasets(handle["novelties"]):
            if dataset.shape[0] < committed_novelty:
                raise RuntimeError(
                    "Novelty dataset is shorter than its committed boundary"
                )
            if dataset.shape[0] > committed_novelty:
                dataset.resize(committed_novelty, axis=0)
                changed = True
        processed = self._ensure_processed_group(handle)["gps_times"]
        if processed.shape[0] < committed_processed:
            raise RuntimeError(
                "Processed-window ledger is shorter than its committed boundary"
            )
        if processed.shape[0] > committed_processed:
            processed.resize(committed_processed, axis=0)
            changed = True
        if changed:
            logger.warning("Recovered and removed an uncommitted HDF5 batch tail")
            handle.flush()

    def _after_data_flush(self) -> None:
        """Test fault-injection seam after data flush, before commit marker."""

    def _after_commit_flush(self) -> None:
        """Test fault-injection seam after commit marker, before checkpoint."""

    @staticmethod
    def _same_novelty(existing: dict, requested: dict) -> bool:
        return (
            float(existing["novelty_score"]) == float(requested["novelty_score"])
            and np.array_equal(existing["mil_vector"], requested["mil_vector"])
            and np.array_equal(existing["top_k_indices"], requested["top_k_indices"])
            and existing.get("ablation_k_scores", {})
            == requested.get("ablation_k_scores", {})
        )

    def append_batch(self, gps_starts, novel_records) -> None:
        """Commit one scored batch before its external checkpoint advances.

        ``novel_records`` contains ``(gps_start, full_result_dict)`` pairs.
        Replaying a committed batch is idempotent. A divergent replay for an
        existing novelty GPS fails closed instead of silently overwriting it.
        """
        processed_values = [float(value) for value in gps_starts]
        requested_novelties = [(float(gps), result) for gps, result in novel_records]
        if len({gps for gps, _ in requested_novelties}) != len(requested_novelties):
            raise ValueError("Duplicate novelty GPS within one append batch")
        if not processed_values and not requested_novelties:
            return

        with h5py.File(self.hdf5_path, "a", libver="latest") as handle:
            self._ensure_writer_state(handle)
            self._recover_uncommitted(handle)
            novelty = handle["novelties"]
            processed = self._ensure_processed_group(handle)["gps_times"]

            committed_novelty = int(handle.attrs["writer_committed_novelty_rows"])
            existing_gps = np.asarray(
                novelty["gps_times"][:committed_novelty], dtype=np.float64
            )
            existing_by_gps = {float(gps): index for index, gps in enumerate(existing_gps)}
            to_append = []
            for gps, result in requested_novelties:
                if gps not in existing_by_gps:
                    to_append.append((gps, result))
                    continue
                index = existing_by_gps[gps]
                stored_ablation = {}
                if "ablation_k_scores" in novelty:
                    value = novelty["ablation_k_scores"][index]
                    if isinstance(value, bytes):
                        value = value.decode("utf-8")
                    stored_ablation = json.loads(value)
                existing = {
                    "novelty_score": novelty["nov_scores"][index],
                    "mil_vector": novelty["mil_vectors"][index],
                    "top_k_indices": novelty["top_k_idx"][index],
                    "ablation_k_scores": stored_ablation,
                }
                if not self._same_novelty(existing, result):
                    raise RuntimeError(
                        f"Divergent novelty replay at detector/GPS "
                        f"{self.detector}/{gps}"
                    )

            if to_append:
                start = committed_novelty
                stop = start + len(to_append)
                for dataset in self._novelty_datasets(novelty):
                    dataset.resize(stop, axis=0)
                novelty["gps_times"][start:stop] = [gps for gps, _ in to_append]
                novelty["mil_vectors"][start:stop] = np.asarray(
                    [result["mil_vector"] for _, result in to_append],
                    dtype=np.float32,
                )
                novelty["nov_scores"][start:stop] = np.asarray(
                    [result["novelty_score"] for _, result in to_append],
                    dtype=np.float32,
                )
                novelty["top_k_idx"][start:stop] = np.asarray(
                    [result["top_k_indices"] for _, result in to_append],
                    dtype=np.int32,
                )
                if "ablation_k_scores" in novelty:
                    novelty["ablation_k_scores"][start:stop] = [
                        json.dumps(
                            result.get("ablation_k_scores", {}), sort_keys=True
                        )
                        for _, result in to_append
                    ]

            existing_processed = set(
                np.asarray(processed[:], dtype=np.float64).tolist()
            )
            new_processed = []
            for gps in processed_values:
                if gps not in existing_processed:
                    new_processed.append(gps)
                    existing_processed.add(gps)
            if new_processed:
                start = processed.shape[0]
                processed.resize(start + len(new_processed), axis=0)
                processed[start:] = np.asarray(new_processed, dtype=np.float64)

            handle.flush()
            self._after_data_flush()
            committed_novelty += len(to_append)
            committed_processed = processed.shape[0]
            last_gps = processed_values[-1] if processed_values else None
            self._set_committed_state(
                handle, committed_novelty, committed_processed, last_gps
            )
            handle.flush()
            self._after_commit_flush()
            
    def append_novel(self, gps_start: float, result_dict: dict):
        """Backward-compatible one-row wrapper around ``append_batch``."""
        self.append_batch([], [(gps_start, result_dict)])

    def append_processed(self, gps_starts) -> None:
        """Append analysis-window starts that completed scoring successfully.

        This ledger is distinct from the novelty table: coverage requires every
        processed window, including those classified as background. The dataset
        is append-only; readers de-duplicate GPS values to make crash/resume
        replay harmless.
        """
        self.append_batch(gps_starts, [])

    def save_checkpoint(self, gps_start: int):
        """Saves the last processed GPS to the checkpoint file."""
        temporary = self.checkpoint_path.with_suffix(
            self.checkpoint_path.suffix + ".tmp"
        )
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(str(gps_start))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.checkpoint_path)

    def load_checkpoint(self) -> int | None:
        """Loads the last processed GPS from the checkpoint file."""
        if self.checkpoint_path.exists():
            with open(self.checkpoint_path, "r") as f:
                content = f.read().strip()
                if content and content != "DONE":
                    return int(content)
        return None

    def mark_completed(self):
        """Marks the session as completely processed."""
        temporary = self.checkpoint_path.with_suffix(
            self.checkpoint_path.suffix + ".tmp"
        )
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write("DONE")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.checkpoint_path)

    def is_completed(self) -> bool:
        """Checks if the session is completely processed."""
        if self.checkpoint_path.exists():
            with open(self.checkpoint_path, "r") as f:
                content = f.read().strip()
                if content == "DONE":
                    return True
        return False
