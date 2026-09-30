# ROADMAP.md

> **Current Milestone**: DANTE v6 evidence repair and dual-paper delivery
> **Goal**: una sola evidenza validata per arXiv v6 e CQG autoconsistente.

## Phase 1: Shared calibration gate

**Status**: Completed

- rendere il sampler threshold run-bounded e temporalmente disgiunto;
- salvare il ledger GPS e la provenance completa;
- aggiungere test regressivi per cross-run contamination e leakage;
- invalidare i cache non auditabili e ricalibrare H1/L1.

## Phase 2: Shared evidence propagation

**Status**: In progress

- rigenerare soglie, tassonomia e transition audit;
- identificare e rieseguire ogni analisi class-dependent;
- rigenerare figure/tabelle e consistency audit;
- aggiornare LAB_NOTEBOOK e preparare il bundle riproducibilità.

## Phase 3: arXiv v6

**Status**: Pending

- integrare i risultati comuni congelati;
- aggiungere claim-status v5 -> v6 e correction log completo;
- verificare source package e PDF arXiv.

## Phase 4: CQG v6

**Status**: Pending

- ricostruire Methods e Data come esposizione autonoma;
- aggiungere schema, esempi, parametri, sessioni, baseline e appendici;
- verificare reporting, bibliografia, data availability e PDF.

## Phase 5: Final cross-paper gate

**Status**: Pending

- audit numerico e semantico incrociato;
- verifica dei DOI e dei manifest;
- controllo finale come reviewer CQG e come continuation arXiv.

## Phase 6: Multiscale efficiency v2

**Status**: In progress

- conservare le curve 2026-07 come evidenza esplorativa, non end-to-end;
- congelare una coorte O4a outcome-blind disgiunta per blocco raw da indice e
  calibrazione nativi, con candidate guard cross-detector;
- misurare separatamente recovery end-to-end e risposta condizionale
  multiscala, con incertezza block-aware e provenance completa;
- non derivare upper limit morfologici senza un successivo contratto di
  popolazione e livetime.

## Phase 8: Multi-run workflow productization

**Status**: In progress; administrative foundation verified 2026-09-30

Author-approved scope: all public H1/L1 runs and V1 where public strain exists.
The historical manuscript milestone above is preserved; this is the newly
approved software milestone, not a claim that its scientific gates are done.

- 08.01: sealed run catalogue, explicit detector/run selection and exact
  adapter dispatch; PASS administrative-only, local commit8d29136.
- Bind existing O3a stage CLIs and receipts without changing frozen science;
  version profile-specific stage applicability separately from O4a's graph.
- Add a real common CLI/UI selector, exact-GPS data/DQ/context preflight and
  clean-install bounded real replays; do not confuse availability with support.
- Freeze new-run/V1 population/reference/calibration contracts before enabling
  measurement. Any new scientific choice requires author decision.
- Approve any Virgo pairwise/network null separately; no implicit transplant
  of bipartite H1/L1 thresholds, pooling or global significance claim.
- Resolve/qualify Git-source identity and detached-launch portability before
  declaring a full multi-run release ready. No automatic push/merge/publication.
