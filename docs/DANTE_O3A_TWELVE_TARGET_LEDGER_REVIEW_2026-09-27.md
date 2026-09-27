# O3a: review dei 12 target selezionati, solo ledger

Data: 2026-09-27 Europe/Rome. Stato al momento di questo audit: **ledger
completato; revisione visuale/strumentale non ancora eseguita**. La successiva
[revisione visuale](DANTE_O3A_TWELVE_TARGET_VISUAL_REVIEW_2026-09-27.md) è
documentata separatamente. Questo documento non introduce statistiche,
soglie, ordinamenti o classificazioni nuovi e non promuove candidati.

## Provenance e controlli

Input: receipt verificati `native_classification.json`, `native_taxonomy.json`,
`native_coincidence.json` e `native_pem.json` sotto
`artifacts/dante_light/o3a_native_v1/`. I ledger esterni restano nelle
rispettive run canoniche sotto `E:\dante_cache\dante_light\o3a_native_v1`.
I SHA-256 dei sei JSONL usati (classificazione, tassonomia, coincidenza
ROBUST/AMBIGUOUS, PEM primary/diagnostic) coincidono con i receipt/summary
congelati. L'join per `identity_digest` collega esattamente 8.900 righe di
classificazione, 8.900 di tassonomia, 6.408 di coincidenza e i 12 target
PEM, senza identità mancanti o mismatch di detector, GPS, classe, score,
image/raw-context hash o `cc_onsource`. I 12 sono esattamente i seed con
`exceeds_primary_threshold=true` nel ledger di coincidenza: 11 ROBUST
primari e uno AMBIGUOUS diagnostico. Per tutti i 12, i cinque canali PEM
del detector sono disponibili; SHA-256 della calibrazione, massimo tra
canali, top channel, soglie e verdetto coincidono con i rispettivi JSON.
Tutti sono stati calibrati; nessun `UNCALIBRATED` è stato trasformato in
negativo. Il verificatore PEM standalone era già uscito con codice 0 prima
di questo audit. Qui non sono stati riacquisiti dati né ricomputati strain,
Q-transform, embedding, cross-correlazioni o null empirici.

## Ledger target (valori arrotondati solo per lettura)

`cc` è la correlazione on-source della coincidenza; `null locale` indica
**soltanto** il booleano preregistrato `per_event_null_exceeded`, distinto
dalla soglia pooled che ha selezionato questi target. `NC` significa
`NO_CORRELATION` nel PEM diagnostico sui cinque canali pubblici testati;
non significa assenza di coupling in sensori non pubblici. I valori esatti,
le due soglie PEM per evento e le identità complete restano nei JSONL sigillati.

| Detector | GPS inizio | Tier | Score nativo | cc | Null locale | PEM |
| --- | ---: | --- | ---: | ---: | --- | --- |
| L1 | 1238507872 | ROBUST | 0.4942 | 0.2693 | sì | NC |
| L1 | 1238508320 | ROBUST | 0.4863 | 0.4356 | sì | NC |
| L1 | 1238515136 | ROBUST | 0.5284 | 0.2868 | no | NC |
| L1 | 1239175264 | ROBUST | 0.5048 | 0.3159 | no | NC |
| L1 | 1239628448 | ROBUST | 0.4845 | 0.3196 | sì | NC |
| L1 | 1241808544 | ROBUST | 0.4271 | 0.3144 | sì | NC |
| H1 | 1243231936 | ROBUST | 0.4400 | 0.3495 | sì | NC |
| L1 | 1243231936 | ROBUST | 0.5094 | 0.2612 | sì | NC |
| H1 | 1245414400 | AMBIGUOUS (diagnostic) | 0.4029 | 0.2750 | sì | NC |
| L1 | 1247267872 | ROBUST | 0.4594 | 0.3115 | no | NC |
| L1 | 1253362624 | ROBUST | 0.4433 | 0.2910 | no | NC |
| H1 | 1253581920 | ROBUST | 0.4573 | 0.2565 | sì | COUPLED |

Sette degli 11 primari e l'unico diagnostico superano anche il proprio null
per-evento; quattro primari superano il pooled p99 diagnostico ma **non** il
proprio null per-evento. Questo è un confronto tra booleani già prodotti
dalla run, non un nuovo gate di selezione. Tutti e 12 hanno `Family_01`,
coerentemente con il chaining single-linkage (8.899/8.900 nella famiglia
dominante); l'ID di famiglia non discrimina qui una morfologia fisica.

## Due casi da esaminare senza promozione

- **H1 GPS 1253581920:** l'unico `COUPLED` primario. Il massimo PEM
  `0.5363456117` è nel canale `H1:LSC-POP_A_LF_OUT_DQ` a 390.5 Hz;
  supera sia il controllo time-shift `0.3555665314` sia il quiet zero-lag
  `0.5035300851`. È un flag di accoppiamento ambientale secondo il
  contratto diagnostico, non un veto automatico né una spiegazione causale
  completa della strain.
- **H1 e L1 GPS 1243231936:** due seed ROBUST nella medesima finestra
  di 32 s, entrambi sopra il pooled p99 e il proprio null per-evento; il
  PEM a cinque canali è `NO_CORRELATION` per entrambi. Le localizzazioni
  Top-k dentro la finestra sono 22.4865 s (H1) e 22.9189 s (L1): non sono
  una misura del ritardo di propagazione tra i detector e non dimostrano
  che si tratti dello stesso transiente. Il test `cc` usa subfinestre
  localizzate separatamente, una banda derivata da ciascun seed e il lag
  fisico ammesso dal contratto. I due record non sono due prove statistiche
  indipendenti. Serve ispezione time-frequency e strumentale prima di
  attribuire un'interpretazione fisica.

Le tre calibrazioni PEM L1 per GPS 1238507872, 1238508320 e 1238515136
riusano lo stesso span di background di 4 ore
`1238542865–1238557265` (91 finestre clean). I loro controlli null non
vanno trattati come tre misure indipendenti della coda.

## Cross-check del catalogo pubblico

La [query ufficiale GWOSC per GPS nel range dei target](https://gwosc.org/eventapi/jsonfull/query/show?min-gps-time=1238507872&max-gps-time=1253581952),
letta il 2026-09-27, restituisce 129 versioni di eventi; nessuna ha il
GPS catalogato dentro una delle 11 distinte finestre target di 32 s. Come
controllo della sintassi, la stessa query ristretta attorno al GPS noto
1248242632 restituisce le tre versioni di GW190727_060333. Per il caso
H1/L1 a GPS 1243231936, quindi, non risulta una coincidenza con un evento
pubblico in quella finestra **nel catalogo interrogato**. L'assenza nel
catalogo non è prova di assenza di un segnale, né sostituisce una stima
indipendente del false-alarm rate o una revisione time-frequency.

## Gate ancora aperti

Questa è una **review documentale degli output congelati**, non una review
visuale delle 12 Q-transform (eseguita successivamente nel documento collegato),
né un controllo indipendente di tutti i
canali strumentali, del catalogo eventi o della significatività globale.
Il pooled p99 della coincidenza usa fino a otto shift per seed e non è una
correzione formale del look-elsewhere effect. Il PEM testa solo cinque
canali pubblici per detector; `NO_CORRELATION` non certifica che gli altri
sensori siano quieti. Nessun confronto O4a o promozione A2 è stato eseguito.
Prima di qualunque comunicazione esterna sui target, l'autore deve vedere
le evidenze time-frequency/strumentali e decidere se aprire una validazione
indipendente con criteri fissati prima di guardare nuovi outcome.
