---
phase: 3
plan: 1
wave: 1
---

# Plan 3.1: Validazione e Veto Paper 5

## Objective
Creare uno script per eseguire i controlli fisici e identificare candidati anomali (`Unclassified_Physical_Anomaly`) da rivedere manualmente per la stesura del paper.

## Context
- .gsd/ROADMAP.md
- `src/scripts/paper5_data_loader.py`

## Tasks

<task type="auto">
  <name>Script Validazione e Veto</name>
  <files>src/scripts/paper5_validation.py</files>
  <action>
    - Creare `src/scripts/paper5_validation.py`.
    - Importare `Paper5DataLoader`.
    - Filtrare gli eventi con `transitivity_status == "Unclassified_Physical_Anomaly"`.
    - Verificare la significatività e coerenza temporale (es. conteggio per detector).
    - Generare un report di validazione in `data/production/aggregated/paper5_validation_report.md` con l'elenco dei candidati "Unclassified" (se presenti) per review manuale.
  </action>
  <verify>python src/scripts/paper5_validation.py && type data\production\aggregated\paper5_validation_report.md</verify>
  <done>Lo script esegue i check fisici e genera il report di validazione.</done>
</task>

## Success Criteria
- [ ] Script di validazione completato.
- [ ] Report generato in `paper5_validation_report.md`.
