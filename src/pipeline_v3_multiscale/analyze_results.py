import argparse
import pandas as pd
import numpy as np
import scipy.stats as stats
from pathlib import Path
from statsmodels.stats.contingency_tables import mcnemar

def wilson_ci(k, n, z=1.96):
    if n == 0: return 0.0, 0.0
    p = k / n
    denom = 1 + z**2/n
    center = (p + z**2/(2*n)) / denom
    spread = z * np.sqrt(p*(1-p)/n + z**2/(4*n**2)) / denom
    return max(0.0, center - spread), min(1.0, center + spread)

def analyze_results(detector="L1", n_test=200):
    res_file = Path(f"results/micro_mdc/multiscale/{detector}_real_blips_scoring_results_{n_test}.csv")
    if not res_file.exists():
        print(f"File not found: {res_file}")
        return
        
    df = pd.read_csv(res_file)
    N = len(df)
    
    print(f"\n=== Analisi Risultati Multiscale Pilota ({detector}) ===")
    print(f"N. Eventi (Blip/Blip_LF con conf>=0.90): {N}\n")
    
    # 1. Recall per scala + Native + Union
    recalls = {}
    print("Recalls (con Wilson CI 95%):")
    for col in ["novel_0.5s", "novel_1s", "novel_2s", "novel_4s", "novel_native", "novel_union"]:
        k = df[col].sum()
        p = k / N
        low, high = wilson_ci(k, N)
        recalls[col] = p
        print(f"  {col:<15}: {p:.2%} [{low:.2%}, {high:.2%}]")
        
    # --- H1: Union vs Native (McNemar Test) ---
    print("\n[H1] L'unione fine-scale batte la pipeline nativa a 32s (McNemar test)")
    # Contingency table
    #            Native_True  Native_False
    # Union_True      a            b
    # Union_False     c            d
    
    a = len(df[(df["novel_union"] == True) & (df["novel_native"] == True)])
    b = len(df[(df["novel_union"] == False) & (df["novel_native"] == True)])
    c = len(df[(df["novel_union"] == True) & (df["novel_native"] == False)])
    d = len(df[(df["novel_union"] == False) & (df["novel_native"] == False)])
    
    table = [[a, b], [c, d]]
    res = mcnemar(table, exact=False, correction=True)
    
    print(f"  Contingency Table: {table}")
    print(f"  Guadagno Assoluto: +(c-b) = {c-b} blip rilevati in più dall'unione")
    print(f"  Guadagno Percentuale: +{(c-b)/N:.2%} punti percentuali")
    print(f"  p-value = {res.pvalue:.4e}")
    if res.pvalue < 0.05 and c > b:
        print("  -> H1 CONFERMATA: L'unione è significativamente superiore.")
    else:
        print("  -> H1 RIFIUTATA: Nessuna superiorità significativa.")
        
    # --- H2: Correlazione Durata - Score ---
    print("\n[H2] Correlazione di Spearman tra durata Omega e score di anomalia")
    durations = df["duration"].values
    for s in [0.5, 1, 2, 4, 32]:
        col = f"score_{s}s" if s != 32 else "score_32s_native"
        scores = df[col].values
        rho, pval = stats.spearmanr(durations, scores)
        print(f"  Scala {s:>4}s: rho = {rho:+.3f}, p-value = {pval:.4e}")
        
    # --- H3: Scala 0.5s vs Union ---
    print("\n[H3] La scala 0.5s da sola non risolve tutto (0.5s < Union)")
    diff = recalls['novel_union'] - recalls['novel_0.5s']
    print(f"  Recall 0.5s : {recalls['novel_0.5s']:.2%}")
    print(f"  Recall Union: {recalls['novel_union']:.2%}")
    print(f"  Diff        : +{diff:.2%} punti")
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector", type=str, default="L1")
    parser.add_argument("--n_test", type=int, default=200)
    args = parser.parse_args()
    analyze_results(detector=args.detector, n_test=args.n_test)
