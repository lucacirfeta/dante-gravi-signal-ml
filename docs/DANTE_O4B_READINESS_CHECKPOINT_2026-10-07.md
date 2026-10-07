# Checkpoint readiness O4b e pipeline multi-run — 7 ottobre 2026

Stato ricostruito in sola lettura sul checkout `140878ba1c81f27e5d4a803d86088d1ac21b0037`,
branch `science/o3-transfer-readiness`. Questo documento è una ricognizione,
non un contratto scientifico attivo, una modifica dei criteri di accettazione o
un'autorizzazione a eseguire O4b. Nessun test, replay, verifier o download di
strain è stato avviato per produrlo. Le suite già concluse non sono state ripetute.

## Cosa è già disponibile

- Reader nativo e admission degli input estesi: 08.34–08.36 conclusi nel loro
  perimetro, con verifica indipendente. Non certificano una nuova popolazione O4b.
- Preprocessing con contesto padded della popolazione precedente: 08.38 concluso
  con confronto RGB esatto e 306 test post-run; non qualifica automaticamente
  il nuovo metodo O4b a 16 kHz.
- Integrazione produttiva isolata: 08.39 verifica il boundary degli input e
  437 test post-run; non equivale a completa calibrazione numerica.
- Pacchetto installato, CLI amministrativa e rendering di tre route UI:
  verificati separatamente. La suite amministrativa di 100 test e la regressione
  post-run di 489 pass / 3 skip restano conservate, senza nuova esecuzione.
- Metadati ufficiali O4b conservati su E:; native 16.384 Hz / banda di analisi
  20–2048 Hz e CW come annotazione, senza veto globale, sono scelte approvate.
  L'allocazione concreta reference/calibrazione/evaluation non è ancora fissata.
- Stage A CW sintetico a 16 kHz è concluso nel suo perimetro descrittivo isolato;
  non è la promozione della rappresentazione a metodo produttivo O4b.

## Gate necessari ancora aperti

| Gate | Stato e prossimo requisito concreto |
|---|---|
| Qualificazione completa della catena produttiva precedente | La run 08.43 è completa, ma il suo verifier è stato interrotto dall'autore. Non esiste `PASS_VERIFIED`; la disposizione di questo limite resta esplicita, senza retry automatico o sostituzione con test brevi. |
| Metodo produttivo O4b a 16 kHz | Versionare e qualificare routing, preprocessing e rappresentazione approvati, con reference/index e calibrazione compatibili. Il protocollo produttivo precedente specifica ancora 4096 Hz; Stage A è un chiamante isolato, non un adapter produttivo. Nessuna equivalenza automatica nella banda alta rispetto ai lavori storici. |
| Popolazioni e statistica O4b | Fissare GPS/epoche, DQ, griglia e copertura completa del padding; reference/calibrazione/evaluation temporalmente disgiunti; soglie e validazione dedicate. Non trasferire soglie O4a né scegliere finestre sulla base degli score. |
| Contratti multi-run eseguibili | Il registro O4b ha ancora `method_contract:null` e `workflow_contract:null`. La disponibilità pubblica del rivelatore non è una qualificazione del metodo o del workflow. |
| Runtime/index/encoder/scoring e calibrazione nuova | Prova numerica della catena approvata, nel runtime effettivo, con output e verifiche coerenti col nuovo contratto. Un cambiamento di driver da solo non è un veto permanente, ma i vecchi risultati non provano la nuova catena. |
| CLI/UI scientifico end-to-end e installazione scientifica | Restano aperti il percorso scientifico completo dell'expanded provider e il replay di reader/model/dependency nel pacchetto installato. Wheel/help/plan/rendering HTTP verificati non li sostituiscono. |
| Preflight finale e avvio O4b | Contratto congelato, input/copertura, source/runtime/storage e riepilogo dei limiti. Dopo readiness, richiesta separata di avvio: questa ricognizione non lancia O4b. |

## Virgo è un ramo separato

V1 è disponibile nei metadati O4b, ma necessita dei propri reference/index,
calibrazione, null e validazione. Gli ingressi congelati H1/L1 non si allargano
semplicemente rimuovendo una guardia: `load_frozen_raw_manifest` e il builder
native-index sono ancora H1/L1. Nessun riuso del null bipartito H1/L1 o promozione
a coerenza a tre rivelatori è autorizzato. La preparazione V1 non deve essere
confusa con un requisito per lanciare un futuro perimetro H1/L1 approvato.

## CW: ricerca separata, non certificato universale

L'ultimo incarico parallelo autorizza una diagnostica descrittiva circoscritta
sulle coppie RGB già conservate, a DINO/reference congelati, senza nuove soglie
o dichiarazioni di equivalenza. Lo Stage B confermativo resta un progetto
scientifico distinto: il suo JSON di pianificazione è disabilitato e non ammette
strain, popolazioni o esecuzione. Non chiude i gate O4b sopra e non va presentato
come condizione implicita per ogni attività tecnica. Una claim di irrilevanza
delle CW reali richiede invece evidenza specifica alle dosi e ai dati pertinenti.

## Evidenze locali rilette in questo checkpoint

- `config/dante_workflow_runs_v1.json`: O4b method/workflow null; la URL di
  catalogo del registro è ancora quella 4 kHz. Non è stata cambiata o usata per
  annullare la proposta metadata-only a 16 kHz.
- `config/dante_o4a_corrected_protocol_v4.json`: `sample_rate_hz:4096`;
  `src/core/patch_producer.py` resample al sample rate configurato.
- `/home/atafe/dante_bench/native_calibration_20261006/execution_v2/exits.json`:
  `run:0`, `verify:254`, `automatic_resume:false`.
- `/home/atafe/dante_bench/native_calibration_20261006/calibration_native_v2/summary.json`:
  `PASS_COMPLETE_ISOLATED_EXPANDED_CALIBRATION_ONLY`, 39.971 identità,
  39.891 contesti, 84 session-detector; SHA256
  `2511ff69f38c1bf7a68981f5be6f3766238083dbcebcfa5a61a3f3d50db8335c`.
  Esistono 84 JSON di sessione; `progress.verify.json` resta a 7.273/39.971;
  `verification.json` e `controller.lock` assenti. La causa di exit254 è
  l'interruzione esplicita documentata, non una nuova failure numerica diagnosticata.
- `E:/dante_cache/dante_workflow/o4b_metadata_proposal_20261007/snapshot_v1/proposal.json`:
  SHA256 `5233f7567afaaa354115f2178f30da39e69b8af1ea55901d23e8dc795d7dfc0e`;
  `population_allocation:null`, `context_coverage_verified:false`,
  `scientific_execution_ready:false`, `strain_files_inspected:0`.

Riferimenti di stato: `.gsd/STATE.md`, piani 08.44/08.45/08.50,
`docs/DANTE_WORKFLOW_PRE_O4B_CHECKLIST_2026-10-04.md`,
`docs/DANTE_WORKFLOW_INSTALLED_BOUNDARY_2026-10-06.md`,
`docs/DANTE_WORKFLOW_O4B_METADATA_PROPOSAL_2026-10-07.md`.

Nessuna stima di durata o nuovo PASS scientifico è ricavato da questa ricognizione.
Run/failure/interruzioni storiche e directory utente untracked restano immutate;
O3a non viene riaperta e il monitor resta fuori da questo incarico.
