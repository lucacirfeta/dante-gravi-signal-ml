import os
import torch
import torch.nn.functional as F
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from PIL import Image
from torchvision import transforms

# gwpy silently lowers the requested upper frequency when the Q range cannot
# support it: asking for (20, 2048) with qrange=(4, 64) over a 32 s window
# yields an axis that actually stops at ~1291 Hz, and only a UserWarning says
# so. Every patch-row -> Hz conversion must use the EFFECTIVE range or it
# overestimates frequency by +12% at the bottom and +57% at the top.
REQUESTED_FRANGE = (20.0, 2048.0)
EFFECTIVE_FRANGE = (20.0, 1291.0)

def generate_saliency_map(
    spectrogram_matrix: np.ndarray,
    output_path_prefix: str,
    model,
    background_vector: np.ndarray | None = None,
    k_highlight: int = 68,
    device: str = 'cuda',
    segment_length: float = 32.0,
    frange: tuple[float, float] = EFFECTIVE_FRANGE,
    scorer=None,
) -> dict:
    """
    Generates a 3-panel Topological Saliency Map of a candidate spectrogram.

    ``scorer`` should be a :class:`~src.core.patch_scorer.PatchScorer`. **Pass it
    for any figure that will be published.** With it, the highlighted patches
    are the production Top-$k$ -- the ones actually pooled into the novelty
    score -- because the scoring is delegated to the same code path. Without it
    the function falls back to a session-local spatial background, which ranks
    patches differently; that fallback is a diagnostic only and its panels must
    never be captioned as showing "the Top-k patches".

    ``background_vector`` is needed only by that fallback, so it may be omitted
    whenever a ``scorer`` is supplied.

    ``segment_length`` and ``frange`` exist only to label the axes in physical
    units. Before 2026-07-21 the panels were drawn with ``extent=[0, w, 0, h]``
    -- raw pixel indices -- while the y-axis was labelled "Frequency (Hz)", so a
    feature at pixel row 220 read as "220 Hz" when it actually sits near
    1150 Hz. Pass the *effective* frange, not the requested one (see
    EFFECTIVE_FRANGE).
    """
    # 1. (Rimosso il caricamento dell'indice VQ globale per disaccoppiamento architetturale)

    # 2. Extract patch tokens
    # Generate RGB image from raw spectrogram matrix matching patch-production
    cmap = plt.get_cmap("cividis")
    rgb_spectrogram = cmap(spectrogram_matrix)[:, :, :3]
    rgb_spectrogram_uint8 = (rgb_spectrogram * 255).astype(np.uint8)
    
    img = Image.fromarray(rgb_spectrogram_uint8).convert("RGB")
    
    transform = transforms.Compose([
        transforms.Resize((518, 518)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225]
        ),
    ])
    tensor = transform(img).unsqueeze(0).to(device)

    with torch.inference_mode():
        features = model.forward_features(tensor)
        patch_tokens = features['x_norm_patchtokens'].squeeze(0) # (1369, 384)

    # Normalizzazione L2 ESPLICITA obbligatoria
    patch_tokens = F.normalize(patch_tokens, p=2, dim=-1)

    # 3. Anomaly score per patch.
    #
    # When a production `scorer` is supplied we delegate to it, so the patches
    # highlighted here are *by construction* the same ones the pipeline pooled
    # to produce the candidate's novelty score: distance to the nearest centroid
    # of the frozen VQ dictionary.
    #
    # The `background_vector` branch below is a DIFFERENT quantity -- distance
    # to a position-matched median of session-local background. It ranks patches
    # differently, so a figure drawn from it must not be captioned as showing
    # "the Top-k patches". That mislabelling reached a published figure; see
    # CORRECTIONS_2026-07-21.md.
    if scorer is not None:
        res = scorer.score_spectrogram([rgb_spectrogram_uint8], threshold=0.0)[0]
        anomaly_score_np = np.asarray(res["patch_anomaly_scores"], dtype=np.float32)
        production_top_k = np.asarray(res["top_k_indices"], dtype=np.int64).ravel()
        score_source = "VQ dictionary (production)"
    else:
        if background_vector is None:
            raise ValueError(
                "generate_saliency_map needs either a production `scorer` "
                "(preferred) or a `background_vector` for the diagnostic fallback."
            )
        bg_vec_tensor = torch.tensor(background_vector, dtype=torch.float32, device=device) # (1369, 384)
        bg_vec_tensor = F.normalize(bg_vec_tensor, p=2, dim=-1)
        cos_sim_bg = torch.sum(patch_tokens * bg_vec_tensor, dim=1) # (1369,)
        anomaly_score_np = (1.0 - cos_sim_bg).cpu().numpy()
        production_top_k = None
        score_source = "session-local spatial background (NOT the production score)"

    # 4. Rimappatura spaziale 37x37
    grid = anomaly_score_np.reshape(37, 37)

    # 5. Upsampling bilineare to strict dimensions
    h, w = spectrogram_matrix.shape
    grid_tensor = torch.tensor(grid, dtype=torch.float32).unsqueeze(0).unsqueeze(0) # (1,1,37,37)
    saliency_256_tensor = F.interpolate(
        grid_tensor,
        size=(h, w),
        mode='bilinear',
        align_corners=False
    )
    saliency_upsampled = saliency_256_tensor.squeeze().numpy() # (H, W)

    # Normalizzazione per visualizzazione
    saliency_min = saliency_upsampled.min()
    saliency_max = saliency_upsampled.max()
    saliency_norm = (saliency_upsampled - saliency_min) / (saliency_max - saliency_min + 1e-8)

    # Estrazione dei Top-K. With a production scorer we take ITS selection
    # verbatim rather than re-deriving it, so the boxes cannot drift from what
    # the pipeline actually pooled.
    if production_top_k is not None:
        top_k_indices = production_top_k
    else:
        top_k_indices = np.argsort(anomaly_score_np)[-k_highlight:][::-1]
    top_k_positions = [(int(idx // 37), int(idx % 37)) for idx in top_k_indices]
    
    max_anomaly_score = float(anomaly_score_np.max())
    mean_topk_score = float(np.mean(anomaly_score_np[top_k_indices]))

    # 6. Figura pubblicabile (3 pannelli)
    fig, axs = plt.subplots(1, 3, figsize=(11, 4), dpi=150)
    
    # AXIS ORDER. gwpy's Spectrogram.value is (n_times, n_frequencies) --
    # verified directly: a 32 s Q-transform gives shape (1000, 500) against
    # len(times) == 1000. The array reaches the encoder unchanged, so axis 0 is
    # TIME and axis 1 is FREQUENCY, and patch index p maps to
    # row = p // 37 = time, col = p % 37 = frequency.
    #
    # Both axes are 256 px after resizing, which is why the transposition here
    # went unnoticed until 2026-07-22: the panels were drawn straight from the
    # array, putting time on the vertical axis under a "Frequency (Hz)" label
    # and vice versa. Transpose for display so the figure reads conventionally.
    disp = spectrogram_matrix.T                 # (freq, time)
    n_f = disp.shape[0]
    extent = [0, segment_length, 0, n_f]
    f_lo, f_hi = frange

    def _pix_to_hz(pix: float) -> float:
        return f_lo * (f_hi / f_lo) ** (pix / n_f)

    y_rows = np.linspace(0, n_f, 6)
    y_labels = [f"{_pix_to_hz(r):.0f}" for r in y_rows]

    # Pannello 1
    axs[0].imshow(disp, extent=extent, origin='lower', aspect='auto', cmap='cividis')
    axs[0].set_title("Original Q-Transform")
    axs[0].set_xlabel("Time from window start (s)")
    axs[0].set_ylabel("Frequency (Hz, log-spaced)")
    axs[0].set_yticks(y_rows)
    axs[0].set_yticklabels(y_labels)
    axs[0].grid(False)

    # Pannello 2 - Saliency. grid is (time, freq) like the spectrogram, so it
    # transposes the same way.
    axs[1].imshow(grid.T, extent=extent, origin='lower', cmap='hot', aspect='auto')
    axs[1].set_title("Patch anomaly score\n[" + score_source + "]", fontsize=9)
    axs[1].grid(False)

    # Sovrapponi griglia 37x37: dx along time, dy along frequency.
    dx = segment_length / 37.0
    dy = n_f / 37.0
    for x in range(38):
        axs[1].axhline(x * dy, color='white', alpha=0.15, linewidth=0.5)
        axs[1].axvline(x * dx, color='white', alpha=0.15, linewidth=0.5)

    # Evidenzia i top-k_highlight patch. (r, c) = (time cell, frequency cell),
    # so r drives x and c drives y.
    for (r, c) in top_k_positions:
        rect = patches.Rectangle((r * dx, c * dy), dx, dy, linewidth=1.5, edgecolor='red', facecolor='none')
        axs[1].add_patch(rect)

    axs[1].set_xlabel("Time from window start (s)")
    axs[1].set_yticks([])

    # Pannello 3 - Overlay combinato
    im1 = axs[2].imshow(disp, extent=extent, origin='lower', aspect='auto', cmap='cividis')
    im2 = axs[2].imshow(saliency_norm.T, extent=extent, origin='lower', aspect='auto', cmap='RdYlGn_r', alpha=0.55)
    axs[2].set_title("Anomaly Saliency Overlay")
    axs[2].set_xlabel("Time from window start (s)")
    axs[2].set_yticks([])
    axs[2].grid(False)
    
    cbar = fig.colorbar(im2, ax=axs[2], fraction=0.046, pad=0.04)
    cbar.set_label("Anomaly Score")

    plt.tight_layout()

    # Salva
    os.makedirs(os.path.dirname(output_path_prefix), exist_ok=True)
    plt.savefig(f"{output_path_prefix}_saliency.png", bbox_inches='tight', pad_inches=0.1, dpi=150)
    plt.savefig(f"{output_path_prefix}_saliency.pdf", bbox_inches='tight', pad_inches=0.1, dpi=150)
    plt.close(fig)

    # 7. Output dict
    return {
        'anomaly_scores': anomaly_score_np,
        'saliency_2d': grid,
        'top_k_indices': top_k_indices,
        'top_k_positions': top_k_positions,
        'score_source': score_source,
        'top_k_indices': np.asarray(top_k_indices, dtype=np.int32),
        'patch_anomaly_scores': anomaly_score_np,
        'max_anomaly_score': max_anomaly_score,
        'mean_topk_score': mean_topk_score,
    }
