---
phase: 2
plan: 1
wave: 1
---

# Plan 2.1: Analisi Base Paper 5

## Objective
Creare lo script di analisi base per calcolare e salvare le statistiche generali sui dati aggregati del Paper 5 (es. SNR, frequenze, distribuzioni temporali).

## Context
- .gsd/ROADMAP.md
- `src/scripts/paper5_data_loader.py`

## Tasks

<task type="auto">
  <name>Script Analisi Statistiche</name>
  <files>src/scripts/paper5_analysis.py</files>
  <action>
    - Creare `src/scripts/paper5_analysis.py`.
    - Importare `Paper5DataLoader` per ottenere la tassonomia e i candidati.
    - Calcolare statistiche aggregate chiave: SNR mediano/massimo per detector, classificazione anomalie e distribuzioni temporali.
    - Salvare l'output in `data/production/aggregated/paper5_summary_stats.md`.
  </action>
  <verify>python src/scripts/paper5_analysis.py && type data\production\aggregated\paper5_summary_stats.md</verify>
  <done>Lo script genera il file di report con le statistiche richieste senza errori.</done>
</task>

## Success Criteria
- [ ] Script di analisi completato e funzionante.
- [ ] Report generato in `paper5_summary_stats.md`.
