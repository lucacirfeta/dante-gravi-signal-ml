---
phase: 1
plan: 1
wave: 1
---

# Plan 1.1: Setup Dati Paper 5

## Objective
Creare lo script di base per caricare e validare strutturalmente i risultati aggregati in preparazione al Paper 5.

## Context
- .gsd/SPEC.md
- `data/production/aggregated/Master_Taxonomy_O4a.csv`

## Tasks

<task type="auto">
  <name>Script DataLoader Paper 5</name>
  <files>src/scripts/paper5_data_loader.py</files>
  <action>
    - Creare `src/scripts/paper5_data_loader.py`.
    - Aggiungere funzione che carica `Master_Taxonomy_O4a.csv` e `master_candidates.csv` in `pandas.DataFrame`.
    - Eseguire controlli di base sui dati (es. conteggio anomalie fisiche vs strumentali).
  </action>
  <verify>python src/scripts/paper5_data_loader.py</verify>
  <done>Lo script carica i dati aggregati e stampa i conteggi di base senza errori.</done>
</task>

## Success Criteria
- [ ] Dati aggregati caricati con successo in memoria.
