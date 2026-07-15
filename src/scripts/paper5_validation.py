import sys
from pathlib import Path
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.scripts.paper5_data_loader import Paper5DataLoader

def run_validation():
    loader = Paper5DataLoader()
    try:
        loader.load_all()
    except Exception as e:
        logger.error(f"Errore caricamento dati: {e}")
        return

    tax_df = loader.taxonomy_df
    report_lines = []
    report_lines.append("# Paper 5 Validation & Veto Report\n")

    if 'transitivity_status' not in tax_df.columns:
        logger.error("Manca la colonna transitivity_status")
        return

    # Filter unclassified physical anomalies
    mask_unclassified = (tax_df['transitivity_status'] == 'Unclassified_Physical_Anomaly')
    unclassified_df = tax_df[mask_unclassified]

    report_lines.append("## 1. Sommario Eventi Fisici Non Classificati\n")
    report_lines.append(f"- **Totale eventi 'Unclassified_Physical_Anomaly':** {len(unclassified_df)}\n")

    if len(unclassified_df) > 0:
        report_lines.append("### Distribuzione per Detector:\n")
        if 'detector' in unclassified_df.columns:
            det_counts = unclassified_df['detector'].value_counts()
            for det, count in det_counts.items():
                report_lines.append(f"- **{det}**: {count}")
        report_lines.append("\n")
        
        report_lines.append("### Elenco Eventi da revisionare manualmente:\n")
        # Extract meaningful columns if available
        cols_to_print = ['gps_start', 'detector', 'global_family_id', 'transitivity_status']
        cols_available = [c for c in cols_to_print if c in unclassified_df.columns]
        
        # Limit to 50 for the report if it's large
        subset_df = unclassified_df[cols_available].head(50)
        report_lines.append(subset_df.to_markdown(index=False))
        if len(unclassified_df) > 50:
            report_lines.append(f"\n*(Mostrati solo i primi 50 di {len(unclassified_df)})*\n")
    else:
        report_lines.append("> Nessun evento 'Unclassified_Physical_Anomaly' individuato. Tutti i candidati sono stati identificati, classificati o correlati.\n")

    # Save to file
    out_path = loader.aggregated_dir / "paper5_validation_report.md"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        logger.info(f"Report di validazione salvato in {out_path}")
    except Exception as e:
        logger.error(f"Errore durante il salvataggio del report: {e}")

if __name__ == "__main__":
    run_validation()
