# Disegno O4a → O4b approvato, 8 ottobre 2026

## Decisione dell'autore

L'autore approva A, non come braccio unico: A1 qualifica la nuova catena su
O4a, A2 studia il trasferimento a O4b, B è il confronto secondario adattato.
Questo sostituisce la precedente alternativa esclusiva A/B di 08.52.
La richiesta indica esplicitamente reference storica **O4a**, non l'indice
primario O3b citato nella proposta precedente. Non viene selezionato O3b.

| Braccio | Reference | Evaluation | Ruolo approvato |
|---|---|---|---|
| A1 | Nuovo artefatto16k dalle finestre storiche O4a da identificare esattamente | O4a tenuta da parte, disgiunta | Qualificazione entro run della catena16k |
| A2 | Lo stesso artefatto di reference A1, senza refit | O4b disgiunta | Trasferimento tra run |
| B | Nuovo artefatto da reference O4b separata da calibrazione/evaluation | Le stesse identità di evaluation O4b di A2 | Comparatore adattato secondario |

Approvati per la prima qualificazione: ingresso nativo16384Hz,
bandpass20–2000Hz e Q-transform20–2048Hz. Nessuna estensione implicita del
filtro a2048Hz, nessun notch CW o cambiamento silenzioso dello scoring.
Altri parametri provengono dai config versionati e dal futuro contratto
isolato approvato, non da deduzioni numeriche dalla chat.

Se le finestre originali non sono recuperabili, l'autore consente una nuova
ricostruzione con la stessa regola di selezione dichiarata prima dei risultati.
Una coorte ricostruita va identificata come tale, non come replica di identità
mai dimostrate. Non è consentito passare silenziosamente aB.

## Evidenza sui membri O4a: solo metadati, nessuna nuova run

Sono presenti due sorgenti diverse. Non sono intercambiabili.

1. `data/reference/patch_compressed_index_o4a_q4-64_ex.t_bg.json`:
   1294 valori GPS numerici senza detector, SHA256
   `eb94118672bbe50b8a7ead63cc298f92804aa54afd9750e01a9e3797843fb061`.
   Il solo elenco non consente di ricostruire le identità detector/GPS.
2. `artifacts/dante_light/o4a_v1_parity/corrected_native_cohort.json`:
   descrittore storico `PASS_VERIFIED_NATIVE_COHORT` della coorte corretta,
   detector-aware, autorizzata il1settembre2026. Il ledger esterno esiste in:
   `E:/dante_cache/dante_light/o4a_corrected_native_v1/native_cohort_733a65f58de3143dc8ca860f4a800aba5d59d05bff6a59d92e3515e3de61f05b/native_cohort.jsonl`.
   Lettura amministrativa osservata oggi:1294righe,1294identità uniche
   detector/GPS,647H1 e647L1; SHA256
   `358138d942267b73d5bbd95a8a0204b8dd2f260f1d2797e6cde2f6bd75252b46`,
   corrispondente al descrittore. Nessun array strain o score letto.

Il contratto `config/dante_o4a_corrected_native_v1.json`, digest
`66f5796aecdea5a1009257a96a351e960c0801eadb60dc40bbf01bdfa74378c2`,
documenta la sostituzione dell'elenco detector-ambiguo, non l'inferenza dei
suoi detector. Questa coorte corretta è quindi una candidata concretamente
recuperabile, ma non viene adottata qui come training A1 senza conferma.

La coorte e l'indice corretti precedenti sono a4096Hz. Il loro PASS storico
non è una qualificazione16k. Disponibilità e copertura dei raw16k per gli
stessi contesti non sono ancora verificate; non si riusano i vecchi clean
window/token come ingresso16k e non si acquisisce strain in questo incremento.

## Interpretazione e controlli necessari nel contratto successivo

- A1→A2 è il contrasto di trasferimento approvato, ma include le differenze di
  stato del detector, rumore/calibrazione e composizione delle popolazioni.
  Non è automaticamente una stima causale di un unico effetto della run.
- A1 da sola non dimostra equivalenza al4k storico, né isola tutte le
  conseguenze di campionamento/banda. Nessun nuovo braccio4k viene aggiunto.
- A2→B confronta reference trasferita e adattata. B è un benchmark empirico:
  non è garantito che migliori il risultato e non è un upper bound matematico.
- Per questo contrasto vanno mantenuti comparabili metodo/model/scorer,
  capacità/budget della reference e regola di calibrazione; il contratto dovrà
  esplicitare ciò che è uguale e ciò che cambia. Nessun valore nuovo adottato.
- A1/A2 usano una reference byte-identica. A2/B usano identiche finestre di
  evaluation O4b. Training, calibrazione ed evaluation sono separate anche
  per contesti padded, non solo per GPS centrali; leakage audit prima degli score.
- Una finestra esclusa dal training non diventa per questo un holdout mai
  visto. La coorte corretta storica usa esclusioni di candidati della scansione:
  lo stato di esposizione precedente delle evaluation O4a va dichiarato.
- Calibrazioni pertinenti e regola congelata per ogni braccio/run; niente
  trapianto delle soglie precedenti. Endpoint e criteri confermativi devono
  essere definiti prima dei risultati, con bootstrap a blocchi se previsto.

Release/GPS/DQ, identità delle evaluation e calibrazioni, null, endpoint,
criteri di accettazione e promozione restano da approvare nel contratto.
V1 resta separato con artefatti/reference/calibrazione/null propri: questo
disegno H1/L1 non autorizza riuso dei null o coerenza a tre detector.

## Checkpoint unico prima della ricostruzione

**Proposta:** intendere per finestre storiche O4a la coorte corretta
detector-aware verificata sopra (1294identità,647H1+647L1).
Serve conferma dell'autore, perché scegliere tra i due ledger modifica la
popolazione di training. Non si inferiscono detector del vecchio elenco.

Dopo conferma: verifica della disponibilità raw16k sugli stessi contesti e
proposta concreta delle popolazioni disgiunte/metodo isolato; test e freeze
prima delle esecuzioni. Nessun config scientifico attivo, acquisizione strain,
ricostruzione dell'indice o lancio O4b in questo incremento. O3a e tutti gli
artefatti storici/interruzioni restano immutabili; monitor resta sospeso.

## Push e verifica osservati

Su richiesta esplicita `pusha`,132commit precedentemente locali sono stati
pubblicati solo su `science/o3-transfer-readiness`, remoto passato da
`ae9395a` a `b08cc5dba17f314846cfc184921c39e7aca95622`, pushOSexit0.
Lettura live successiva conferma main invariato a
`3e3302f94f3ab1b4dfbf4a99c7f677bf304efbe4`.

Prima del push: diff check pulito; fixture CWStageC/planning/metadata
**55passed/3.12s/OSexit0**. Audit mirato degli oggetti aggiunti:796blob,
25273129byte totali, nessun blob≥100MB e nessun pattern di credenziali ad alta
confidenza riconosciuto; non è un audit completo di sicurezza.
Questi controlli non certificano equivalenza CW reale, catena16k o readiness
O4b. La successiva registrazione documentale riceve diff check, non un rerun
scientifico. `output/` e `artifacts/dante_workflow/public_smoke_v1/` non aggiunti.
