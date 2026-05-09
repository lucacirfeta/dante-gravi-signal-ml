# Session Handoff — gravi-signal-ml

## Stato attuale: Phase 3.1 in esecuzione
- `python main.py scan-extended` in corso (H1 48h + L1 48h)
- Scan avviato il 2026-05-09, stima ~6-8h

## Prossimi comandi da eseguire (nell'ordine)
1. python main.py encode --input-dir data/spectrograms/o4a/H1/ --output data/embeddings/o4a_h1_48h.npy
2. python main.py encode --input-dir data/spectrograms/o4a/L1/ --output data/embeddings/o4a_l1_48h.npy
3. python main.py cluster --input data/embeddings/o4a_h1_48h.npy --output data/clusters/h1_48h/
4. python main.py crosscheck --report data/clusters/h1_48h/cluster_report.json --metadata data/embeddings/o4a_h1_48h.json --detector H1 --output data/clusters/h1_48h/gravity_spy_crosscheck.json

## Risultati Phase 3 (6h H1)
- 4 cluster trovati, 0 noise
- Cluster 2 (9 pts): ANOMALOUS - persistent multi-line narrowband
- Cluster 3 (6 pts): ANOMALOUS - isolated compact transients
- Contact sheet salvati in results/figures/clusters/

## Obiettivo Phase 3.1
Verificare che i cluster anomalous sopravvivano con 48h di dati
e cross-check con Gravity Spy API per escludere classi già note.

## Phase 3.2 — Pipeline Parallelization (da implementare)
Architettura:
  - ThreadPoolExecutor(max_workers=4) per fetch GWOSC (I/O bound)
  - Semaphore + 300ms delay per rispettare rate limit GWOSC
  - ProcessPoolExecutor(max_workers=N-2) per Q-transform (CPU bound)
  - Pattern producer-consumer con Queue tra i due pool
  - Flag --workers N (default=1, backward compatible)
  - Con --workers 8 su Ryzen 7800X3D: stima 4-5x speedup
File da modificare: src/preprocessor.py batch_process()
File da aggiornare: main.py (aggiungere --workers a scan, scan-extended)
Nuovo file: src/parallel_processor.py (logica parallelismo isolata)
## Session end — 2026-05-09

**Stato alla chiusura:**
- `scan-extended` in esecuzione: H1 48h + L1 48h
- Completate finora: H1 6h (Phase 3.0)
- Tempo restante stimato: 6-8 ore
- Output temporaneo: `data/spectrograms/o4a/H1/2025-11-14T00:00:00-2025-11-16T00:00:00`

**Azioni da riprendere al prossimo avvio:**
1. Monitorare `scan-extended` finché non completa
2. Eseguire `python main.py encode` sui nuovi spectrogrammi (H1 + L1)
3. Eseguire `python main.py cluster` sui nuovi embeddings
4. Eseguire `python main.py crosscheck` sui nuovi cluster

**Backup manuale (2026-05-09, 15:19 CET):**
```bash
# Backup dei progressi finora
cd /dante-gravi-signal-ml/
zip -r backup_2026-05-09_1519.zip main.py data/ results/ requirements.txt docs/ README.md logs/

# Spostare il backup in una cartella sicura
cd ..
mv gravi-signal-ml/backup_2026-05-09_1519.zip /mnt/backup/ml_projects/
```

**Punto di ripresa:**
- `scan-extended` continuerà automaticamente
- Output continuerà ad accumularsi in `data/spectrograms/o4a/H1/`
- Backup disponibile in `/mnt/backup/ml_projects/`

## Performance

By default, the pipeline runs sequentially (--workers 1) 
and works on any machine, including laptops.

If you have a multi-core CPU and want to speed up scanning:
  python main.py scan-extended --workers 8  # ~4-6x faster

Recommended workers = number of physical CPU cores - 2