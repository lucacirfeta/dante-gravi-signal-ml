#!/usr/bin/env python3
import argparse
import sys
import time
import re
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(
        description="Standalone raw GWOSC strain data fetcher. Usabile in Termux o ambienti minimi."
    )
    parser.add_argument("--detector", type=str, required=True, choices=["H1", "L1", "V1"], help="Rivelatore.")
    parser.add_argument("--mode", type=str, default="current", choices=["current", "o4a_start"], help="Modalità di download.")
    parser.add_argument("--run", type=str, default="O4a", choices=["O2", "O3a", "O3b", "O4a"], help="Run osservativo base.")
    parser.add_argument("--hours", type=float, default=72, help="Ore totali da scaricare (se mode=current).")
    parser.add_argument("--output-dir", type=str, default="data/raw", help="Cartella output cache per i file HDF5.")
    parser.add_argument("--segment-duration", type=int, default=4096, help="Durata di ogni blocco di download in secondi.")
    parser.add_argument("--no-resume", action="store_false", dest="resume", help="Disattiva il check e resume dei file HDF5 già scaricati.")

    args = parser.parse_args()

    # Import ritardato per gestire la dipendenza in modo pulito
    try:
        from gwpy.timeseries import TimeSeries
        from gwpy.time import tconvert
    except ImportError:
        sys.exit("Errore: la libreria 'gwpy' non è installata. Esegui 'pip install gwpy h5py'.")

    # Tempi GPS di inizio dei run (ricavati da GWOSC + 6 ore di offset per evitare anomalie iniziali)
    RUN_STARTS = {
        "O2": 1164556817 + 6 * 3600,
        "O3a": 1238166018 + 6 * 3600,
        "O3b": 1256655618 + 6 * 3600,
        "O4a": 1368956418 + 6 * 3600,
    }

    # Calcolo finestra GPS
    if args.mode == "current":
        end_gps = int(tconvert('now'))
        start_gps = int(end_gps - args.hours * 3600)
    elif args.mode == "o4a_start":
        start_gps = RUN_STARTS[args.run]
        end_gps = int(tconvert('now'))
    else:
        sys.exit(f"Modalità sconosciuta: {args.mode}")

    # Allineamento dell'inizio a multipli di 4096 secondi (standard GWOSC) 
    # per prevenire bug di attraversamento file in gwpy
    aligned_start = (start_gps // 4096) * 4096
    if aligned_start != start_gps:
        print(f"Start GPS allineato da {start_gps} a {aligned_start} per evitare boundary bug.")
        start_gps = aligned_start

    print(f"=== FETCH-RAW: {args.detector} [{args.run}] ===")
    print(f"Intervallo GPS: {start_gps} -> {end_gps} ({(end_gps - start_gps) / 3600:.1f} ore)")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    current_start = start_gps

    # Logica di Resume Incrementale
    if args.resume:
        # main.py si aspetta i file nel formato: <detector>_<start>_<end>.hdf5
        pattern = re.compile(rf"^{args.detector}_(\d+)_(\d+)\.hdf5$")
        max_end_gps = 0
        for f in out_dir.glob("*.hdf5"):
            m = pattern.match(f.name)
            if m:
                file_end = int(m.group(2))
                if file_end > max_end_gps:
                    max_end_gps = file_end
        
        if max_end_gps > 0:
            current_start = max_end_gps
            if current_start >= end_gps:
                print("Nessun nuovo dato da scaricare. La cache è aggiornata.")
                return

            aligned_current = (current_start // 4096) * 4096
            if aligned_current != current_start:
                print(f"Ripresa allineata da {current_start} a {aligned_current} per evitare boundary bug.")
                current_start = aligned_current
                
            print(f"Ripresa dal GPS {current_start} (ultimo file trovato arriva a {max_end_gps}).")

    # Inizio download in blocchi
    total_blocks = (end_gps - current_start + args.segment_duration - 1) // args.segment_duration
    if total_blocks <= 0:
        print("Nessun dato da scaricare per l'intervallo richiesto.")
        return

    block_num = 1
    while current_start < end_gps:
        current_end = min(current_start + args.segment_duration, end_gps)
        
        # Stessa naming convention attesa dal main.py nella funzione di reprocessing e cache check
        filename = f"{args.detector}_{current_start}_{current_end}.hdf5"
        filepath = out_dir / filename

        print(f"Blocco {block_num}/{total_blocks}: {args.detector} da {current_start} a {current_end}... ", end="", flush=True)

        if filepath.exists():
            print("già presente")
        else:
            success = False
            # Meccanismo di Exponential Backoff in caso di API down
            for attempt, backoff in enumerate([5, 10, 20]):
                try:
                    ts = TimeSeries.fetch_open_data(
                        args.detector,
                        current_start,
                        current_end,
                        verbose=False,
                        cache=True,
                    )
                    # Scriviamo in hdf5.gwosc format nativo come fa il main.py
                    ts.write(filepath, format="hdf5.gwosc")
                    print("OK")
                    success = True
                    break
                except Exception as e:
                    if attempt < 2:
                        print(f"ERRORE. Riprovo in {backoff}s... ", end="", flush=True)
                        time.sleep(backoff)
                    else:
                        print(f"FALLITO ({str(e)})")
            
            if not success:
                print(f"Salto il blocco {block_num} a causa di errori persistenti.")

        current_start = current_end
        block_num += 1

    print("Download completato.")

if __name__ == "__main__":
    main()
