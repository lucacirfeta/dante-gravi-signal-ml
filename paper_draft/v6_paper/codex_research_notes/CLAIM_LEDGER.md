# Claim ledger per il paper v6

Legenda: **READY** = pubblicabile con il wording indicato; **CONDITIONAL** =
pubblicabile solo con caveat espliciti; **WITHDRAW** = non usare come claim.
La fonte numerica prevalente è `MASTER_NUMBERS_V6.yaml` e i relativi artefatti
hashati. Il 7 agosto 2026 il gate finale ripete con esito PASS tutti i dieci
stage C2/BGV3, i cinque stage CQG (domain, known-glitch, absorption,
robustness e reviewer extensions), il claim checker di entrambi i manoscritti con ricostruzione hash,
il bundle portabile e 71 test finali focalizzati. La suite completa corrente è
270 PASS, 1 skip platform-dependent e 9 warning
classificati (xFormers opzionale e deprecazione GWpy).

| Claim candidato | Stato | Evidenza finale | Wording/azione |
|---|---|---|---|
| DANTE-Light exact replay | PUBLIC-REPLAY READY; non claim operativo del paper v6 | branch `codex/dante-light`, run commit `9669fab678ce08fd5eac818ea530cc1ba1591ae6`; clean paired L1 benchmark 1.15348 vs 1.30177 window/s (+12.856%); suite 270 PASS, 1 skip; C2 10/10 e CQG 5/5 PASS. Fresh HTTPS clone and Torch cache self-downloaded GitHub asset SHA256 `651a70d...fa63`, used GWOSC-only/CAT1, and completed 2/2 canonical/shared windows with zero DEFER/drop/failure, score delta 0 and identical dispositions. | descrivere come experimental exact historical replay con riproducibilità pubblica del piccolo replay. Epoche causali e validazione prospettica restano OPEN; nessun claim real-time/operational o miss-rate. Zenodo `21957984` contiene lo snapshot sorgente, non il bundle NPZ. |
| Catalogue timestamps pre-24/07 anticipati di 4 s | READY | riproduzione esatta 10/10 su `[G+4,G+36]` | bug di label, non di score |
| Catalogo detector-aware | READY | 10.429 chiavi detector+GPS; H1 4.411, L1 6.018; 10.372 score riusati con uguaglianza esatta e 57 nuovi | distinguere deduplica di ripetizioni dalla vecchia deduplica GPS-only |
| Coincidenza fisica | READY solo come screen conservativo con coverage caveat | 8.806/10.429 misurati, 1.623 storicamente non misurati; per evento massimo su 4--8 shift validi, poi P99 dei massimi pooled; 13 singoli on-source sopra \(\tau_{cc}=0.4046\) | on-source singolo e massimo-null per evento non sono exchangeable: nessun tail-count test o p-value; i 13 non ricevono interpretazione fisica da questo screen |
| Contratto Q64/Q64 | READY | join one-to-one detector+GPS: nel sottoinsieme storico paired 4.676/10.372 disposizioni differiscono dal contratto incoerente; matrice completa in `dsd_representation_transition_detector_aware.json` | rappresentazione di index, background e query è parte del modello; il precedente 4.558 era stale rispetto alle classi detector-aware |
| Tassonomia DSD | READY come disposizione statistica | 6.365 ROBUST, 1.275 AMBIGUOUS, 2.789 BACKGROUND; H1 2.227/562/1.622, L1 4.138/713/1.167 | non chiamare le classi morfologie o cause fisiche |
| Stabilità al background draw | READY solo come stabilità moderata di rango/score | P5, 80 ROBUST + 80 AMBIGUOUS, 4 draw: Spearman medio/minimo 0.6737/0.5147; score-std mediana 0.00757 | non usare il vecchio 0.979 e non riportare verdict agreement |
| Invarianza a K | WITHDRAW/rephrase | P4: rho vs K=1216 = 0.7525/0.7680/0.9428 per K=512/1024/2048; pairwise medio/minimo 0.7923/0.6452 | ranking sensibile a K; maggiore accordo a K=2048 |
| DINOv2 prova morfologia oltre loudness | CONDITIONAL | PCA AUC/rho 0.4363/-0.1579; energy AUC/rho 0.5438/0.0301; energy AUC H1/L1 0.5981/0.4900 | i baseline non spiegano il ranking, ma non provano causalità od ottimalità |
| Autoencoder GW-specifico conferma DANTE | WITHDRAW; controllo negativo READY | autoencoder convoluzionale detector-specific, 650 background/detector, tre seed, stessi 160 candidati: AUC pooled 0.4729 (seed 0.4732--0.4850), rho -0.0469; H1/L1 AUC 0.5284/0.4241 | il reconstruction error non riproduce la disposizione DANTE; non usarlo come conferma o misura di accuratezza fisica |
| Tassonomia insensibile alla lunghezza dei blocchi | CONDITIONAL | B=200.000 per cella, b=8/17/32/64: cambi non-overlap 46/1/42/140 e moving-block 86/43/7/148 su 10.429 | almeno 98.58% stabile nella griglia testata, ma le classi vicino ai confini dipendono da b e dallo schema; non dichiarare invarianza |
| Whitening context modifica i verdetti vicino alla soglia | READY con caveat forte | 60/66 candidati; swing mediano/massimo 0.0109/0.0738; 16/60 >0.02; flip fixed 40.0/40.0/36.7%, ricalibrati 63.3/70.0/65.0% a pad 16/64/128 | campione boundary-conditioned, non prevalenza survey-wide |
| Absorption C2 iniziale | CONDITIONAL/storico | Blip Q64, singolo seed: z 8.60, 3.60, 2.29, 0.89 a prevalenza 0, 2, 10, 40%; controllo same-size circa 8.2--8.8 | non usare come endpoint finale al posto della matrice replicata |
| Domain shift O3b→O4a | READY detector-dependent | controllo matched \(K=56\), 60 train + 40 held-out per run/detector, seed 20260730; H1 differenza media +0.03983, CI95% [0.02914,0.05184], run-probe AUC 0.9199; L1 -0.00290, CI95% [-0.01304,0.00823], AUC 0.6165 | shift risolto in H1 ma non L1 nel controllo held-out; \(K=56\) è distinto dai dizionari production \(K=275/1216\); non rendere universale la necessità di recalibration |
| Controllo esterno known-glitch | READY con scope O3b | AUC H1 Blip/Scattered/Koi 0.670/1.000/1.000; L1 0.523/0.988/0.993, 30 positivi per cella e 40 clean | construct validity morphology- e detector-dependent; non è recall O4a o classificazione multiclass |
| Absorption multi-morfologia | READY con caveat | peak amplitude 12 in unità whitened; durata Blip/Koi 1 s, Scattered Light 1.5 s; tre seed: crossing Blip 2--5%, Koi Fish 10%, Scattered Light 5% | absorption misurabile e morphology-dependent; ampiezza SNR-like, non matched-filter SNR; non `controllable` né costante production |
| Robustezza CQG replicata | READY come matrice distinta da P4/P5 C2 | background draw rho medio near/unconditioned 0.934/0.977; K-seed 0.954/0.988; K-value 0.903/0.978, con bootstrap CI | riportare popolazioni e protocolli separatamente; non sostituire silenziosamente P5 0.674 |
| Soglia universale di absorption 2--5% | WITHDRAW | flagged fraction 53% a 5% e 20% a 10% nel singolo setup | crossing condizionale, non costante production |
| ROBUST arricchita in coerenza aux | WITHDRAW; null READY | coorte fissa 141/141, 8 transizioni al rejoin; primario 2/26 vs 7/93, OR 1.024, Fisher p=1.0; AMBIGUOUS 1/22 | nessun arricchimento risolto; p alto non prova equivalenza |
| Time-shift PEM da solo identifica coupling | WITHDRAW | 48/141 positivi diagnostici, 38 falliscono il quiet zero-lag; time-shift p=0.2447 | usare sempre la regola a due null |
| Recupero eventi GWTC | WITHDRAW | 2 overlap, coverage proxy | non usare recall o efficienza |
| Nessun eccesso GWTC/DANTE | CONDITIONAL | 2 osservati, null 2.1899±1.4665, 95% [0,5], p=0.6508 | nessun eccesso risolto; coverage proxy |
| Nessuna morfologia ricorre | CONDITIONAL | R5 H1/L1 n=2.227/4.138; top-cross 0.9665/0.9610 vs 0.9706/0.9643; z=-7.72/-46.28 | nessuna recurrence positiva risolta dall'embedding, non assenza fisica |
| Blind spot universale sopra Q=64 | WITHDRAW/rephrase | mean flag 26.3% per Q≤64 vs 48.8% per Q>64; Q=2/4 sempre 0, n=8/cella | regione empirica low-Q e morphology-dependent, CI larghe |
| DANTE flags CBC in simulazione | READY con caveat | 375 trial; IMRPhenomD zero-spin non-precessing, cielo/orientazione campionati, iniezione raw, merger centrato, paired clean control; risultati per cella k/25 e Wilson 95%; soglie H1/L1 aggiornate | simulation-only, merger-centred by construction, non curva di efficienza reale; BNS non misurata |
| Rate limits v5 trasferibili | WITHDRAW | tassonomia e denominatori cambiati; nessun nuovo calcolo rate nel perimetro v6 | dichiarare il ritiro |
| Riproducibilità bitwise completa | WITHDRAW/rephrase | public clean-clone replay passa su 2 finestre con asset auto-scaricato, GWOSC-only e score delta 0; non è una ricostruzione completa dell'intero survey/raw corpus | parlare di riproducibilità pubblica del replay congelato, non di riproducibilità bitwise completa dell'analisi O4a |
| Bundle di evidenza v6 | PUBLISHED | dataset Zenodo `10.5281/zenodo.21925453`; 250 file nel payload allowlisted; ZIP 8,958,047 byte, MD5 `2b84a96f557629a8a2805c3c08feede4`, SHA256 `a04ef27a564ab356103eb1ae14031d14649359e884d571aa08a832bc822bd37c`; manifest e ZIP round-trip PASS; nessun raw/pilot/archive o figura superata | payload depositato congelato; non rigenerarlo dopo l'inserimento del DOI nei sorgenti di submission |

| Singleton L1 GPS catalogo 1382955228 | CONDITIONAL, unclassified | finestra reale 1382955232--1382955264; feature 1382955253.17; score Q64 0.598877 riprodotto nella figura a \(1.2\times10^{-7}\); 28 Hz e 304x; multiscale 4/4; coincidence 0.0716 sotto null mean/max 0.197/0.286; PEM 0.478 sotto 0.663/0.789 | transiente L1-local statisticamente ROBUST e non classificato; nessun counterpart H1 o coupling nel subset PEM pubblico risolto; non nuova glitch class e non esclusione di coupling non misurati |

## Claim centrale

Una pipeline unsupervised per strain non stazionario richiede controlli
empirici a ogni livello. Il domain shift e il beneficio della ricalibrazione
sono detector-dependent; l'adattamento nativo può assorbire anomalie ricorrenti.
I null fisici separano la novità statistica
dall'evidenza strumentale o astrofisica. I risultati supportano un framework di
triage e validazione, non una nuova glitch class né una ricerca astrofisica.
