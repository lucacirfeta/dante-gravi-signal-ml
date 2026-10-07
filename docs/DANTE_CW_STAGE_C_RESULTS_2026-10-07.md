# CW: diagnostica appaiata RGB → DINO → score, 7 ottobre 2026

## Esito e perimetro

Esecuzione unica conclusa con **OS exit0**, osservato sia nel supervisore
terminale49628 sia nel log durevole `RUN_EXIT_CODE=0`. Freeze locale
`5b16082b96cbd3493e7668bb67329d501801c25f`. Status:
`COMPLETE_DESCRIPTIVE_SYNTHETIC_INFERENCE_ONLY`.

Output: `/home/atafe/dante_bench/cw_stage_c_20261007/run_v1` su Linux ext4.
Summary SHA256: `6ffb8ad691e16c8862c5112aed1c91eae9b00e2c9cb374e3415f4017ccf61aac`.
Supervisore/stdout/stderr sono nella stessa cartella padre, prefisso `run_v1`.
2.896 immagini esistenti: 16 rumori di base + 2.880 bracci a tono singolo,
18 frequenze × 5 dosi × 2 fasi × 16 rumori. I 384 probe a due toni di Stage A
restano esclusi da questo esperimento, come nel piano approvato.
9 re-encode di tre ingressi base, 120 confronti fra rumori indipendenti,
2.905 file di token conservati; 6.115.235.301 byte di artefatti nella run.

Nessuno strain reale, nuovo preprocessing, training, download, calibrazione,
soglia o flag. DINO/scorer invariati; reference O3b storica usata soltanto
come comparatore diagnostico, **non qualificata come reference 16k/O4b**.
Questo risultato non dimostra equivalenza, innocuità delle CW reali,
assenza di cambiamenti decisionali o readiness O4b.

## Metodo e runtime osservati

Immagini Stage A uint8 RGB già conservate; stesso rumore per ciascuna coppia,
associazione verificata per ID e SHA della baseline. Ingresso al DINO esistente,
patch token normalizzati float32, 1.369 patch × 384 dimensioni. Score effettivo
del PatchScorer esistente: media delle 68 patch più anomale rispetto al massimo
coseno dei centroidi. Batch32 ereditato dal protocollo versionato.
Reference SHA: `9053477ed2f30ed866fc42ff32265957e6a0eb93238032359f5e45e2f032bb7c`.

Per centroidi congelati, in aritmetica esatta:
`|Δscore| ≤ max_norm_centroid × mean_top68(||Δtoken_patch||₂)`.
È un limite patch-level, non sulla rappresentazione MIL aggregata a posteriori.
Tutti i 2.880 bracci hanno eccesso aritmetico osservato zero; il limite è spesso
molto conservativo e non è un criterio di accettazione scientifica nuovo.

Linux WSL2 6.6.114.1, Python3.11.15, Torch2.12.1+cu130, CUDA13.0,
RTX5070/driver617.14, precisione matmul `highest`, TF32 matmul disabilitato.
Algoritmi deterministici globali non abilitati. Runtime completo e provenienza
del modello sono nel summary. GPU utilizzata realmente (58% in uno snapshot),
non un benchmark di massima saturazione. Stderr: tre warning upstream xFormers
non disponibile, nessuna eccezione. Nessun controller resta attivo a fine run.

## Risultato sulla dose minima testata: 0,01

Tra le 512 coppie in banda, tutte presentano Δscore nonzero; tutte superano
il massimo spostamento di score osservato nei re-encode dei **soli tre** ingressi
di controllo. Mediana |Δscore| `1,553446e-4`, massimo `2,936482e-3`.
Il massimo re-encode osservato è `2,682209e-7`: confronto descrittivo, non un
limite universale di rumore numerico, né un test di equivalenza o significatività.

Ogni riga sotto comprende 16 rumori. Le fasi sono riportate separatamente;
il segno può cambiare fra rumori e non va nascosto con la sola media netta.

| Frequenza Hz | Fase | Mediana Δscore | Mediana abs(Δscore) | Min / max Δscore | Mediana limite patch |
|---|---|---|---|---|---|
| 26,32165 | 0 | −1,696795e-4 | 4,325658e-4 | −1,208127e-3 / +1,350343e-3 | 4,331292e-2 |
| 26,32165 | π/2 | −3,784895e-6 | 7,370859e-4 | −1,068771e-3 / +2,539366e-3 | 4,450621e-2 |
| 265,57454 | 0 | +2,746284e-5 | 1,003146e-4 | −4,024804e-4 / +3,217757e-4 | 2,051000e-2 |
| 265,57454 | π/2 | +1,910329e-5 | 1,604110e-4 | −9,699762e-4 / +2,641082e-4 | 2,068597e-2 |
| 1991,09216 | 0 | +1,058877e-4 | 2,476275e-4 | −7,107556e-4 / +1,170456e-3 | 1,084279e-2 |
| 1991,09216 | π/2 | +6,476045e-5 | 1,196861e-4 | −4,790723e-4 / +3,598034e-4 | 1,055102e-2 |

La minore modifica RGB a 1991Hz non si traduce automaticamente in una modifica
di score più piccola che a 265Hz. Non si può propagare il solo MAD dei pixel
allo score mediante una proporzione o una legge √dose presunta.

Controlli fuori banda, sempre dose0,01:

- 12,42562Hz: mediana Δscore zero per entrambe le fasi, ma mediana |Δscore|
  `1,981854e-6` / `2,980232e-7`; massimo assoluto `3,901124e-5`.
  Non è un nullo esatto per ogni ingresso; il risultato non identifica da solo
  il meccanismo di questa risposta residua.
- 2991,09216Hz: token e Δscore identici alla base in tutte le 32 coppie.

## Dose-risposta descrittiva

512 coppie in banda per dose. Mediane aggregate non sono curve monotone
individuali, non stimano la dose reale e non giustificano extrapolazioni.

| Dose | Mediana abs(Δscore) | Min / max Δscore |
|---|---|---|
| 0,01 | 1,553446e-4 | −2,936482e-3 / +2,539366e-3 |
| 0,1 | 3,486723e-4 | −9,551167e-3 / +8,354574e-3 |
| 1 | 5,168617e-4 | −4,111940e-2 / +4,984897e-2 |
| 10 | 8,906424e-4 | −4,117969e-2 / +5,366054e-2 |
| 100 | 1,026556e-3 | −4,104096e-2 / +5,049068e-2 |

Sull'intero esperimento: 1.252 Δscore negativi, 1.450 positivi, 178 nulli.
Nessuna soglia calibrata o decisione binaria è stata applicata.

## Ripetibilità e rumori indipendenti

I due forward singoli dello stesso ingresso producono token byte-identici
per ciascuno dei tre ingressi. Rispetto al batch principale, i forward singoli
hanno |Δscore| fra `2,980232e-8` e `2,682209e-7`; la massima distanza patch
osservata è `5,930262e-6`. Il re-encode con batch3 coincide esattamente con
il batch principale per tutti e tre. È evidenza della dipendenza numerica
dalla geometria del batch nel runtime osservato, non una prova cross-hardware.

Fra le 120 coppie di rumori di base, mediana |Δscore| `2,032320e-2`, intervallo
`3,603101e-5`..`6,942683e-2`. Le coppie condividono gli stessi 16 rumori:
non sono 120 repliche indipendenti, non costituiscono un placebo per il margine
confermativo appaiato e non certificano che una perturbazione minore sia innocua
vicino a una soglia decisionale.

## Verifiche e prossimo checkpoint

Pre-run: 16 test fixture PASS/1,83s/OS0, Ruff lint e format-check3file PASS.
Post-run finale standalone: stessi nuovi 16 test PASS/1,81s/OS0, Ruff lint PASS.
Controllo read-only OS0: hash dei sei artefatti collegati al summary e di tutti
i 2.905 token, geometria/finiteness dei 2.896 token principali, sei ricalcoli
campionati delle metriche dai token conservati; nessun secondo forward.
Config/module/script e pin parent/scientifici invariati. Nessun failure,
partial/tmp o lock. Le ricevute di ingresso sono legate da un inventario nuovo
prima del forward; il vecchio summary Stage A non è chiamato un seal storico
di tutte le ricevute.

La diagnostica approvata è conclusa. Non aggiungiamo automaticamente altri
esperimenti CW. La readiness O4b è separata nel documento
`DANTE_O4B_READINESS_CHECKPOINT_2026-10-07.md`: metodo/reference16k, popolazioni
e contratti eseguibili, calibrazione/validazione e installazione scientifica
sono i prossimi gate. Stage B resta disabilitato; nessuna promozione o run O4b.
