import gc
import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from sklearn.cluster import MiniBatchKMeans
from tqdm import tqdm

from src.encoder import DINOv2Encoder
from src.utils import setup_logger

logger = setup_logger(__name__)

class PatchIndexBuilder:
    """Builds a compressed reference index at patch-level using Vector Quantization."""

    def __init__(self, device: str = "cuda"):
        if device == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA not available, falling back to CPU")
            device = "cpu"
        self.device = torch.device(device)
        self.encoder = DINOv2Encoder(device=self.device)

    def build_index(self, images_dir: Path, output_npz: Path) -> None:
        """
        Extracts patches for each class, compresses them using MiniBatchKMeans,
        and saves the global compressed index.
        """
        images_dir = Path(images_dir)
        output_npz = Path(output_npz)
        
        if not images_dir.exists() or not images_dir.is_dir():
            raise FileNotFoundError(f"Images directory not found: {images_dir}")

        # Raccogli le classi (sottocartelle)
        class_dirs = [d for d in images_dir.iterdir() if d.is_dir()]
        if not class_dirs:
            raise RuntimeError(f"No class subdirectories found in {images_dir}")

        all_centroids = []
        all_labels = []

        batch_size = self.encoder.batch_size

        for class_dir in sorted(class_dirs):
            class_name = class_dir.name
            image_paths = sorted(list(class_dir.glob("*.png")))
            if not image_paths:
                continue
                
            logger.info("Processing class '%s' with %d images...", class_name, len(image_paths))
            
            class_patches = []
            
            # Estrazione patch a batch
            for start in tqdm(range(0, len(image_paths), batch_size), desc=f"Extracting {class_name}"):
                batch_paths = image_paths[start: start + batch_size]
                
                # Load images
                tensors = []
                for p in batch_paths:
                    img = Image.open(p)
                    tensors.append(self.encoder.transform(img))
                
                tensors_gpu = torch.stack(tensors).to(self.device)
                
                with torch.inference_mode():
                    features = self.encoder.model.forward_features(tensors_gpu)
                    # Shape: (B, 1369, 384)
                    patch_tokens = features['x_norm_patchtokens']
                    # L2-normalize lungo l'ultima dimensione
                    patch_tokens = F.normalize(patch_tokens, p=2, dim=-1)
                    
                    # Move to CPU and reshape to (B * 1369, 384)
                    flat_patches = patch_tokens.view(-1, 384).cpu().numpy()
                    class_patches.append(flat_patches)
                
                del tensors_gpu
                del patch_tokens
                del features
            
            if not class_patches:
                continue
                
            n_images = len(image_paths)
            k_class = min(64, max(8, n_images // 2))
                
            # Concatenate all patches for the class
            X_class = np.vstack(class_patches) # Shape: (N_img * 1369, 384)
            logger.info("Class '%s' patches shape: %s", class_name, X_class.shape)
            
            # Vector Quantization con MiniBatchKMeans
            logger.info("Running MiniBatchKMeans (K=%d) on '%s'...", k_class, class_name)
            kmeans = MiniBatchKMeans(
                n_clusters=k_class,
                batch_size=2048,
                compute_labels=False,
                random_state=42,
                n_init="auto"
            )
            kmeans.fit(X_class)
            
            centroids = kmeans.cluster_centers_ # Shape: (64, 384)
            
            # Ri-normalizza in L2 i centroidi per le similarità coseno future
            centroids_tensor = torch.tensor(centroids, dtype=torch.float32)
            centroids_tensor = F.normalize(centroids_tensor, p=2, dim=-1)
            centroids_normalized = centroids_tensor.numpy()
            
            # Calcolo Reconstruction Error (Diagnostica)
            # max cosine similarity tra patch originali e i 64 centroidi
            chunk_size = 50000
            max_sims = []
            for i in range(0, len(X_class), chunk_size):
                chunk = X_class[i:i+chunk_size]
                sims = np.dot(chunk, centroids_normalized.T)
                max_sims.append(np.max(sims, axis=1))
                
            max_sims_all = np.concatenate(max_sims)
            
            # 95th percentile of the error (error = 1 - max_sim) is 1 - 5th percentile of max_sim
            percentile_95_error = 1.0 - np.percentile(max_sims_all, 5)
            
            logger.info("Classe %s: 95th Percentile Reconstruction Error = %.4f", class_name, percentile_95_error)
            
            if percentile_95_error > 0.20:
                logger.warning(
                    "[WARNING] Varianza strutturale alta per la classe '%s'. "
                    "Il 95° percentile dell'errore (%.4f) supera 0.20. La classe potrebbe richiedere K > %d.",
                    class_name, percentile_95_error, k_class
                )
            
            all_centroids.append(centroids_normalized)
            all_labels.extend([class_name] * k_class)
            
            # Garbage collection rigorosa prima della prossima classe
            del X_class
            del class_patches
            del kmeans
            del max_sims
            del max_sims_all
            gc.collect()
            torch.cuda.empty_cache()
            
        # -------------------------------------------------------------
        # Salvataggio finale
        # -------------------------------------------------------------
        if not all_centroids:
            logger.error("No valid centroids generated. Aborting save.")
            return
            
        final_embeddings = np.vstack(all_centroids)
        final_labels = np.array(all_labels, dtype=str)
        
        output_npz.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            output_npz,
            embeddings=final_embeddings,
            labels=final_labels
        )
        
        logger.info(
            "Patch-level index compressed and saved to %s", output_npz
        )
        logger.info(
            "Final index shape: %s (Embeddings), %s (Labels)",
            final_embeddings.shape, final_labels.shape
        )
