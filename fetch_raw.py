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
    parser.add_argument("--run", type=str, default="O4a", choices=["O2", "O3a", "O3b", "O4a"], help="Run osservativo base.")
    parser.add_argument("--hours", type=float, default=1.0, help="Ore totali da scaricare (a partire dall'origine o dal punto di resume).")
    parser.add_argument("--output-dir", type=str, default="data/raw", help="Cartella output cache per i file HDF5.")
    parser.add_argument("--segment-duration", type=int, default=32, help="Durata di ogni blocco di download in secondi.")
    parser.add_argument("--no-resume", action="store_false", dest="resume", help="Disattiva il check e resume dei file HDF5 già scaricati.")
    parser.add_argument("--retry", action="store_true", default=False, help="Abilita la logica di retry in caso di errore.")

    args = parser.parse_args()

    # Import ritardato per gestire la dipendenza in modo pulito
    try:
        from gwpy.timeseries import TimeSeries
    except ImportError:
        sys.exit("Errore: la libreria 'gwpy' non è installata. Esegui 'pip install gwpy h5py'.")

    # Tempi GPS di inizio dei run (ricavati da GWOSC + 6 ore di offset per evitare anomalie iniziali)
    RUN_STARTS = {
        "O2": 1164556817 + 6 * 3600,
        "O3a": 1238166018 + 6 * 3600,
        "O3b": 1256655618 + 6 * 3600,
        "O4a": 1368975618 + 6 * 3600,
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    current_start = None

    # Logica di Resume Incrementale
    if args.resume:
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
            print(f"Ripresa dal GPS {current_start} (ultimo file trovato).")

    if current_start is None:
        current_start = RUN_STARTS[args.run]
        print(f"Nuovo download dall'inizio della run {args.run}: GPS {current_start}")

    # Allineamento dell'inizio a multipli di 4096 secondi (standard GWOSC) 
    aligned_start = (current_start // 4096) * 4096
    if aligned_start != current_start:
        print(f"Start GPS allineato da {current_start} a {aligned_start} per evitare boundary bug.")
        current_start = aligned_start

    end_gps = current_start + int(args.hours * 3600)

    print(f"=== FETCH-RAW: {args.detector} [{args.run}] ===")
    print(f"Intervallo GPS: {current_start} -> {end_gps} ({args.hours:.1f} ore)")

    # Inizio download in blocchi
    total_blocks = (end_gps - current_start + args.segment_duration - 1) // args.segment_duration
    if total_blocks <= 0:
        print("Nessun dato da scaricare per l'intervallo richiesto.")
        return

    block_num = 1
    retry_delays = [5, 10, 20] if args.retry else [0]
    base_delay = 0.3

    while current_start < end_gps:
        current_end = min(current_start + args.segment_duration, end_gps)
        filename = f"{args.detector}_{current_start}_{current_end}.hdf5"
        filepath = out_dir / filename

        print(f"Blocco {block_num}/{total_blocks}: {args.detector} da {current_start} a {current_end}... ", end="", flush=True)

        if filepath.exists():
            print("già presente")
        else:
            success = False
            for attempt, backoff in enumerate(retry_delays):
                try:
                    while True:
                        time.sleep(base_delay)
                        try:
                            ts = TimeSeries.fetch_open_data(
                                args.detector,
                                current_start,
                                current_end,
                                verbose=False,
                                cache=True,
                            )
                            break
                        except Exception as inner_e:
                            err_str = str(inner_e)
                            if "429" in err_str or "Too Many Requests" in err_str:
                                print(f"(429 Too Many Requests. Delay +300ms, attesa 1s)... ", end="", flush=True)
                                base_delay += 0.3
                                time.sleep(1.0)
                            else:
                                raise inner_e

                    ts.write(filepath, format="hdf5.gwosc")
                    print("OK")
                    success = True
                    break
                except Exception as e:
                    if attempt < len(retry_delays) - 1:
                        print(f"ERRORE. Riprovo in {backoff}s... ", end="", flush=True)
                        time.sleep(backoff)
                    else:
                        print(f"FALLITO ({str(e)})")
            
            if not success:
                print(f"Salto il blocco {block_num} a causa di errori.")

        current_start = current_end
        block_num += 1

    print("Download completato.")

if __name__ == "__main__":
    main()

