"""Shared machinery for the norm-leakage factorial experiment.

Everything that must be IDENTICAL across the 4 cells lives here:
segment sampling protocol, preprocessing, raw Q-gram computation,
normalization schemes, and DINOv2 patch-token extraction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.core.utils import setup_logger, normalize_spectrogram, normalize_spectrogram_fixed
from src.pipeline_v3_multiscale.sampling import respects_guard, GUARD_TIME_S

logger = setup_logger(__name__)

SCALES = [0.5, 1, 2, 4]
QRANGE = (4, 32)
OUTPUT_SIZE = (256, 256)
K_CLUSTERS = 275          # production value, empirically verified (audit B-5)
TOP_K = 68
DETECTOR = "L1"

RUN_WINDOWS = {
    # full run windows (GPS) — never sub-windows (audit M-4)
    "o3a": (1238166018, 1253977218),
    "o4a": (1368975618, 1389456018),
}

OUT_ROOT = Path("results/norm_leakage")


# ---------------------------------------------------------------------------
# Normalization schemes (the experimental factor B)
# ---------------------------------------------------------------------------

def get_normalizer(scheme: str, e_max: float | None = None):
    """B1 = per-image min-max (production); B2 = fixed clip [0, e_max]."""
    if scheme == "minmax":
        return normalize_spectrogram
    if scheme == "fixed":
        if e_max is None:
            e_max = load_frozen_emax()
        return lambda arr: normalize_spectrogram_fixed(arr, e_max)
    raise ValueError(f"Unknown normalization scheme: {scheme}")


def load_frozen_emax() -> float:
    """E_max is derived ONCE by pretest_max_ks.py (p99.9 of pooled per-image
    maxima across BOTH runs) and frozen to disk. Refusing to run without it
    prevents silently re-deriving it per run, which would reintroduce the
    very leakage the scheme is designed to remove."""
    path = OUT_ROOT / "frozen_emax.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing: run pretest_max_ks.py first (it freezes E_max)."
        )
    with open(path) as f:
        return float(json.load(f)["e_max"])


# ---------------------------------------------------------------------------
# Raw Q-gram (pre-normalization) — needed by the KS pretest and by scoring
# ---------------------------------------------------------------------------

def raw_qgram(ts, qrange=QRANGE, output_size=OUTPUT_SIZE) -> np.ndarray:
    """Q-transform -> resized 2-D array, WITHOUT normalization.

    Replicates generate_qtransform() up to (not including) the normalizer,
    so per-image maxima can be recorded and any scheme applied downstream.
    """
    from scipy.ndimage import zoom

    q_gram = ts.q_transform(qrange=qrange, frange=(20, 2048), logf=True, whiten=False)
    spec = np.array(q_gram.value, dtype=np.float64)
    factors = (output_size[0] / spec.shape[0], output_size[1] / spec.shape[1])
    return zoom(spec, factors, order=1)


def spectrogram_to_rgb(spec01: np.ndarray, cmap: str = "cividis") -> np.ndarray:
    """[0,1] array -> (H, W, 3) uint8 via the production colormap.

    Kept identical to the PNG path of generate_qtransform (colormap +
    8-bit quantization are part of the channel under test, not confounders)."""
    import matplotlib

    rgba = matplotlib.colormaps[cmap](np.clip(spec01, 0.0, 1.0))
    return (rgba[..., :3] * 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Segment supply — one protocol for both runs (audit confounder #2)
# ---------------------------------------------------------------------------

@dataclass
class CleanSegment:
    t_bg: float          # center GPS
    ts_whitened: object  # 32 s whitened+bandpassed TimeSeries around t_bg


def iter_clean_segments(run: str, detector: str, n: int, seed: int,
                        guard: float = GUARD_TIME_S):
    """Yield up to `n` vetoed clean 32 s segments from `run`.

    Identical protocol for both runs:
      GWOSC {DET}_DATA + {DET}_BURST_CAT1 over the FULL run window,
      guard-time >= 96 s between accepted centers (B-4),
      excess-power veto on the whitened 32 s window,
      whiten_context(pad=4) -> extract_clean_subwindow (single bandpass, B-1).

    Data source: fetch_strain_data resolves local HDF5 (E:/o4a mirrored at
    /mnt/e/o4a under WSL) before falling back to GWOSC download.
    """
    from gwosc.timeline import get_segments
    from tenacity import retry, wait_exponential, stop_after_attempt

    from src.core.data_loader import fetch_strain_data
    from src.core.preprocessor import whiten_context, extract_clean_subwindow
    from src.pipeline_v3_multiscale.micro_mdc_multiscale import excess_power_veto

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10),
           stop=stop_after_attempt(5))
    def _segs(flag, s, e):
        return get_segments(flag, s, e)

    lo, hi = RUN_WINDOWS[run]
    logger.info(f"[{run}] Fetching DQ segments over full window {lo}-{hi}...")
    burst = _segs(f"{detector}_BURST_CAT1", lo, hi)
    data = _segs(f"{detector}_DATA", lo, hi)

    rng = np.random.default_rng(seed)
    accepted: list[float] = []
    attempts = 0
    budget = n * 400
    while len(accepted) < n and attempts < budget:
        attempts += 1
        t_bg = float(rng.integers(lo + 64, hi - 64))
        if not respects_guard(t_bg, accepted, guard):
            continue
        w0, w1 = t_bg - 16, t_bg + 16
        if not any(s[0] <= w0 and s[1] >= w1 for s in burst):
            continue
        if not any(s[0] <= w0 and s[1] >= w1 for s in data):
            continue
        try:
            ts_super = fetch_strain_data(detector, w0 - 4.0, w1 + 4.0,
                                         cache_raw=True, edge_tolerance=4.0)
            ts_w_padded, _ = whiten_context(ts_super, w0, w1, pad=4.0)
            ts_bp = extract_clean_subwindow(ts_w_padded, w0, w1)
        except Exception as e:
            logger.debug(f"[{run}] fetch/whiten failed at {t_bg}: {e}")
            continue
        if np.any(~np.isfinite(ts_bp.value)):
            continue
        if excess_power_veto(ts_bp, sample_rate=4096):
            continue
        accepted.append(t_bg)
        yield CleanSegment(t_bg=t_bg, ts_whitened=ts_bp)
    if len(accepted) < n:
        logger.warning(f"[{run}] only {len(accepted)}/{n} segments found "
                       f"within attempt budget.")


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------

class PatchEncoder:
    """Frozen DINOv2 -> L2-normalized patch tokens (1369, 384)."""

    def __init__(self, device: str | None = None):
        import torch
        from src.core.encoder import build_dinov2_transform

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = torch.hub.load("facebookresearch/dinov2",
                                    "dinov2_vits14_reg").to(self.device)
        self.model.eval()
        for p in self.model.parameters():
            p.requires_grad = False
        self.transform = build_dinov2_transform()

    def encode_rgb(self, rgb: np.ndarray) -> np.ndarray:
        return self.encode_batch([rgb])[0]

    def encode_batch(self, rgbs: list[np.ndarray]) -> np.ndarray:
        """Batch encode: list of (H, W, 3) uint8 -> (B, 1369, 384) L2-normed."""
        from PIL import Image
        import torch.nn.functional as F

        tensors = self.torch.stack(
            [self.transform(Image.fromarray(r)) for r in rgbs]).to(self.device)
        with self.torch.inference_mode():
            feats = self.model.forward_features(tensors)
            tokens = F.normalize(feats["x_norm_patchtokens"], p=2, dim=-1)
        return tokens.cpu().numpy().astype(np.float32)


def topk_score(patch_tokens: np.ndarray, centroids: np.ndarray,
               k: int = TOP_K) -> float:
    """Production scoring rule: 1 - max cosine sim per patch, mean of top-k."""
    sims = patch_tokens @ centroids.T          # (1369, K)
    anomaly = 1.0 - sims.max(axis=1)           # (1369,)
    idx = np.argpartition(anomaly, -k)[-k:]
    return float(anomaly[idx].mean())
