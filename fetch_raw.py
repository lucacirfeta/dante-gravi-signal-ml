import argparse
import os
import sys
import time
import re
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Errore: il modulo 'yaml' non è installato. Esegui 'pip install pyyaml'")

try:
    from gwpy.timeseries import TimeSeries
except ImportError:
    sys.exit("Errore: la libreria 'gwpy' non è installata. Puoi installarla con 'pip install gwpy'")

def get_last_gps(detector, output_dir, run_lower):
    """
    Cerca i file HDF5 già scaricati per il detector e run e restituisce
    il tempo GPS (fine) più avanzato trovato.
    """
    out_path = Path(output_dir) / run_lower / detector
    if not out_path.exists():
        return None
        
    max_gps_end = None
    # Cerca i file corrispondenti al formato DETECTOR-RAW-START-DURATION.hdf5
    pattern = re.compile(rf"^{detector}-RAW-(\d+)-(\d+)\.hdf5$")
    
    for file_path in out_path.glob(f"{detector}-RAW-*.hdf5"):
        match = pattern.match(file_path.name)
        if match:
            start = int(match.group(1))
            duration = int(match.group(2))
            end = start + duration
            if max_gps_end is None or end > max_gps_end:
                max_gps_end = end
                
    return max_gps_end

def load_config_val(keys, default_val):
    """Legge un valore ricorsivo dal config.yaml o ritorna default_val"""
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
            val = config
            for k in keys:
                val = val.get(k)
                if val is None:
                    return default_val
            return val
    except Exception:
        return default_val

def fetch_and_save_raw_data(detector, run, target_gps_start, total_hours, output_dir, chunk_seconds=4096, max_retries=1, retry_delay=2):
    """
    Scarica i dati strain grezzi da GWOSC suddividendo il lavoro in blocchi (default 4096s).
    Allinea l'inizio ai confini dei file di GWOSC per evitare errori di attraversamento.
    Verifica l'ultimo download per riprendere in automatico in caso di interruzione.
    """
    run_lower = run.lower()
    out_path = Path(output_dir) / run_lower / detector
    out_path.mkdir(parents=True, exist_ok=True)
    
    last_gps = get_last_gps(detector, output_dir, run_lower)
    
    if last_gps is not None and last_gps > target_gps_start:
        print(f"Trovati dati esistenti per {detector}. Riprendo il download dall'ultimo blocco scaricato (GPS: {last_gps})")
        current_start = last_gps
    else:
        current_start = target_gps_start
        
    # ALLINEAMENTO AI CONFINI 4096s DI GWOSC:
    # Se iniziamo in mezzo a un file di 4096s (e la richiesta supera il confine), gwpy andrà in errore.
    # Allineiamo current_start al multiplo di 4096 più vicino verso l'alto (o lo lasciamo invariato se già allineato).
    current_start = ((current_start + chunk_seconds - 1) // chunk_seconds) * chunk_seconds
        
    target_end = target_gps_start + int(total_hours * 3600)
    
    if current_start >= target_end:
        print(f"Il download per {detector} è già completo fino a {total_hours} ore dal punto di partenza.")
        return
    
    while current_start < target_end:
        current_end = min(current_start + chunk_seconds, target_end)
        duration = current_end - current_start
        
        filename = f"{detector}-RAW-{current_start}-{duration}.hdf5"
        filepath = out_path / filename
        
        print(f"Scaricando {detector} da {current_start} a {current_end} (Blocco da {duration}s)...")
        
        success = False
        for attempt in range(1, max_retries + 1):
            try:
                ts = TimeSeries.fetch_open_data(
                    detector,
                    current_start,
                    current_end,
                    verbose=False,
                    cache=True
                )
                ts.write(filepath, format="hdf5")
                print(f"-> Dati salvati con successo in: {filepath}")
                success = True
                break
            except Exception as e:
                print(f"-> Errore durante il download (Tentativo {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    print(f"-> Attesa di {retry_delay} secondi prima di riprovare...")
                    time.sleep(retry_delay)
                else:
                    print(f"-> Impossibile scaricare il blocco {current_start}-{current_end}. I dati potrebbero non essere pronti (ANALYSIS_READY). Salto al blocco successivo...")
        
        # Incrementiamo current_start a prescindere dal successo (non fermiamo il ciclo)
        current_start = current_end

def main():
    parser = argparse.ArgumentParser(
        description="Scarica dati strain grezzi da GWOSC. Divide il download in blocchi di 1 ora per sicurezza e supporta il resume."
    )
    parser.add_argument("detector", choices=["H1", "L1", "V1"], help="Identificativo del rivelatore (H1, L1, o V1)")
    parser.add_argument("--run", type=str, default="O4a", choices=["O2", "O3a", "O3b", "O4a"], 
                        help="Run osservativo (default: O4a). Determina la struttura directory e l'inizio GPS se --start non è fornito.")
    parser.add_argument("--hours", type=float, 
                        help="Ore totali da scaricare. Se non specificato, legge da config.yaml in base al run.")
    parser.add_argument("--start", type=int, 
                        help="Tempo GPS di inizio manuale. Se non specificato, viene calcolato da config.yaml in base a --run.")
    parser.add_argument("--outdir", default="data/raw", help="Directory di destinazione (default: data/raw)")
    
    args = parser.parse_args()
    run = args.run
    
    if args.start is not None:
        start = args.start
    else:
        # Leggi start_date dal config.yaml per il run specificato
        start_date = load_config_val(["run_config", run, "start_date"], None)
        if start_date is None:
            # Fallback hardcoded se manca il config
            fallbacks = {"O2": "2016-11-30", "O3a": "2019-04-01", "O3b": "2019-11-01", "O4a": "2023-05-24"}
            start_date = fallbacks.get(run, "2023-05-24")
        
        # Aggiungiamo 6 ore per evitare i primissimi minuti instabili del run, in coerenza con main.py
        from gwpy.time import to_gps
        start = int(to_gps(start_date)) + 6 * 3600
    
    # Carica da config.yaml se non specificati
    if args.hours is not None:
        hours = args.hours
    else:
        hours = load_config_val(["run_config", run, "hours_per_detector"], 48.0)
    
    if hours <= 0:
        sys.exit("Errore: il numero di ore deve essere maggiore di zero.")
        
    print(f"Inizio operazione per {args.detector} ({run}). Obiettivo: {hours} ore partendo da GPS {start}")
    
    fetch_and_save_raw_data(
        detector=args.detector,
        run=run,
        target_gps_start=start,
        total_hours=hours,
        output_dir=args.outdir
    )

if __name__ == "__main__":
    main()
