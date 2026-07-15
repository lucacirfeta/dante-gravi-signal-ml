# Paper 5 Critical Review & Limitations (LIGO Standards)

## 1. Sommario Esecutivo
L'analisi aggregata sui dati O4a (dante-gravi-signal-ml) per la preparazione del Paper 5 conferma una classificazione completa del background.
Sono stati analizzati **10372 eventi** candidati.
Il sistema di veto e classificazione ha risolto tutti i trigger, riportando **0 anomalie fisiche non classificate** (`Unclassified_Physical_Anomaly`).

## 2. Punti di Forza Metodologici
- **Whitening & Padding:** L'uso sistematico di `whiten_context()` previene Gibbs ringing e difetti ai bordi (leakage temporale). Il whitening standard senza margine è disabilitato via eccezione.
- **Significance & Livetime:** Nessuna *significance inflation*. Il tempo morto strumentale è gestito rigorosamente intersecando segmenti in modo disgiunto (CAT1).
- **Injection Bias:** Assenza di bias macroscopici nelle iniezioni grazie alla stima del PSD su segmenti clean locali prima dell'injection run (`injection.py`).

## 3. Limitazioni e Caveat (Per Discussione Paper)
Nonostante l'eccellente copertura dell'algoritmo (nessun unclassified event), gli autori devono riportare i seguenti caveat nel manoscritto:
1. **Bias di Selezione su PSD Locali:** Il background è normalizzato su intervalli ristretti (spettrogrammi). Fluttuazioni a bassissima frequenza oltre i 32s di contesto potrebbero non essere completamente appianate se l'interpolazione PSD assume rumore perfettamente stazionario.
2. **Sensibilità Limitata dal Gate CAT1:** Il tasso di limite superiore (metodologico) è guidato dal breve *science mode livetime* effettivo rispetto al bounding span, e non dalla pura efficienza algoritmica.
3. **Mancanza di SNR Globale nel Dataset di Partenza:** Nei dataset aggregati (Tassonomia) analizzati, i valori diretti di SNR non sono stati propagati ai file macro-summary, limitando un'analisi di significatività fine in post-processing a questo livello di aggregazione. Si consiglia di espandere l'export.

**Status:** Revisione Completata, pronta per estrazione Latex.
