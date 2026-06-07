import logging
from pathlib import Path

import numpy as np
from gwpy.timeseries import TimeSeries
from tqdm import tqdm

from src.preprocessor import whiten, bandpass, generate_qtransform
from src.utils import setup_logger

logger = setup_logger(__name__)

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
        sample_rate: int = 4096
    ):
        self.data_dir = Path(data_dir)
        self.detector = detector
        self.segment_duration = segment_duration
        self.sample_rate = sample_rate
        
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")
            
        # We glob all HDF5 files matching the detector
        self.hdf5_files = sorted(list(self.data_dir.rglob(f"*{self.detector}*.hdf5")))
        if not self.hdf5_files:
            logger.warning(f"No HDF5 files found for detector {self.detector} in {self.data_dir}")
            
    def _read_channel_name(self, ts_dict) -> str:
        """Finds the correct strain channel name dynamically."""
        for key in ts_dict.keys():
            if "STRAIN" in key:
                return key
        # Fallback to the known naming scheme if no dict key was easily extractable
        return f"{self.detector}:GWOSC-16KHZ_R1_STRAIN"
            
    def __iter__(self):
        """Generates (gps_start, spectrogram_array) tuples."""
        skipped_nan = 0
        skipped_short = 0
        
        for file_path in self.hdf5_files:
            logger.debug(f"Reading file: {file_path}")
            try:
                # Load the full timeseries from HDF5
                # Note: gwpy uses a dict-like structure or reads the first TS if name is omitted, 
                # but we will rely on reading the standard GWOSC name format for the detector.
                channel_name = f"{self.detector}:GWOSC-16KHZ_R1_STRAIN"
                try:
                    ts_full = TimeSeries.read(file_path, name=channel_name)
                except Exception:
                    # Fallback to read all and find the strain
                    from gwpy.timeseries import TimeSeriesDict
                    ts_dict = TimeSeriesDict.read(file_path)
                    ch = self._read_channel_name(ts_dict)
                    ts_full = ts_dict[ch]
                
                # Resample if needed
                if ts_full.sample_rate.value != self.sample_rate:
                    ts_full = ts_full.resample(self.sample_rate)
                    
                start_time = ts_full.t0.value
                end_time = ts_full.t0.value + ts_full.duration.value
                
                # Chunk into 32-second segments
                current_start = start_time
                while current_start + self.segment_duration <= end_time:
                    current_end = current_start + self.segment_duration
                    
                    # Extract segment
                    ts_seg = ts_full.crop(current_start, current_end)
                    
                    # Quality checks
                    if not np.isfinite(ts_seg.value).all() or np.all(ts_seg.value == 0):
                        skipped_nan += 1
                        current_start += self.segment_duration
                        continue
                        
                    # Preprocess
                    try:
                        spectrogram = self.preprocess(ts_seg)
                        yield int(current_start), spectrogram
                    except Exception as e:
                        logger.warning(f"Preprocessing failed for GPS {current_start}: {e}")
                        skipped_short += 1
                        
                    current_start += self.segment_duration
                    
            except Exception as e:
                logger.error(f"Failed to read or process file {file_path}: {e}")
                
        logger.info(f"Iteration complete. Skipped {skipped_nan} NaN/Zero segments, {skipped_short} due to errors.")
                
    def preprocess(self, ts_seg: TimeSeries) -> np.ndarray:
        """Applies exact pipeline: Whiten -> Bandpass -> Q-Transform -> Output image."""
        # 1. Whitening
        ts_white = whiten(ts_seg)
        # 2. Bandpass
        ts_bp = bandpass(ts_white)
        # 3. Q-Transform + Cividis normalize (generates 256x256 image by default)
        # We don't save to path, we extract the raw numpy array representing the image
        spectrogram = generate_qtransform(ts_bp, save_path=None, cmap="cividis")
        
        # generate_qtransform returns a (256, 256) float array normalized [0, 1].
        # We must convert it to a 3-channel RGB image (256, 256, 3) to mimic the PNG load.
        import matplotlib.pyplot as plt
        cmap = plt.get_cmap("cividis")
        rgb_spectrogram = cmap(spectrogram)[:, :, :3] # shape (256, 256, 3), range [0, 1]
        
        # Convert to uint8 (0-255) to perfectly mimic PNG reading
        rgb_spectrogram_uint8 = (rgb_spectrogram * 255).astype(np.uint8)
        
        return rgb_spectrogram_uint8
