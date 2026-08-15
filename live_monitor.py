import h5py
import matplotlib.pyplot as plt
import umap
import time
import numpy as np
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="Live UMAP Monitor for SWMR HDF5")
    parser.add_argument("--file", type=str, required=True, help="Path to the .h5 file")
    parser.add_argument("--interval", type=float, default=5.0, help="Refresh interval in seconds (default: 5)")
    parser.add_argument("--min-update", type=int, default=5, help="Minimum new points to trigger UMAP recalculation")
    args = parser.parse_args()

    # Abilita la modalità interattiva per un plot non bloccante
    plt.ion()
    plt.style.use('dark_background') # Tema scuro per esposizioni/fiere
    fig, ax = plt.subplots(figsize=(15, 8)) # Allargato molto per la leggenda laterale
    
    # Facciamo spazio sulla destra per il testo (il plot occupa il 65% a sinistra)
    plt.subplots_adjust(right=0.65)
    
    colorbar = None
    last_count = 0
    
    print(f"Avvio Live Monitor su: {args.file}")
    print(f"Il grafico si aggiornerà ogni {args.interval} secondi se ci sono almeno {args.min_update} nuovi glitch.")
    
    while plt.fignum_exists(fig.number):
        try:
            # Modalità SWMR fondamentale per leggere mentre main.py scrive
            with h5py.File(args.file, 'r', swmr=True) as f:
                if 'novelties/mil_vectors' not in f:
                    plt.pause(args.interval)
                    continue
                    
                vectors = f['novelties/mil_vectors'][:]
                scores = f['novelties/nov_scores'][:]
                
            current_count = len(vectors)
            
            # Ricalcola l'UMAP solo se abbiamo abbastanza nuovi dati
            if current_count - last_count >= args.min_update and current_count > 10:
                print(f"[{time.strftime('%H:%M:%S')}] Ricalcolo UMAP con {current_count} glitch...")
                
                # UMAP è ottimizzato, ma su migliaia di punti impiega qualche secondo.
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    reducer = umap.UMAP(n_neighbors=5, min_dist=0.1, random_state=42)
                    embedding = reducer.fit_transform(vectors)
                
                ax.clear()
                scatter = ax.scatter(embedding[:, 0], embedding[:, 1], c=scores, cmap='viridis', s=30, alpha=0.8)
                
                if colorbar is None:
                    colorbar = fig.colorbar(scatter, ax=ax, label='Novelty Score')
                else:
                    colorbar.update_normal(scatter)
                    
                ax.set_title(f"Live UMAP of Extracted Novelties (Totale: {current_count})", fontsize=14, pad=20)
                ax.set_xlabel("UMAP Dimension 1")
                ax.set_ylabel("UMAP Dimension 2")
                
                # Testo esplicativo / Leggenda per Fiere ed Esposizioni (Aggiornato e Spostato)
                textstr = '\n'.join((
                    r'HOW TO READ THIS DASHBOARD:',
                    r'',
                    r'• Points:',
                    r'  Each dot is a raw LIGO data segment',
                    r'  flagged as an Anomaly (NOVEL).',
                    r'',
                    r'• X/Y Axes (UMAP 1 & 2):',
                    r'  These axes have no physical unit.',
                    r'  They are a 2D projection of the 384D',
                    r'  AI embedding space. Points close to',
                    r'  each other share similar physical shapes.',
                    r'  Dense islands = new repeating glitches.',
                    r'',
                    r'• Color (Novelty Score):',
                    r'  Yellow = Highest novelty (review priority)',
                    r'  Purple = Borderline Anomaly (Near noise)',
                    r'',
                    r'Offline SWMR visualization; not an alert stream'
                ))
                props = dict(boxstyle='round,pad=1', facecolor='#111111', alpha=0.8, edgecolor='gray')
                
                # Rimuoviamo vecchi testi sulla figura per evitare sovrapposizioni
                for txt in fig.texts:
                    txt.remove()
                    
                # Posizioniamo il box FUORI dal grafico, sulla destra (coordinate assolute della figure)
                fig.text(0.68, 0.5, textstr, fontsize=12,
                         verticalalignment='center', bbox=props, color='white', linespacing=1.5)
                
                last_count = current_count
                
            # plt.pause aggiorna il canvas grafico e attende N secondi senza bloccare l'interfaccia
            plt.pause(args.interval)
            
        except OSError as e:
            # Potrebbe esserci un micro-lock sul filesystem, aspettiamo e riproviamo
            time.sleep(1)
        except KeyboardInterrupt:
            print("Chiusura monitor...")
            break
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Errore imprevisto: {e}")
            plt.pause(args.interval)

if __name__ == "__main__":
    main()
