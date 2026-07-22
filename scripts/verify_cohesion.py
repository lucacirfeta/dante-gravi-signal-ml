import os
import sys
import json
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from pathlib import Path
from tqdm import tqdm

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.core.data_loader import fetch_strain_data
from src.core.preprocessor import whiten, bandpass, generate_qtransform
from src.core.patch_scorer import PatchScorer
from src.core.utils import setup_logger

logger = setup_logger(__name__)

def verify_cohesion():
    index_path = "data/reference/patch_compressed_index_o4a_ex.npz"
    scorer = PatchScorer(reference_index_path=index_path, verify_md5=False)
    
    logger.info("Re-extracting NEW MIL vectors for 82 candidates using O4a Native Index...")
    tax_df = pd.read_csv("data/production/aggregated/Master_Taxonomy_O4a.csv")
    
    new_mil_vectors = {}
    
    for i, row in tqdm(tax_df.iterrows(), total=len(tax_df), desc="Candidates"):
        det = row['detector']
        gps = row['gps_start']
        fam = row['global_family_id']
        cid = f"{gps}_{det}"
        
        try:
            cand_ts = fetch_strain_data(det, gps, gps + 32, cache_raw=True, local_only=True)
            cand_ts = whiten(cand_ts)
            cand_ts = bandpass(cand_ts)
            q_gram = generate_qtransform(cand_ts, output_size=(256, 256))
            q_gram_uint8 = (q_gram * 255).astype(np.uint8)
            if q_gram_uint8.ndim == 2:
                q_gram_rgb = np.stack([q_gram_uint8]*3, axis=-1)
            else:
                q_gram_rgb = q_gram_uint8
                
            res = scorer.score_spectrogram([q_gram_rgb], threshold=1.0)[0]
            new_mil_vectors[cid] = {
                "fam": fam,
                "vector": res["mil_vector"]
            }
        except Exception as e:
            logger.error(f"Failed to process candidate {gps} {det}: {e}")
            
    logger.info("Computing Mean Internal Similarity...")
    
    # Group by family
    families = {}
    for cid, data in new_mil_vectors.items():
        fam = data["fam"]
        if fam not in families:
            families[fam] = []
        families[fam].append(data["vector"])
        
    for fam in sorted(families.keys()):
        vectors = np.array(families[fam]) # (N, 384)
        n = vectors.shape[0]
        
        if n > 1:
            # Pairwise cosine similarity
            sim = np.dot(vectors, vectors.T)
            i_upper = np.triu_indices(n, k=1)
            mean_sim = np.mean(sim[i_upper])
            logger.info(f"{fam} (n={n}): Mean Internal Similarity = {mean_sim:.4f}")
        else:
            logger.info(f"{fam} (n={n}): Cannot compute pairwise similarity for a single vector.")
            
if __name__ == "__main__":
    verify_cohesion()
