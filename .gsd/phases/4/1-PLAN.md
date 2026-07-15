---
phase: 4
plan: 1
wave: 1
---

# Plan 4.1: Review Rigorosa Paper 5

## Objective
Stesura del documento finale di "Review Rigorosa" che sintetizza le metriche raccolte nelle fasi precedenti (Statistiche e Veto) evidenziando eventuali criticità strumentali, limiti dell'analisi e bias residui.

## Context
- .gsd/ROADMAP.md
- `data/production/aggregated/paper5_summary_stats.md`
- `data/production/aggregated/paper5_validation_report.md`

## Tasks

<task type="auto">
  <name>Stesura Review Rigorosa</name>
  <files>data/production/aggregated/paper5_critical_review.md</files>
  <action>
    - Scrivere il documento markdown `data/production/aggregated/paper5_critical_review.md`.
    - Integrare i risultati: 10372 eventi totali, 0 `Unclassified_Physical_Anomaly`.
    - Discutere l'assenza di leakage, l'uso corretto di padding e il limite della significatività.
    - Elencare potenziali "caveat" o criticità strumentali per gli autori del Paper 5.
  </action>
  <verify>type data\production\aggregated\paper5_critical_review.md</verify>
  <done>Il file markdown di review viene generato con successo e contiene i punti critici richiesti.</done>
</task>

## Success Criteria
- [ ] Documento di review `paper5_critical_review.md` creato.
- [ ] Criticità e limiti metodologici identificati.
