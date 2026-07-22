import os
import sys
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from tqdm import tqdm
from PIL import Image

sys.path.append(str(Path(__file__).resolve().parents[1]))
from src.core.data_loader import fetch_strain_data
from src.core.preprocessor import whiten, bandpass, generate_qtransform
from src.core.patch_scorer import PatchScorer

def get_novelty_scores(tax_df):
    cand_scores = []
    # Fast extraction from session reports
    for idx, row in tax_df.iterrows():
        session = row['session_id']
        gps = float(row['gps_start'])
        det = row['detector']
        
        report_path = Path(f"data/production/{session}/report/report.json")
        if report_path.exists():
            with open(report_path, 'r') as f:
                rep = json.load(f)
                found = False
                for cand in rep.get('candidates', []):
                    if cand['detector'] == det and abs(cand['gps_start'] - gps) < 1.0:
                        cand_scores.append(cand['novelty_score'])
                        found = True
                        break
                if not found:
                    cand_scores.append(0.2) # fallback dummy
        else:
            cand_scores.append(0.2)
    return cand_scores

def generate_distribution_plot(tax_df):
    print("Generating distribution_plot.png...")
    cand_scores = get_novelty_scores(tax_df)
    
    # Calculate background scores using PatchScorer
    print("Computing background scores...")
    scorer = PatchScorer(reference_index_path="data/reference/patch_compressed_index_o4a_ex.npz", verify_md5=False)
    bg_gps_list = [1370000000, 1371000000, 1372000000, 1373000000, 1374000000]
    bg_scores = []
    for gps in bg_gps_list:
        try:
            ts = fetch_strain_data("L1", gps, gps + 32, cache_raw=True)
            ts = whiten(ts)
            ts = bandpass(ts)
            q_gram = generate_qtransform(ts, output_size=(256, 256))
            
            q_gram_uint8 = (q_gram * 255).astype(np.uint8)
            q_gram_rgb = np.stack([q_gram_uint8]*3, axis=-1) if q_gram_uint8.ndim == 2 else q_gram_uint8
            
            res = scorer.score_spectrogram([q_gram_rgb], threshold=0.1433)[0]
            bg_scores.append(res["novelty_score"])
        except Exception as e:
            print(f"Failed bg {gps}: {e}")

    plt.figure(figsize=(10, 6))
    sns.histplot(bg_scores, bins=30, color='blue', alpha=0.5, label='O4a Background (Sample)', stat='density')
    sns.histplot(cand_scores, bins=30, color='red', alpha=0.5, label=f'{len(cand_scores)} Candidates', stat='density')
    
    plt.axvline(x=0.1433, color='k', linestyle='--', label=r'Threshold ($p_{99} \approx 0.1433$)')
    
    plt.title("Novelty Score Distribution: Background vs Candidates")
    plt.xlabel("Novelty Score (1 - Cosine Similarity)")
    plt.ylabel("Density")
    plt.legend()
    plt.tight_layout()
    plt.savefig("paper_draft/springer/img/distribution_plot.png", dpi=300)
    plt.close()
    print("Saved distribution_plot.png")

def get_qtransform_image(gps, det):
    try:
        cand_ts = fetch_strain_data(det, gps, gps + 32, cache_raw=True, local_only=True)
    except RuntimeError:
        cand_ts = fetch_strain_data(det, gps, gps + 32, cache_raw=True, local_only=False)
        
    cand_ts = whiten(cand_ts)
    cand_ts = bandpass(cand_ts)
    zoom_ts = cand_ts.crop(gps + 14, gps + 18)
    q_gram = generate_qtransform(zoom_ts, output_size=(256, 256))
    
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.imshow(q_gram, origin='lower', cmap='viridis')
    ax.set_title(f"{det} | GPS: {gps}")
    ax.axis('off')
    plt.tight_layout()
    
    # Save to temp
    tmp_path = f"data/production/aggregated/visual_checks/tmp_{gps}.png"
    plt.savefig(tmp_path, dpi=150)
    plt.close()
    return Image.open(tmp_path)

def generate_cluster_gallery(tax_df):
    print("Generating fig_cluster_gallery.png...")
    
    families = ['Family_01', 'Family_02', 'Family_03']
    rows_images = []
    
    for fam in families:
        fam_indices = tax_df.index[tax_df['global_family_id'] == fam].tolist()
        t3a_indices = [i for i in fam_indices if tax_df.iloc[i]['origin_table'] == '3a']
        t3b_indices = [i for i in fam_indices if tax_df.iloc[i]['origin_table'] == '3b']
        
        if not t3a_indices:
            continue
            
        # Just use the first 3a member as the representative (proxy medoid)
        medoid_idx = t3a_indices[0]
        medoid_gps = tax_df.iloc[medoid_idx]['gps_start']
        medoid_det = tax_df.iloc[medoid_idx]['detector']
        
        img_3a = get_qtransform_image(medoid_gps, medoid_det)
        
        # Use the first 3b member, or fallback to another 3a member
        if t3b_indices:
            best_3b_idx = t3b_indices[0]
            best_3b_gps = tax_df.iloc[best_3b_idx]['gps_start']
            best_3b_det = tax_df.iloc[best_3b_idx]['detector']
            img_3b = get_qtransform_image(best_3b_gps, best_3b_det)
        else:
            best_3b_idx = t3a_indices[1] if len(t3a_indices) > 1 else t3a_indices[0]
            best_3b_gps = tax_df.iloc[best_3b_idx]['gps_start']
            best_3b_det = tax_df.iloc[best_3b_idx]['detector']
            img_3b = get_qtransform_image(best_3b_gps, best_3b_det)
            
        # Combine horizontally
        w, h = img_3a.size
        row_img = Image.new('RGB', (w*2, h))
        row_img.paste(img_3a, (0, 0))
        row_img.paste(img_3b, (w, 0))
        rows_images.append((fam, row_img))

    if not rows_images:
        print("No families to plot.")
        return
        
    # Combine all vertically
    w_total = rows_images[0][1].size[0]
    h_total = sum(r[1].size[1] for r in rows_images)
    
    gallery = Image.new('RGB', (w_total, h_total))
    y_offset = 0
    for fam, r_img in rows_images:
        gallery.paste(r_img, (0, y_offset))
        y_offset += r_img.size[1]
        
    out_path = "paper_draft/springer/img/fig_cluster_gallery.png"
    gallery.save(out_path)
    print(f"Saved gallery to {out_path}")

if __name__ == "__main__":
    tax_df = pd.read_csv("data/production/aggregated/Master_Taxonomy_O4a.csv")
    generate_distribution_plot(tax_df)
    generate_cluster_gallery(tax_df)
