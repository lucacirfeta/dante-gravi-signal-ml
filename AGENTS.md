# AGENTS.md — dante-gravi-signal-ml

## Contesto del progetto

Pipeline non supervisionata per anomaly detection e caratterizzazione di glitch
nei dati LIGO (O4a pubblici, solo H1/L1 — Virgo non ha partecipato a O4a,
nessuna claim che la includa). Embeddings patch-level DINOv2 su spettrogrammi
Q-transform, VQ reference indexing, Top-k MIL scoring, validazione statistica
via block-bootstrap. Autore unico: Luca Cirfeta. Tu (agente di produzione
codice) lavori qui; la revisione scientifica e metodologica è fatta
separatamente — alimentala con diff leggibili, non sostituirla.

## Stile di comunicazione — regola principale

Obiettivo: zero output che non serva a un'azione o una decisione. Non è un
log continuo — nelle sessioni lunghe il default è il silenzio operativo, non
la narrazione a intervalli regolari.

Rumore operativo (staging, merge, conferme step-by-step, progress %, annunci
"ora farò X" prima di un comando) non va narrato: il diff/output parla da sé.
A fine incremento riporta solo, in un unico messaggio: file modificati, esito
test (pass/fail con conteggi), blocker aperti.

**Fermati e chiedi conferma prima di procedere se la modifica tocca una
decisione con conseguenze scientifiche o strutturali** — soglie, criteri di
scoring, popolazioni di riferimento, parametri di validazione statistica,
promozione di un componente da sperimentale ad attivo, o qualunque cambio in
COSA viene misurato o COME viene validato. Presenta la scelta e le
alternative, non implementare e poi raccontare. Questa è un'eccezione rara e
delimitata, non un log: non genera output continuo, si attiva solo quando
serve davvero.

I punti nella sezione seguente sono istanze note di questo stesso problema
generale — un cambiamento nel *modo in cui un valore viene calcolato,
aggregato o confrontato*, anche senza toccare una costante nominata, che
altera l'interpretazione scientifica. La lista documenta errori già
commessi, non è esaustiva: se una modifica nuova, non elencata, ha lo stesso
effetto, vale la stessa regola di stop-and-ask.

In caso di dubbio se una modifica rientri tra quelle da segnalare prima di
procedere, trattala come tale — il costo di una domanda in più è basso, il
costo di un'assunzione statistica implementata silenziosamente non lo è.

## Vincoli non negoziabili (causa di errori già commessi in passato)

- Bootstrap: sempre block-based, mai i.i.d.
- Statistiche intra-detector (Sintra) e soglie cross-detector (τ_coh) non
  sono mai confrontabili direttamente — costruzioni nulle diverse
  (within-pool vs bipartita L1/H1). Se un test o una funzione li mette a
  confronto, è un bug: fermati e segnala, non "correggere" silenziosamente.
- Nessuna costante numerica (K, k, soglie) hardcoded o dedotta dal contesto
  della chat: sempre dal config versionato del repo. Se il config e la
  richiesta divergono, la fonte di verità è il config — segnala la
  discrepanza, non risolverla a modo tuo.
- Whitening sempre prima del cropping del Q-transform, con pad di contesto.
- known glitches e injections: gate/soglie separati per morfologia, mai
  aggregati — un filtro può comportarsi diversamente su ciascuna morfologia.
- PEM-EX_VMON, PEM-EY_MAINSMON esclusi dalla coerenza (FPR elevato su
  background time-shifted) — non reintrodurli senza discussione esplicita.

## Convenzioni tecniche

- Commit: Conventional Commits. Nessun push su main senza diff revisionabile
  separatamente da un umano — non fondere nella stessa risposta in cui scrivi
  il codice.
- Test di regressione verdi prima di procedere all'incremento successivo.
- Qualunque modifica a un valore di config citato nel paper (K, k, soglie di
  produzione) richiede una entry in CHANGELOG.md con riferimento alla
  versione arXiv/Zenodo corrispondente, prima del merge.
- Non riusare silenziosamente output di run precedenti se cambia
  l'interpretazione scientifica dello schema: archivia la run precedente e
  rilanciala da zero.
- Se un test dipende da un hash di provenance e non coincide: fermati a
  diagnosticare, non bypassare il controllo.

## Note per sessioni lunghe

- Usa `/compact` a metà sessione se sta accumulando molta storia, invece di
  lasciarla crescere fino a fine task.
- Se una suite di test richiede più tempo del timeout del terminale, verifica
  che il processo sia ancora attivo invece di ripetere aggiornamenti di stato
  intermedi.