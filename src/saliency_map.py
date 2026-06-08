import os
import torch
import torch.nn.functional as F
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from PIL import Image
from torchvision import transforms

def generate_saliency_map(
    spectrogram_path: str,
    background_vector: np.ndarray,
    output_path_prefix: str,
    model,
    k_highlight: int = 68,
    device: str = 'cuda',
) -> dict:
    """
    Generates a 3-panel Topological Saliency Map using purely spatial background distances.
    """
    # 1. (Rimosso il caricamento dell'indice VQ globale per disaccoppiamento architetturale)

    # 2. Extract patch tokens
    img = Image.open(spectrogram_path).convert("RGB")
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

    # 5. Upsampling bilineare a 256x256
    grid_tensor = torch.tensor(grid, dtype=torch.float32).unsqueeze(0).unsqueeze(0) # (1,1,37,37)
    saliency_256_tensor = F.interpolate(
        grid_tensor,
        size=(256, 256),
        mode='bilinear',
        align_corners=False
    )
    saliency_256 = saliency_256_tensor.squeeze().numpy() # (256, 256)

    # Normalizzazione per visualizzazione
    saliency_min = saliency_256.min()
    saliency_max = saliency_256.max()
    saliency_norm = (saliency_256 - saliency_min) / (saliency_max - saliency_min + 1e-8)

    # Estrazione dei Top-K
    top_k_indices = np.argsort(anomaly_score_np)[-k_highlight:][::-1]
    top_k_positions = [(int(idx // 37), int(idx % 37)) for idx in top_k_indices]
    
    max_anomaly_score = float(anomaly_score_np.max())
    mean_topk_score = float(np.mean(anomaly_score_np[top_k_indices]))

    # 6. Figura pubblicabile (3 pannelli)
    fig, axs = plt.subplots(1, 3, figsize=(11, 4), dpi=200)

    # Original PNG
    original_img = Image.open(spectrogram_path)

    # Pannello 1
    axs[0].imshow(original_img, cmap='cividis')
    axs[0].set_title("Original Q-Transform")
    axs[0].set_xlabel("Time samples")
    axs[0].set_ylabel("Frequency (Hz)")

    # Pannello 2 - Saliency (score_bg unicamente spaziale)
    grid_bg = score_bg_np.reshape(37, 37)
    axs[1].imshow(grid_bg, cmap='hot', aspect='auto')
    axs[1].set_title("Patch Saliency (Spatial Background)")
    # Sovrapponi griglia 37x37
    for x in range(38):
        axs[1].axhline(x - 0.5, color='white', alpha=0.15, linewidth=0.5)
        axs[1].axvline(x - 0.5, color='white', alpha=0.15, linewidth=0.5)
    
    # Evidenzia i top-k_highlight patch sulla heatmap spaziale
    for (r, c) in top_k_positions:
        rect = patches.Rectangle((c - 0.5, r - 0.5), 1, 1, linewidth=1.5, edgecolor='red', facecolor='none')
        axs[1].add_patch(rect)
        
    axs[1].set_xticks([])
    axs[1].set_yticks([])

    # Pannello 3 - Overlay combinato
    im1 = axs[2].imshow(original_img, cmap='cividis')
    im2 = axs[2].imshow(saliency_norm, cmap='RdYlGn_r', alpha=0.55)
    axs[2].set_title("Anomaly Saliency Overlay")
    axs[2].set_xticks([])
    axs[2].set_yticks([])
    
    cbar = fig.colorbar(im2, ax=axs[2], fraction=0.046, pad=0.04)
    cbar.set_label("Anomaly Score")

    plt.tight_layout()

    # Salva
    os.makedirs(os.path.dirname(output_path_prefix), exist_ok=True)
    plt.savefig(f"{output_path_prefix}_saliency.png", dpi=200, bbox_inches='tight')
    plt.savefig(f"{output_path_prefix}_saliency.pdf", bbox_inches='tight')
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
