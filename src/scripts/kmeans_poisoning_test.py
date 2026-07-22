import numpy as np
from sklearn.cluster import MiniBatchKMeans

def run_poisoning_test():
    np.random.seed(42)

    # Parametri operativi DANTE
    N_bg = 150000  # segmenti totali
    K = 1216       # budget centroidi
    dim = 384      # dimensione features
    
    print(f"=== MiniBatchKMeans Poisoning Sensitivity Test ===")
    print(f"Background segments: {N_bg}")
    print(f"Centroids (K): {K}")
    print(f"Feature dimension: {dim}\n")

    # 1. Simula background stazionario (distribuzione larga sferica)
    # Per evitare colli di bottiglia memoria, riduciamo in scala se necessario, 
    # ma 150k x 384 = ~230 MB, fattibile.
    X_bg = np.random.randn(N_bg, dim)
    X_bg = X_bg / np.linalg.norm(X_bg, axis=1, keepdims=True)

    # 2. Anomalia sintetica (cluster molto denso e isolato, simulando morphologia coerente come Family_01)
    anomaly_center = np.random.randn(dim)
    anomaly_center = anomaly_center / np.linalg.norm(anomaly_center)

    # Percentuali di avvelenamento da testare
    contamination_levels = [0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.05]
    
    for p in contamination_levels:
        N_anomaly = int(N_bg * p)
        if N_anomaly < 1:
            N_anomaly = 1
            
        # Simula vettori anomalia molto compatti (varianza 0.05)
        X_anom = anomaly_center + 0.05 * np.random.randn(N_anomaly, dim)
        X_anom = X_anom / np.linalg.norm(X_anom, axis=1, keepdims=True)
        
        # Unisci background e anomalia
        X_total = np.vstack([X_bg, X_anom])
        
        # Esegui MiniBatchKMeans (stessi iperparametri della pipeline)
        kmeans = MiniBatchKMeans(
            n_clusters=K,
            batch_size=2048,
            n_init="auto",
            random_state=42
        )
        kmeans.fit(X_total)
        
        centroids = kmeans.cluster_centers_
        
        # Trova la similarità coseno massima tra il centro dell'anomalia e i centroidi
        # Se un centroide si posiziona esattamente sull'anomalia, la similarità ~ 1.0
        # Se l'anomalia è ignorata (assorbita dal background senza deformarlo), la similarità resterà bassa (e.g. ~0.3-0.5 per noise)
        sims = np.dot(centroids, anomaly_center)
        max_sim = np.max(sims)
        
        # Una similarità > 0.85 indica che il KMeans ha dedicato un centroide all'anomalia (avvelenamento riuscito)
        is_absorbed = max_sim > 0.85
        
        print(f"Contamination: {p*100:.3f}% ({N_anomaly} segments) | Max Sim to Anomaly: {max_sim:.4f} | Poisoned: {is_absorbed}")

if __name__ == "__main__":
    run_poisoning_test()
