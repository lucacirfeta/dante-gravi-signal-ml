import pandas as pd
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class Paper5DataLoader:
    def __init__(self, aggregated_dir: str = "data/production/aggregated"):
        self.aggregated_dir = Path(aggregated_dir)
        self.taxonomy_path = self.aggregated_dir / "Master_Taxonomy_O4a.csv"
        self.candidates_path = self.aggregated_dir / "master_candidates.csv"
        
        self.taxonomy_df = None
        self.candidates_df = None

    def load_all(self):
        logger.info(f"Caricamento dati da {self.aggregated_dir}...")
        
        if not self.taxonomy_path.exists():
            raise FileNotFoundError(f"{self.taxonomy_path} non trovato.")
        if not self.candidates_path.exists():
            raise FileNotFoundError(f"{self.candidates_path} non trovato.")
            
        self.taxonomy_df = pd.read_csv(self.taxonomy_path)
        self.candidates_df = pd.read_csv(self.candidates_path)
        
        logger.info(f"Tassonomia caricata: {len(self.taxonomy_df)} righe.")
        logger.info(f"Candidate caricate: {len(self.candidates_df)} righe.")
        
    def perform_basic_checks(self):
        if self.taxonomy_df is None:
            raise RuntimeError("Dati non caricati. Esegui load_all() prima.")
            
        logger.info("=== Controlli di base sulla Tassonomia ===")
        if 'transitivity_status' in self.taxonomy_df.columns:
            status_counts = self.taxonomy_df['transitivity_status'].value_counts()
            logger.info("Distribuzione transitivity_status:")
            for status, count in status_counts.items():
                logger.info(f"  {status}: {count}")
        else:
            logger.warning("Colonna 'transitivity_status' non trovata in taxonomy.")
            
        if 'detector' in self.taxonomy_df.columns:
            det_counts = self.taxonomy_df['detector'].value_counts()
            logger.info("Distribuzione detector in taxonomy:")
            for det, count in det_counts.items():
                logger.info(f"  {det}: {count}")
        
        logger.info("=========================================")

if __name__ == "__main__":
    loader = Paper5DataLoader()
    loader.load_all()
    loader.perform_basic_checks()
    print("OK")
