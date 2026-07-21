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
    background_vector: np.ndarray,
    output_path_prefix: str,
    model,
    k_highlight: int = 68,
    device: str = 'cuda',
    segment_length: float = 32.0,
    frange: tuple[float, float] = EFFECTIVE_FRANGE,
) -> dict:
    """
    Generates a 3-panel Topological Saliency Map using purely spatial background distances.

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

    # 3. Anomaly score per patch (doppia metrica)
    # background_vector ora è una matrice (1369, 384)
    bg_vec_tensor = torch.tensor(background_vector, dtype=torch.float32, device=device) # (1369, 384)
    bg_vec_tensor = F.normalize(bg_vec_tensor, p=2, dim=-1)

    # Metrica A - distanza dal background spaziale (calcolo puntuale 1-a-1)
    cos_sim_bg = torch.sum(patch_tokens * bg_vec_tensor, dim=1) # (1369,)
    score_bg = 1.0 - cos_sim_bg

    # Score combinato ORA E' ESCLUSIVAMENTE LO SCORE SPAZIALE
    anomaly_score = score_bg # (1369,)

    # Convert to numpy for downstream processing
    score_bg_np = score_bg.cpu().numpy()
    anomaly_score_np = anomaly_score.cpu().numpy()

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

    # Estrazione dei Top-K
    top_k_indices = np.argsort(anomaly_score_np)[-k_highlight:][::-1]
    top_k_positions = [(int(idx // 37), int(idx % 37)) for idx in top_k_indices]
    
    max_anomaly_score = float(anomaly_score_np.max())
    mean_topk_score = float(np.mean(anomaly_score_np[top_k_indices]))

    # 6. Figura pubblicabile (3 pannelli)
    fig, axs = plt.subplots(1, 3, figsize=(11, 4), dpi=150)
    
    # Time is linear across the window; frequency rows are LOG-spaced over the
    # effective frange, so the y axis is kept in pixel units and tick LABELS
    # carry the physical frequency. Using a linear Hz extent here would be the
    # very error this function used to make.
    extent = [0, segment_length, 0, h]
    f_lo, f_hi = frange

    def _row_to_hz(row: float) -> float:
        return f_lo * (f_hi / f_lo) ** (row / h)

    y_rows = np.linspace(0, h, 6)
    y_labels = [f"{_row_to_hz(r):.0f}" for r in y_rows]

    # Pannello 1
    axs[0].imshow(spectrogram_matrix, extent=extent, origin='lower', aspect='auto', cmap='cividis')
    axs[0].set_title("Original Q-Transform")
    axs[0].set_xlabel("Time from window start (s)")
    axs[0].set_ylabel("Frequency (Hz, log-spaced)")
    axs[0].set_yticks(y_rows)
    axs[0].set_yticklabels(y_labels)
    axs[0].grid(False)

    # Pannello 2 - Saliency (score_bg unicamente spaziale)
    grid_bg = score_bg_np.reshape(37, 37)
    axs[1].imshow(grid_bg, extent=extent, origin='lower', cmap='hot', aspect='auto')
    axs[1].set_title("Patch Saliency (Spatial Background)")
    axs[1].grid(False)
    
    # Sovrapponi griglia 37x37 (dx now in seconds, matching the new extent)
    dx = segment_length / 37.0
    dy = h / 37.0
    for x in range(38):
        axs[1].axhline(x * dy, color='white', alpha=0.15, linewidth=0.5)
        axs[1].axvline(x * dx, color='white', alpha=0.15, linewidth=0.5)
    
    # Evidenzia i top-k_highlight patch sulla heatmap spaziale
    for (r, c) in top_k_positions:
        # origin='lower' on a 37x37 matrix means row 0 is at bottom (y=0 to y=dy)
        # So r corresponds directly to the y grid cell. 
        rect = patches.Rectangle((c * dx, r * dy), dx, dy, linewidth=1.5, edgecolor='red', facecolor='none')
        axs[1].add_patch(rect)
        
    axs[1].set_xlabel("Time from window start (s)")
    axs[1].set_yticks([])

    # Pannello 3 - Overlay combinato
    im1 = axs[2].imshow(spectrogram_matrix, extent=extent, origin='lower', aspect='auto', cmap='cividis')
    im2 = axs[2].imshow(saliency_norm, extent=extent, origin='lower', aspect='auto', cmap='RdYlGn_r', alpha=0.55)
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
        'score_bg': score_bg_np,
        'max_anomaly_score': max_anomaly_score,
        'mean_topk_score': mean_topk_score,
    }
