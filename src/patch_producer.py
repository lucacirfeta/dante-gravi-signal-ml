import logging
from pathlib import Path

import numpy as np
from gwpy.timeseries import TimeSeries
from tqdm import tqdm

from src.preprocessor import whiten, bandpass, generate_qtransform
from src.utils import setup_logger

logger = setup_logger(__name__)

def _worker_preprocess(ts_value: np.ndarray, t0: float, dt: float, name: str) -> tuple[int, np.ndarray]:
    """Module-level function for multiprocessing. 
    Applies Whiten -> Bandpass -> Q-Transform -> Image conversion.
    """
    try:
        from gwpy.timeseries import TimeSeries
        import matplotlib.pyplot as plt
        import warnings
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ts_seg = TimeSeries(ts_value, t0=t0, dt=dt, name=name)
            
            # 1. Whitening
            ts_white = whiten(ts_seg)
            # 2. Bandpass
            ts_bp = bandpass(ts_white)
            # 3. Q-Transform + Cividis normalize
            spectrogram = generate_qtransform(ts_bp, save_path=None, cmap="cividis")
            
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
        
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")
            
        # We glob all HDF5 files matching the detector
        self.hdf5_files = sorted(list(self.data_dir.rglob(f"*{self.detector}*.hdf5")))
        if not self.hdf5_files:
            logger.warning(f"No HDF5 files found for detector {self.detector} in {self.data_dir}")
            
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
                        current_end = current_start + self.segment_duration
                        
                        ts_seg = ts_full.crop(current_start, current_end)
                        
                        if not np.isfinite(ts_seg.value).all() or np.all(ts_seg.value == 0):
                            skipped_nan += 1
                            current_start += self.segment_duration
                            continue
                            
                        # Inietta nel pool di processi (passiamo i valori base, non l'oggetto TS intero per evitare pickling overhead)
                        future = executor.submit(
                            _worker_preprocess,
                            ts_seg.value,
                            ts_seg.t0.value,
                            ts_seg.dt.value,
                            ts_seg.name
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
