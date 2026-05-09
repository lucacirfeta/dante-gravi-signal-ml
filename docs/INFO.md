Cosa esiste già:

Gravity Spy: classificatore supervisionato su classi note (Blip, Scattering, ecc.)
Autoencoder per anomaly detection su O3 (pubblicato)
SimCLR/contrastive learning su waveform grezze (pubblicato)
CNN binaria chirp vs glitch (pubblicato mille volte)

Cosa NON esiste ancora:

DINOv2 frozen applicato a spettrogrammi GW — non pubblicato
Pipeline open-source, laptop-friendly, zero labeled data, zero GPU training che scansiona O4a cercando morfologie sconosciute
Il gap che colmiamo è esattamente quello che la community ha esplicitamente identificato come priorità: trovare l'ignoto automaticamente, senza aspettare che un umano lo etichetti

La nostra onestà scientifica: al momento abbiamo 15 spettrogrammi anomalous su 6h di dati. È un segnale interessante, non una scoperta. Phase 3.1 ci dirà se regge. Se sopravvive su 48h e non è già in Gravity Spy, allora abbiamo qualcosa di concreto da condividere.

Spiegazione per chi non sa nulla
Immagina di dover ascoltare il silenzio dello spazio cercando un suono specifico.
Gli interferometri di LIGO e Virgo sono gli strumenti più sensibili mai costruiti dall'umanità. Sono tunnel lunghi 4 chilometri in cui un raggio laser rimbalza avanti e indietro migliaia di volte. Quando un'onda gravitazionale — una crepa nello spaziotempo generata da due buchi neri che si scontrano a miliardi di anni luce da noi — attraversa la Terra, distorce lo spazio di una quantità incredibilmente piccola: un millesimo del diametro di un protone. L'interferometro la rileva.
Il problema è che questi strumenti sono così sensibili da registrare letteralmente tutto: un camion che passa, un terremoto in Giappone, un'oscillazione della rete elettrica. Questi disturbi si chiamano glitch e assomigliano visivamente alle vere onde gravitazionali.
I fisici hanno costruito Gravity Spy — un sistema di intelligenza artificiale addestrato a riconoscere i 23 tipi di glitch conosciuti. Funziona bene, ma ha un limite strutturale: se appare un tipo di rumore mai visto prima, non lo riconosce. Lo butta in un cestino chiamato "Other" e aspetta che qualcuno lo trovi manualmente.
Noi costruiamo esattamente quello che Gravity Spy non può fare.
La nostra pipeline scarica i dati pubblici dell'interferometro, li trasforma in immagini colorate chiamate spettrogrammi, e usa un modello di intelligenza artificiale chiamato DINOv2 — addestrato da Meta su 142 milioni di immagini — per estrarre un "fingerprint visivo" da ogni immagine. Poi raggruppa automaticamente questi fingerprint cercando forme simili tra loro.
Il risultato è una mappa di tutto il rumore strumentale, dove i gruppi piccoli e isolati — quelli che non assomigliano a nulla di noto — sono i candidati interessanti. Non sappiamo ancora cosa siano. Potrebbero essere un nuovo tipo di glitch strumentale, oppure qualcosa di più interessante. Il passo successivo è verificarlo.
Il contributo concreto alla community è questo: chiunque, con un laptop e una connessione internet, potrà eseguire la nostra pipeline sui dati pubblici e cercare morfologie sconosciute — senza GPU costose, senza dati etichettati, senza dover essere un fisico. Abbassiamo la barriera d'ingresso per l'analisi indipendente delle onde gravitazionali.