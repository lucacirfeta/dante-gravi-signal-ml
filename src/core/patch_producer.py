import logging
from pathlib import Path

import numpy as np
from gwpy.timeseries import TimeSeries
from tqdm import tqdm

from src.core.preprocessor import whiten, bandpass, generate_qtransform
from src.core.utils import setup_logger

logger = setup_logger(__name__)

def _worker_preprocess(ts_value: np.ndarray, t0: float, dt: float, name: str, seg_start: float, seg_end: float) -> tuple[int, np.ndarray]:
    """Module-level function for multiprocessing. 
    Applies Whiten Context -> Q-Transform -> Image conversion.
    """
    try:
        from gwpy.timeseries import TimeSeries
        import matplotlib.pyplot as plt
        import warnings
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ts_context = TimeSeries(ts_value, t0=t0, dt=dt, name=name)
            
            from src.core.preprocessor import whiten_context, extract_clean_subwindow
            # 1. Whitening & Bandpass with context
            ts_w_context, _ = whiten_context(ts_context, seg_start, seg_end, pad=4.0)
            
            # 2. Extract strictly the target segment
            ts_clean = extract_clean_subwindow(ts_w_context, seg_start, seg_end)
            
            # 3. Q-Transform + Cividis normalize
            spectrogram = generate_qtransform(ts_clean, save_path=None, cmap="cividis")
            
            cmap = plt.get_cmap("cividis")
            rgb_spectrogram = cmap(spectrogram)[:, :, :3]
            rgb_spectrogram_uint8 = (rgb_spectrogram * 255).astype(np.uint8)
            
            return int(t0), rgb_spectrogram_uint8
    except Exception as e:
        return int(t0), None

class PatchProducer:
    """CPU-bound Data Producer for Patch-Level production pipeline.
    
    Reads raw HDF5 files directly from disk, chunks them into 32-second segments,
    and applies the exact preprocessing pipeline: 
    Whitening -> Bandpass -> Q-Transform -> Cividis colormap -> (256, 256, 3) Numpy array.
    """
    def __init__(
        self, 
        data_dir: str | Path, 
        detector: str, 
        segment_duration: float = 32.0,
        sample_rate: int = 4096,
        workers: int = 8,
        batch_size: int = 32
    ):
        self.data_dir = Path(data_dir)
        self.detector = detector
        self.segment_duration = segment_duration
        self.sample_rate = sample_rate
        self.workers = workers
        self.batch_size = batch_size
        self.resume_gps = None
        
        from src.core.data_loader import _DATA_DIRECTORIES
        
        self.hdf5_files = []
        if self.data_dir.exists():
            self.hdf5_files.extend(list(self.data_dir.rglob(f"*{self.detector}*.hdf5")))
            
        if not self.hdf5_files:
            for d in _DATA_DIRECTORIES:
                if d.exists() and d != self.data_dir:
                    # Look for the specific session folder inside the global directory
                    fallback_dir = d / self.data_dir.name
                    if fallback_dir.exists() and fallback_dir.is_dir():
                        self.hdf5_files.extend(list(fallback_dir.rglob(f"*{self.detector}*.hdf5")))
                    elif not self.data_dir.name.isdigit():
                        # If the data_dir is not a session folder (e.g. processing 'ALL' sessions), fallback to the whole global directory
                        self.hdf5_files.extend(list(d.rglob(f"*{self.detector}*.hdf5")))
                
        self.hdf5_files = sorted(list(set(self.hdf5_files)))
        
        if not self.hdf5_files:
            error_msg = f"No HDF5 files found for detector {self.detector} in {self.data_dir} or configured external drives."
            logger.warning(error_msg)
            raise FileNotFoundError(error_msg)
            
    def _read_channel_name(self, ts_dict) -> str:
        """Finds the correct strain channel name dynamically."""
        for key in ts_dict.keys():
            if "STRAIN" in key.upper():
                return key
        # Fallback to the known naming scheme if no dict key was easily extractable
        return f"{self.detector}:GWOSC-16KHZ_R1_STRAIN"
            
    def __iter__(self):
        """Generates (gps_starts, spectrogram_arrays) batched tuples."""
        skipped_nan = 0
        skipped_short = 0
        
        import concurrent.futures
        import multiprocessing as mp
        
        ctx = mp.get_context('spawn')
        with concurrent.futures.ProcessPoolExecutor(max_workers=self.workers, mp_context=ctx) as executor:
            futures = []
            
            gps_batch = []
            img_batch = []
            
            for file_path in self.hdf5_files:
                if self.resume_gps is not None:
                    # Skip entire file if it ends before or exactly at resume_gps
                    import os
                    basename = os.path.basename(file_path).replace(".hdf5", "")
                    parts = basename.split('_')
                    if len(parts) >= 3:
                        try:
                            file_end = float(parts[-1])
                            if file_end <= self.resume_gps:
                                logger.debug(f"Skipping already processed file: {file_path}")
                                continue
                        except ValueError:
                            pass
                
                logger.debug(f"Reading file: {file_path}")
                try:
                    channel_name = f"{self.detector}:GWOSC-16KHZ_R1_STRAIN"
                    try:
                        ts_full = TimeSeries.read(file_path, name=channel_name)
                    except Exception:
                        from gwpy.timeseries import TimeSeriesDict
                        ts_dict = TimeSeriesDict.read(file_path)
                        ch = self._read_channel_name(ts_dict)
                        ts_full = ts_dict[ch]
                    
                    if ts_full.sample_rate.value != self.sample_rate:
                        ts_full = ts_full.resample(self.sample_rate)
                        
                    start_time = ts_full.t0.value
                    end_time = ts_full.t0.value + ts_full.duration.value
                    
                    current_start = start_time
                    while current_start + self.segment_duration <= end_time:
                        if self.resume_gps is not None and current_start <= self.resume_gps:
                            current_start += self.segment_duration
                            continue
                            
                        current_end = current_start + self.segment_duration
                        
                        pad = 4.0
                        crop_start = max(start_time, current_start - pad)
                        crop_end = min(end_time, current_end + pad)
                        ts_context = ts_full.crop(crop_start, crop_end)
                        
                        ts_target = ts_full.crop(current_start, current_end)
                        if not np.isfinite(ts_target.value).all() or np.all(ts_target.value == 0):
                            skipped_nan += 1
                            current_start += self.segment_duration
                            continue
                            
                        # Inietta nel pool di processi
                        future = executor.submit(
                            _worker_preprocess,
                            ts_context.value,
                            ts_context.t0.value,
                            ts_context.dt.value,
                            ts_context.name,
                            current_start,
                            current_end
                        )
                        futures.append(future)
                        
                        # Yield if buffer is full enough to maintain a batch
                        while len(futures) >= self.workers * 2 and len(futures) >= self.batch_size:
                            completed_future = futures.pop(0)
                            gps, spec = completed_future.result()
                            if spec is not None:
                                gps_batch.append(gps)
                                img_batch.append(spec)
                                
                                if len(gps_batch) == self.batch_size:
                                    yield gps_batch, img_batch
                                    gps_batch = []
                                    img_batch = []
                            else:
                                skipped_short += 1
                                
                        current_start += self.segment_duration
                        
                except Exception as e:
                    logger.error(f"Failed to read or process file {file_path}: {e}")
                    
                    # Auto-heal: sposta il file corrotto per escluderlo dai futuri run
                    err_str = str(e).lower()
                    if "synchronously read data" in err_str or "filter returned failure" in err_str or "unable to open file" in err_str:
                        try:
                            import shutil
                            # Riconoscimento dinamico del mount point (WSL "/mnt/e/" o Windows "E:/")
                            if len(file_path.parts) >= 4:
                                base_mount = file_path.parents[2] # Es. /mnt/e/ oppure E:/
                                run_name = file_path.parent.parent.name # Es. o4a
                                session_name = file_path.parent.name    # Es. 1386598912
                                corrupt_dir = base_mount / "corrupt" / run_name / session_name
                            else:
                                # Fallback sicuro per path corti (es. data/raw/file.hdf5)
                                corrupt_dir = file_path.parent / ".corrupt"
                                
                            corrupt_dir.mkdir(parents=True, exist_ok=True)
                            
                            corrupt_path = corrupt_dir / file_path.name
                            shutil.move(str(file_path), str(corrupt_path))
                            logger.warning(f"[AUTO-HEAL] File corrotto spostato in {corrupt_path}")
                        except Exception as ren_e:
                            logger.error(f"Impossibile spostare il file corrotto: {ren_e}")
                    
            # Svuota i rimanenti futures (Garantendo sempre l'ordine FIFO)
            for future in futures:
                gps, spec = future.result()
                if spec is not None:
                    gps_batch.append(gps)
                    img_batch.append(spec)
                    
                    if len(gps_batch) == self.batch_size:
                        yield gps_batch, img_batch
                        gps_batch = []
                        img_batch = []
                else:
                    skipped_short += 1
                    
            # Resa della batch finale incompleta (se presente)
            if len(gps_batch) > 0:
                yield gps_batch, img_batch

        logger.info(f"Iteration complete. Skipped {skipped_nan} NaN/Zero segments, {skipped_short} due to errors.")
