# O4b: prossimo contratto scientifico, 8 ottobre 2026

## Stato verificato oggi

HEAD iniziale480df74; branch science/o3-transfer-readiness, solo output/ e
artifacts/dante_workflow/public_smoke_v1/ untracked, preservati.
Ultimo push registrato del branch: 29 settembre2026 ore20:18:02 Europe/Rome,
commit ae9395a1d140ebb4add6f43556d9fdaac950a203. Lettura live git ls-remote
conferma lo stesso tip remoto; 131commit locali in più prima di questo documento.
Non è stata eseguita alcuna fetch/push/merge o modifica del remoto.

08.51 concluso nel perimetro sintetico descrittivo. Nessun nuovo esperimento
CW viene introdotto qui. Nessuna claim di innocuità delle CW reali.
Nel registro O4b method_contract e workflow_contract restano null.
Il vecchio verifier interrotto exit254 resta nonverificato, senza retry.

## Già approvato: non viene richiesto nuovamente

- Ingresso ed elaborazione nativi16.384Hz, non resampling a4096Hz.
- Banda di analisi Q20–2048Hz, CW annotata senza veto globale.
- Virgo con propri artefatti/reference/calibrazione/null e ramo separato;
  nessun trasferimento del nullH1/L1 né coerenza a tre detector implicita.
- Calcolo e dati di lavoro Linuxext4; E: per raw/archivio/backup.
- Test/freeze prima delle esecuzioni; commit locali, niente push/main/O4b.

Queste approvazioni non selezionano GPS, DQ o membri delle popolazioni e non
trasformano StageA/C in qualificazione del metodo produttivo.

## Decisione primaria: cosa vogliamo misurare su O4b?

L'indice primario storico del protocollo produttivo è O3b, SHA
9053477ed2f30ed866fc42ff32265957e6a0eb93238032359f5e45e2f032bb7c.
Il protocollo attuale è4096Hz. Riutilizzare questo NPZ come se fosse già
qualificato per16k non è autorizzato, né supportato dalla sola diagnostica CW.

| Percorso proposto, non adottato | Reference | Domanda scientifica |
|---|---|---|
| A: trasferimento controllato | Ricostruire la reference storica dalle stesse identità di training, con nuova catena16k qualificata; nuovo artefatto, non overwrite dell'indice4k | Come si comporta su O4b una rappresentazione/reference appresa su un altro periodo? |
| B: adattamento a O4b | Costruire una reference nuova da un sottoinsieme O4b approvato e disgiunto da calibrazione/evaluation | Come si comporta su dati O4b nuovi una pipeline adattata al rumore O4b? |

Raccomandazione condizionale: **A se l'obiettivo principale resta il
trasferimento multi-run**; B è legittimo ma va descritto come adattamento,
non come prova dello stesso trasferimento. Non serve fare entrambi di default.
È una distinzione del disegno sperimentale, non un risultato numerico nuovo.

A richiede prima prova delle identità/provenienza della reference storica e
della disponibilità dei contesti sorgente16k. Non sono state verificate qui.
Se mancano, fermarsi: niente sostituzione con una popolazione "simile",
ricostruzione dedotta dai centroidi o fallback silenzioso aB. Non si riapre O3a:
eventuali nuovi artefatti di reference restano isolati dalle run pubblicate.
L'eventuale ricostruzione cambia il preprocessing di training e va qualificata;
non promette token/score identici al vecchio indice né un campionamento isolato
da tutte le differenze nella banda alta.

In entrambi i percorsi: stesso modello DINO congelato e definizione di scoring
dal config versionato salvo nuove approvazioni esplicite; nuova calibrazione
O4b e validazione pertinenti, nessun trapianto di score/soglie/null precedenti.
La collocazione temporale delle popolazioni si congela prima di leggere score;
se B, anche reference e calibrazione/evaluation O4b devono essere disgiunte.
Separazione dei contesti completi, non soltanto degli istanti centrali.

## Quale catena16k proporre per la qualificazione

Proposta, non promozione: mantenere le primitive già caratterizzate in StageA,
senza notch CW, sottrazione delle righe o variazioni di normalizzazione:

- Contesto40s, analisi32s e pad4s per lato dalla configurazione StageA.
- Whitening sul contesto della singola finestra prima del crop; PSD stimata
  per braccio, non una PSD "pulita" scelta dopo il risultato.
- Ordine esplicito del chiamante StageA: contesto padded → whitening →
  bandpass sul contesto → estrazione della finestra di analisi → Q-transform
  → resize/min–max/colormap RGB. L'inferenza successiva usa il preprocessing
  DINO esistente, come nella diagnostica StageC. Non viene cambiato qui.
- Filtro StageA/GWpy Chebyshev I, gpass2/gstop30, filtfilt SOS;
  bandpass20–2000Hz. Ordine/coefficienti effettivi vanno registrati dal runtime,
  non inventati o fissati per deduzione dal nome del filtro.
- Qrange4–64, Qfrange20–2048Hz, min–max per immagine, cividis uint8 RGB,
  trasformazione DINO come nelle primitive/config congelate.

**20–2000Hz del filtro non è 20–2048Hz del Q-transform.** Confermare la catena
attuale significa mantenere esplicita questa distinzione, non certificare
guadagno fisico uniforme fino2048Hz. Estendere il filtro a2048Hz cambierebbe
il comportamento misurato e richiede una scelta separata; non lo faccio qui.
La maggiore frequenza Nyquist a16k impedisce di trattare la parte alta come
numericamente equivalente al4k storico. I lavori storici restano nel loro scope.

## Sequenza dopo la decisione, non una run già autorizzata

1. Verificare disponibilità/provenienza della reference scelta e scrivere il
   contratto metodo16k isolato, ancora senza promozione di default.
2. Presentare l'allocazione concreta GPS/DQ/reference/calibrazione/evaluation
   dal metadata snapshot conservato; nessuna selezione attraverso gli score.
   O4b_16KHZ_R1 è la release candidata già inventariata, non automaticamente
   un'ammissione scientifica definitiva. Definire validazione/morfologie,
   estimator/null e criteri dai config/approvazioni, mai dalla chat per deduzione.
3. Test/negativi, freeze, esecuzioni isolate e verifiche della catena approvata;
   poi percorso scientifico installato/CLI/UI e preflight finale O4b.
4. Chiedere l'avvio O4b separatamente, dopo la readiness. V1 non viene incluso
   per disponibilità del catalogo e non blocca automaticamente un futuro scope
   H1/L1 approvato. Nessun esperimento CW aggiuntivo imposto automaticamente.

## Checkpoint da approvare

Scegliere A (transfer) oppure B (adattamento); confermare se per la qualificazione
16k manteniamo la catena StageA20–2000/Q20–2048 descritta sopra.
Non approva GPS/DQ/popolazioni numeriche, margini CW, promozione o lancio O4b.
Nessun config scientifico attivo o sorgente congelato è stato modificato.
