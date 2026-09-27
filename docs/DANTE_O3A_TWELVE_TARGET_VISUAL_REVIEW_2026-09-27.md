# O3a: revisione visiva dei 12 target PEM

Data: 2026-09-27 Europe/Rome. Stato: **review diagnostica dei 12 target
completata; attribuzione causale e validazione indipendente non dimostrate**. Questa revisione non
aggiunge classi, soglie, ranking o decisioni di promozione. I conteggi e i
verdetti originali sono nel [ledger review](DANTE_O3A_TWELVE_TARGET_LEDGER_REVIEW_2026-09-27.md).

## Materiale verificato e limiti della figura

Sono stati riacquisiti gli 11 frame GWOSC O3a 4 kHz R1 citati nei 12 target.
Tutti gli SHA-256 e le dimensioni dei frame coincidono con le sorgenti congelate.
Il replay dei 12 contesti grezzi da 40 s e delle 12 immagini Q-transform produce
esattamente gli SHA-256 nei ledger di coincidenza e PEM. Sono stati usati il
contratto di coincidenza O3a v2 (digest
`05565c848b08efda6d71b7acf434809f93e5db638d623ca994824d1e520d991a`),
whitening prima del crop con 4 s di contesto e il Q-transform di produzione.
L'intervallo richiesto dal contratto è 20–2048 Hz; GWPy, con questo sampling e
Q-range, termina effettivamente a 1291,05 Hz, come nella run originale.

- [Dodici finestre complete, 20–1291 Hz](o3a_visual_review/o3a_12_targets_contact_full_allfreq.png)
- [Dodici finestre complete, dettaglio 20–200 Hz](o3a_visual_review/o3a_12_targets_contact_full_20_200hz.png)
- [Dettaglio di 5 s attorno alla localizzazione Top-k, 20–200 Hz](o3a_visual_review/o3a_12_targets_contact_20_200hz.png)
- [Receipt di replay e SHA-256 delle figure](o3a_visual_review/o3a_12_targets_visual_receipt.json)

La linea tratteggiata indica la mediana temporale dei patch Top-k **già
congelata**, non il picco del segnale né un tempo d'arrivo fisico. Il dettaglio
20–200 Hz è solo un crop di visualizzazione. I colori sono normalizzati per
immagine: la luminosità non confronta ampiezze tra detector o target. Lo script
di presentazione, separato dai sorgenti di produzione, resta con i frame
temporanei in `E:\dante_cache\dante_light\o3a_native_v1\visual_review_12_targets`;
SHA-256 dello script: `4ca7ea59fcacb518b022249113df79f467240a7ee1e08557ffdb5de6db2aea21`.

## Osservazioni per finestra (descrittive, non nuove etichette)

| Detector | GPS | Osservazione visiva | Limite immediato |
| --- | ---: | --- | --- |
| L1 | 1238507872 | Archi ripetuti a poche decine di Hz | Causa non verificata |
| L1 | 1238508320 | Più archi bassi nella stessa finestra | Causa non verificata; background PEM condiviso con altre due finestre L1 |
| L1 | 1238515136 | Archi bassi multipli | Non supera il proprio null per-evento |
| L1 | 1239175264 | Archi bassi multipli | Non supera il proprio null per-evento |
| L1 | 1239628448 | Impulso verticale ben visibile circa 3 s dopo l'inizio | Mediana Top-k circa 25,5 s: localizzazione e caratteristica visiva dominante non coincidono; motivo non determinato |
| L1 | 1241808544 | Archi bassi ripetuti | Causa non verificata |
| H1 | 1243231936 | Impulso verticale attorno a 22,6 s | Stessa finestra L1, non ritardo fisico misurato |
| L1 | 1243231936 | Impulso verticale attorno a 22,6 s | Stessa finestra H1, non prova di sorgente comune |
| H1 | 1245414400 | Arco basso intorno a 25 s | Seed AMBIGUOUS: solo diagnostico |
| L1 | 1247267872 | Archi bassi multipli | Non supera il proprio null per-evento |
| L1 | 1253362624 | Archi bassi multipli | Non supera il proprio null per-evento |
| H1 | 1253581920 | Arco basso intorno a 10–12 s; altra struttura sottile prima nella finestra | PEM COUPLED a 390,5 Hz, fuori dalla banda Top-k 20–92,5 Hz: non dimostra che il coupling spieghi l'arco |

Gli archi a bassa frequenza ricordano **visivamente** la morfologia di
scattered light descritta nel [catalogo ufficiale O3](https://ligo.org/science-summaries/o3acatalog/).
Questa è un'ipotesi per orientare controlli indipendenti, non un'assegnazione
Gravity Spy né una misura della causa. Anche gli impulsi verticali possono
essere glitch, altre perturbazioni strumentali o, in linea di principio,
segnali nello strain: l'immagine non distingue queste possibilità da sola.

## Incrocio descrittivo con il catalogo pubblico Gravity Spy

I CSV originali [Gravity Spy O3a su Zenodo](https://zenodo.org/records/5649212)
sono stati letti per H1 e L1, con dimensioni e MD5 identici al record
pubblicato (`H1_O3a.csv`: 90.238.691 byte,
`29aea278b622cd97496971f7c07f7d6a`; `L1_O3a.csv`: 142.258.875 byte,
`3d3d0409817499c84fb2e0a2b211b5a5`). L'incrocio usa soltanto
`event_time` Omicron nella finestra congelata `[GPS, GPS+32 s)`, senza
introdurre un'associazione automatica con il patch Top-k. Sono 24 trigger
in 10 delle 12 finestre:

| Detector | GPS | Trigger Omicron nella finestra: etichette ML Gravity Spy |
| --- | ---: | --- |
| L1 | 1238507872 | 1 Low_Frequency_Lines |
| L1 | 1238508320 | 1 Scattered_Light |
| L1 | 1238515136 | 4 Scattered_Light |
| L1 | 1239175264 | Nessuno nel catalogo |
| L1 | 1239628448 | 1 Extremely_Loud, 3 Fast_Scattering |
| L1 | 1241808544 | 4 Scattered_Light |
| H1 | 1243231936 | 1 Koi_Fish |
| L1 | 1243231936 | 1 Extremely_Loud |
| H1 | 1245414400 | 3 Scattered_Light |
| L1 | 1247267872 | Nessuno nel catalogo |
| L1 | 1253362624 | 3 Scattered_Light |
| H1 | 1253581920 | 2 Scattered_Light |

Le 17 occorrenze `Scattered_Light` in sei finestre rendono l'ipotesi
morfologica più concreta, ma Gravity Spy osserva **gli stessi dati strain**
tramite un'altra pipeline: non è una conferma fisica indipendente, né prova
che la classificazione descriva il patch selezionato da DANTE. L'assenza di
trigger nelle altre due finestre vale solo rispetto ai criteri di inclusione
Omicron/Gravity Spy del catalogo (in particolare SNR > 7,5).

Due verifiche temporali sono particolarmente informative. A GPS 1243231936,
i trigger H1 `Koi_Fish` e L1 `Extremely_Loud` hanno tempi
`+22,629 s` e `+22,660 s`; sono vicini ai rispettivi Top-k, ma differiscono
per etichetta e il divario dei picchi Omicron non è una misura del ritardo
fisico fra detector. A L1 GPS 1239628448, il trigger `Extremely_Loud`
coincide con l'impulso visivo a `+2,975 s`, mentre il Top-k congelato è a
`+25,514 s`: l'incrocio rafforza la necessità di un audit della
localizzazione, senza identificare ancora cosa abbia selezionato il modello.
Nel caso H1 GPS 1253581920, un trigger `Scattered_Light` a 30,1 Hz e
`+11,375 s` è vicino al Top-k (`+10,811 s`), ma non riconcilia da solo il
picco PEM a 390,5 Hz.

## Audit dei flag pubblici di qualità e della localizzazione congelata

Nei medesimi 11 frame verificati sono stati letti direttamente i vettori
GWOSC HDF5 `quality/simple/DQmask` e `quality/injections/Injmask` alla
risoluzione di 1 s. Lo script di sola lettura è nello stesso scratch della
review visuale (SHA-256
`7b7ff38a68a9b5e1153bd6688f0dcaeea0dcd24b972d4e383870b64992f3eb61`),
e ricontrolla gli SHA-256 dei frame prima di leggere le maschere.
Secondo le [definizioni ufficiali O3](https://gwosc.org/O3/o3_details/),
il bit 1 indica che il secondo **passa** il relativo flag; CBC e BURST
sono categorie distinte. Tutte le 12 finestre passano `DATA`, `CBC_CAT1`
e `BURST_CAT1` per tutti i 32 s, in accordo con la popolazione CBC_CAT1
congelata. Le violazioni delle categorie più restrittive sono:

| Detector | GPS | Secondi che non passano CBC_CAT2/3 | Secondi che non passano BURST_CAT2/3 |
| --- | ---: | --- | --- |
| L1 | 1238507872 | +18–20 | +18–20 |
| L1 | 1238508320 | Nessuno | Nessuno |
| L1 | 1238515136 | +23–24 | +23–24 |
| L1 | 1239175264 | Nessuno | +17–21, +29–31 |
| L1 | 1239628448 | Nessuno | +1–5 |
| L1 | 1241808544 | Nessuno | Nessuno |
| H1 | 1243231936 | Nessuno | +21–23 |
| L1 | 1243231936 | Nessuno | +20–24 |
| H1 | 1245414400 | Tutti i 32 s | +2–7, +19–21 |
| L1 | 1247267872 | Nessuno | Nessuno |
| L1 | 1253362624 | Nessuno | Nessuno |
| H1 | 1253581920 | Nessuno | +4–9 |

Quindi 8/12 finestre contengono almeno un secondo che non passa
`BURST_CAT2/3`, e 3/12 almeno uno che non passa `CBC_CAT2/3`.
La finestra comune GPS 1243231936 ha il fallimento BURST in **entrambi**
i detector proprio attorno agli impulsi a `+22,6 s`. Anche l'impulso forte
L1 GPS 1239628448 a `+2,975 s` cade nel tratto BURST non valido. È una
convergenza fra forma visiva, trigger Omicron e flag DQ pubblico, ma non
specifica la causa del disturbo. Non si retrocede né si elimina un seed:
il contratto selezionava intenzionalmente `CBC_CAT1`, non `BURST_CAT2`.

I bit `NO_CBC_HW_INJ`, `NO_BURST_HW_INJ` e `NO_DETCHAR_HW_INJ` sono attivi
per tutti i 32 s di tutte le finestre; `NO_CW_HW_INJ` non lo è in nessuna.
Questo stato va distinto da un'iniezione hardware transiente, e non è una
spiegazione specifica dei 12 target.

L'ispezione degli indici Top-k sigillati chiarisce la discordanza L1 GPS
1239628448 senza modificare lo scoring. Dei 68 patch selezionati, soltanto
tre cadono nelle righe temporali 3–4 (circa `+3,0–3,9 s`), ai ranghi
53, 63 e 68; i primi dieci patch per anomalia sono invece in righe
temporali 23–34. La mediana Top-k a `+25,514 s` segue esattamente la
regola congelata (`row = index // 37`): non è un errore aritmetico di
coordinate, ma la sintesi di più regioni anomale in una sola finestra.
Resta aperto *perché* il modello attribuisca rango più alto alle regioni
tardive rispetto all'impulso molto visibile.

Il `COUPLED` H1 GPS 1253581920 è calcolato con coerenza spettrale sull'intera
finestra di 32 s (FFT da 2 s, banda 20–500 Hz); non produce un tempo del
massimo. Pertanto il picco PEM a 390,5 Hz **non è stato associato nel tempo**
all'arco strain/Top-k intorno a `+11 s`. Per la coppia H1/L1 GPS 1243231936,
il ledger contiene due correlazioni sopra i rispettivi null locali, ma
usa subfinestre di 1 s centrate separatamente a `+22,486 s` e `+22,919 s`
e bande distinte. Entrambe le subfinestre di correlazione cadono interamente
nei rispettivi tratti che non passano `BURST_CAT2/3`. Il valore massimo della
correlazione entro il lag ammesso
non registra il lag stesso; i tempi di picco Omicron non lo sostituiscono.
I sorgenti di coincidenza e PEM consultati per questa lettura coincidono
byte-per-byte con gli SHA-256 congelati nei rispettivi contratti.

## Chiusura diagnostica, record per record

La tabella distingue un flag DQ **in qualunque punto dei 32 s** dalla sua
sovrapposizione con la subfinestra di correlazione congelata di 1 s,
`[t_Top-k − 0,5 s, t_Top-k + 0,5 s)`. I flag pubblici sono campionati a 1 Hz:
questa è una verifica di intersezione temporale, non un nuovo veto e non una
prova di causalità. Un'etichetta Gravity Spy nella stessa finestra osserva
lo stesso strain e non identifica necessariamente il patch Top-k. Il null
locale è quello preregistrato nel ledger, non una nuova stima statistica.

| Record | Evidenza diagnostica pertinente | Cosa resta non dimostrato |
| --- | --- | --- |
| L1 1238507872 | CBC_CAT2/3 e BURST_CAT2/3 non passano anche nella subfinestra Top-k (`+20,324 s`); archi bassi. Null locale superato. | Quale disturbo abbia prodotto gli archi; l'etichetta `Low_Frequency_Lines` è lontana dal Top-k. |
| L1 1238508320 | DQ CAT2/3 integro nei 32 s; archi bassi, null locale superato. | Nessuna causa strumentale verificata. Il trigger `Scattered_Light` è a `+2,625 s`, lontano dal Top-k `+16,865 s`; è un'ipotesi morfologica, non una spiegazione del patch. |
| L1 1238515136 | Archi bassi; CBC/BURST CAT2/3 non passano a `+23–24 s`, **dopo** la subfinestra Top-k `+22,054 s`. Null locale non superato. | Il DQ vicino non identifica causalmente il patch; trigger `Scattered_Light` nella finestra non è una conferma indipendente. |
| L1 1239175264 | Archi bassi; BURST_CAT2/3 non passa in due tratti lontani dal Top-k `+25,514 s`. Null locale non superato. | Causa degli archi; nessun trigger Gravity Spy catalogato nei 32 s. Il DQ della finestra non spiega la struttura selezionata. |
| L1 1239628448 | Impulso visivo a `+2,975 s` dentro BURST_CAT2/3 non valido; Omicron `Extremely_Loud` allo stesso tempo. Solo 3/68 patch Top-k sono lì, ai ranghi 53/63/68; null locale del seed superato. | Perché il modello privilegia regioni tardive e cosa sia la struttura alla mediana Top-k `+25,514 s`, dove il DQ passa. Il flag è un avviso sull'impulso, non automaticamente la spiegazione della selezione DANTE. |
| L1 1241808544 | DQ CAT2/3 integro nei 32 s; archi bassi, null locale superato. | Nessuna causa strumentale verificata. I quattro trigger `Scattered_Light` nella finestra sono lontani dal Top-k `+18,162 s`; somiglianza visiva non equivale ad attribuzione. |
| H1 1243231936 | Impulso a `+22,629 s`; BURST_CAT2/3 non passa nella subfinestra Top-k `+22,486 s`. Null locale superato. | Causa del veto e ritardo fisico rispetto a L1; PEM `NO_CORRELATION` sui cinque canali pubblici non assolve altri accoppiamenti. |
| L1 1243231936 | Impulso a `+22,660 s`; BURST_CAT2/3 non passa nella subfinestra Top-k `+22,919 s`. Null locale superato. | Stesse limitazioni di H1. Il doppio fallimento BURST contestuale è il più diretto indizio di una spiegazione ordinaria/strumentale fra i target, **non** prova di un'unica causa ambientale condivisa. |
| H1 1245414400 | CBC_CAT2/3 non passa in tutti i 32 s, anche al Top-k `+24,649 s`; trigger `Scattered_Light` vicino (`+25,125 s`). Seed `AMBIGUOUS`, solo diagnostico. | Causa specifica dell'arco; BURST_CAT2/3 non passa altrove, non nella subfinestra selezionata. |
| L1 1247267872 | DQ CAT2/3 integro; archi bassi, nessun trigger Gravity Spy catalogato. Null locale non superato. | Causa non identificata, ma l'evidenza statistica è più debole: sola soglia pooled diagnostica. |
| L1 1253362624 | DQ CAT2/3 integro; archi bassi, trigger `Scattered_Light` a `+17,875 s` vicino al Top-k `+17,730 s`. Null locale non superato. | L'etichetta morfologica non prova la causa; sola soglia pooled diagnostica. |
| H1 1253581920 | Arco basso vicino a trigger `Scattered_Light` (`+11,375 s`); BURST_CAT2/3 non passa solo prima del Top-k `+10,811 s`. PEM `COUPLED` a 390,5 Hz sull'intera finestra. Null locale superato. | Il PEM non localizza il coupling nel tempo e non collega causalmente il picco a 390,5 Hz all'arco Top-k 20–92,5 Hz. |

La coppia GPS 1243231936 non è un candidato astrofisico sostenuto da questa
review: gli impulsi e le rispettive subfinestre di correlazione cadono
interamente in secondi che non passano BURST_CAT2/3 **in entrambi** i detector.
È un forte avviso diagnostico di qualità/strumento, non un veto retroattivo:
la popolazione era fissata su CBC_CAT1. Né i flag BURST né la coincidenza
visuale dimostrano una causa comune fra i siti.

In totale, 8/12 finestre hanno almeno un secondo BURST_CAT2/3 non valido,
ma soltanto **3/12 subfinestre Top-k** si sovrappongono a quei secondi
(L1 1238507872 e i due record GPS 1243231936). Una quarta subfinestra,
H1 1245414400, è in CBC_CAT2/3 non valido mentre BURST_CAT2/3 passa lì.
Quattro record sono CAT2/3 integri per l'intera finestra; fra loro,
**L1 1238508320 e L1 1241808544** superano il null locale e non hanno
una causa verificata né un trigger catalogato vicino alla struttura Top-k.
Restano quindi due residui descrittivi, non due candidati promossi: gli
archi sono compatibili visivamente con glitch/scattered light, ma questa
compatibilità non è un'identificazione strumentale. Gli altri due record
DQ-integri, L1 1247267872 e L1 1253362624, non superano il null locale.
H1 1253581920 e L1 1239628448 conservano inoltre domande di
localizzazione/causalità specifiche, senza che ciò aumenti la loro
significatività.

### Controllo leggero dei due residui L1

L1 1238508320 e L1 1241808544 sono separati da 3.300.224 s (38,20 giorni).
Nel manifest CBC_CAT1 O3a congelato appartengono a segmenti **distinti**:
`[1238500421, 1238517740)` e `[1241731918, 1241818103)` rispettivamente.
Entrambi usano il prodotto strain pubblico L1 O3a 4 kHz R1, ma la stessa
versione del prodotto non documenta uno stesso stato strumentale. Nei 32 s
selezionati entrambi passano CBC/BURST CAT2/3 e hanno `NO_CORRELATION` sui
medesimi cinque canali PEM pubblici. Il canale di massimo PEM è in entrambi
`L1:SUS-ETMX_L3_CAL_LINE_OUT_DQ`, ma i massimi sono **sotto** le rispettive
soglie e a frequenze diverse (120 e 249 Hz): il nome condiviso non è
un'identificazione causale.

Le immagini mostrano archi ripetuti a poche decine di Hz. Le bande di
coincidenza derivate dai patch Top-k sono 20–54,50 e 20–58,97 Hz; 33 delle
68 posizioni nella griglia dei patch coincidono, ma solo tre posizioni fra
i primi dieci per rango. Il confronto esplorativo sul ledger sigillato
`native_coincidence_robust.jsonl`, fra tutte le 36 coppie dei nove target
primari L1, trova altre cinque coppie con sovrapposizione
almeno pari: la somiglianza geometrica non è esclusiva dei due residui.
Questi sono controlli descrittivi degli output già sigillati, **non** un
test di somiglianza calibrato, una nuova soglia o una prova di un disturbo
L1 condiviso. La causa di entrambi rimane non verificata; nessun protocollo
temporale PEM o nuova significatività è stato eseguito.

## Cosa cambia e cosa non cambia

La review visuale e la matrice diagnostica aggiungono evidenza sulla
**forma** e sulla qualità temporale dei target, non significatività.
Rimangono 11 ROBUST primari e un AMBIGUOUS diagnostico;
quattro primari superano soltanto il pooled p99 diagnostico, non il proprio
null per-evento. Il caso H1/L1 a GPS 1243231936 ha un forte avviso BURST
contemporaneo; un'eventuale riapertura come evento fisico richiederebbe tempi
fisici e controlli indipendenti, non presenti qui. Il caso H1 1253581920
mantiene un limite strumentale specifico:
il flag PEM è verificato, ma il massimo di coerenza ausiliaria e la banda
localizzata dal modello sono diversi. Per L1 1239628448 va chiarito perché
la localizzazione Top-k cade lontano dall'impulso dominante visibile.

Nessuna delle 11 finestre GPS distinte coincide con un evento nel catalogo
GWOSC interrogato nel [ledger review](DANTE_O3A_TWELVE_TARGET_LEDGER_REVIEW_2026-09-27.md);
questo non esclude un segnale sotto soglia. Prima di una comunicazione esterna
su un target occorrono revisione strumentale più ampia, confronto di timing
fisicamente valido e una significatività di rete con controllo del
look-elsewhere effect definita prima di leggere nuovi outcome. Non si
modificano soglie, classi o criteri di selezione dopo questa ispezione.

## Confine della chiusura diagnostica

1. L1 GPS 1239628448: la mappa di coordinate Top-k è verificata. Il passo
   ancora aperto è capire il rango basso dei patch sull'impulso a `+3 s`
   rispetto alle regioni tardive, senza spostare il seed a posteriori.
2. Coppia H1/L1 GPS 1243231936: i DQ BURST pubblici non passano nei secondi
   degli impulsi in entrambi i detector. Prima di un'ipotesi di evento comune
   servirebbero documentazione strumentale più specifica e una procedura
   indipendente per il timing fisico; la correlazione attuale non la fornisce.
3. H1 GPS 1253581920: il `COUPLED` PEM è integrato su 32 s. Un'eventuale
   analisi PEM localizzata nel tempo richiederebbe un nuovo protocollo;
   l'attuale flag non diventa automaticamente spiegazione causale o veto.

La review dei 12 si chiude **come diagnostica**, non come attribuzione
causale esaustiva. I due residui DQ-integri con null locale superato
(L1 1238508320 e L1 1241808544) vanno mostrati all'autore se si valuta un
protocollo strumentale/timing dedicato; non giustificano automaticamente un
framework per tutti e 12. Qualunque nuovo test, ordinamento o stima di
significatività di rete e sensibilità richiede contratto scientifico fissato
in anticipo e approvato dall'autore. Non è avviato qui.
