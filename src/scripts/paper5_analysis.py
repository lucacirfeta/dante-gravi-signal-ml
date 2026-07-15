import sys
from pathlib import Path
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Assicuriamoci che python riesca a trovare src
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.scripts.paper5_data_loader import Paper5DataLoader

def run_analysis():
    loader = Paper5DataLoader()
    try:
        loader.load_all()
    except Exception as e:
        logger.error(f"Errore caricamento dati: {e}")
        return

    tax_df = loader.taxonomy_df
    cand_df = loader.candidates_df

    report_lines = []
    report_lines.append("# Paper 5 Summary Statistics\n")

    report_lines.append("## 1. Dati Analizzati\n")
    report_lines.append(f"- **Totale eventi tassonomia:** {len(tax_df)}")
    report_lines.append(f"- **Totale eventi candidati:** {len(cand_df)}\n")

    report_lines.append("## 2. Distribuzione per Detector\n")
    if 'detector' in tax_df.columns:
        det_counts = tax_df['detector'].value_counts()
        for det, count in det_counts.items():
            report_lines.append(f"- **{det}**: {count}")
    report_lines.append("\n")

    report_lines.append("## 3. Classificazione Anomalie (transitivity_status)\n")
    if 'transitivity_status' in tax_df.columns:
        status_counts = tax_df['transitivity_status'].value_counts()
        for status, count in status_counts.items():
            report_lines.append(f"- **{status}**: {count}")
    report_lines.append("\n")

    report_lines.append("## 4. Statistiche SNR (se disponibili)\n")
    # Tassonomia O4a potrebbe avere SNR, ma controlliamo cand_df se tax_df non ce l'ha
    snr_col = 'snr' if 'snr' in tax_df.columns else None
    if not snr_col and 'snr' in cand_df.columns:
        snr_col = 'snr'
        df_for_snr = cand_df
    else:
        df_for_snr = tax_df

    if snr_col and snr_col in df_for_snr.columns:
        median_snr = df_for_snr[snr_col].median()
        max_snr = df_for_snr[snr_col].max()
        report_lines.append(f"- **SNR Mediano:** {median_snr:.2f}")
        report_lines.append(f"- **SNR Massimo:** {max_snr:.2f}")
    else:
        report_lines.append("- Colonna 'snr' non trovata nei dataset correnti.")
    
    report_lines.append("\n")

    # Save to file
    out_path = loader.aggregated_dir / "paper5_summary_stats.md"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        logger.info(f"Report salvato in {out_path}")
    except Exception as e:
        logger.error(f"Errore durante il salvataggio del report: {e}")

if __name__ == "__main__":
    run_analysis()
