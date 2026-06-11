import numpy as np
import matplotlib.pyplot as plt

def generate_synthetic_spectrogram(size=256, alpha=2.0):
    """
    Genera un rumore sintetico 2D con inviluppo spettrale 1/f^alpha.
    Restituisce un array numpy (size, size, 3) in RGB con colormap 'cividis'.
    """
    # Genera rumore bianco nel dominio spaziale
    white_noise = np.random.randn(size, size)
    
    # Passa nel dominio di Fourier
    f_transform = np.fft.fft2(white_noise)
    f_shift = np.fft.fftshift(f_transform)
    
    # Crea griglia delle frequenze
    fx = np.fft.fftfreq(size)
    fy = np.fft.fftfreq(size)
    FX, FY = np.meshgrid(np.fft.fftshift(fx), np.fft.fftshift(fy))
    
    # Calcola magnitudine delle frequenze (evita divisione per zero al centro)
    f_mag = np.sqrt(FX**2 + FY**2)
    f_mag[size//2, size//2] = 1.0  # temporaneamente evita 0
    
    # Applica filtro 1/f^(alpha/2) perché la PSD è proporzionale al modulo quadro
    spectral_envelope = 1.0 / (f_mag ** (alpha / 2.0))
    spectral_envelope[size//2, size//2] = 0.0  # azzera componente DC
    
    # Moltiplica per l'inviluppo e torna al dominio spaziale
    f_filtered = f_shift * spectral_envelope
    filtered_noise = np.real(np.fft.ifft2(np.fft.ifftshift(f_filtered)))
    
    # Normalizza in [0, 1]
    noise_min = np.min(filtered_noise)
    noise_max = np.max(filtered_noise)
    normalized_noise = (filtered_noise - noise_min) / (noise_max - noise_min)
    
    # Applica colormap cividis
    cmap = plt.get_cmap('cividis')
    # cmap restituisce RGBA, prendiamo solo RGB e scartiamo A, poi scaliamo a [0, 255]
    rgb_noise = (cmap(normalized_noise)[..., :3] * 255).astype(np.uint8)
    
    return rgb_noise

def apply_glitch_to_noise(base_rgb, draw_mask, intensity=5.0):
    """
    Applica il disegno del glitch al rumore e ricalcola la colormap.
    draw_mask è una matrice (256, 256) float in [0, 1].
    Poiché base_rgb è già colorato, ricaviamo i valori scalari originali,
    aggiungiamo l'intensità della mask, e riapplichiamo il colore.
    """
    # Approssimazione: per non dover invertire la colormap, calcoliamo una versione in scala di grigi
    # Ma il modo più corretto è generare il grayscale (normalized_noise), salvarlo, e sommarlo.
    # Per semplicità in questa funzione, se base_rgb è fornito come tale, dovremo fare un trucco.
    pass  # In realtà la logica di amplificazione sarà gestita nell'app prima di convertire in RGB

class SpectrogramGenerator:
    def __init__(self, size=256, alpha=2.0):
        self.size = size
        self.alpha = alpha
        self.cmap = plt.get_cmap('cividis')
        
    def generate_base_noise_normalized(self):
        """Restituisce il rumore 2D normalizzato in [0, 1] prima della colormap."""
        white_noise = np.random.randn(self.size, self.size)
        f_transform = np.fft.fft2(white_noise)
        f_shift = np.fft.fftshift(f_transform)
        
        fx = np.fft.fftfreq(self.size)
        fy = np.fft.fftfreq(self.size)
        FX, FY = np.meshgrid(np.fft.fftshift(fx), np.fft.fftshift(fy))
        
        f_mag = np.sqrt(FX**2 + FY**2)
        f_mag[self.size//2, self.size//2] = 1.0
        
        spectral_envelope = 1.0 / (f_mag ** (self.alpha / 2.0))
        spectral_envelope[self.size//2, self.size//2] = 0.0
        
        f_filtered = f_shift * spectral_envelope
        filtered_noise = np.real(np.fft.ifft2(np.fft.ifftshift(f_filtered)))
        
        # Standardizza con varianza realistica per il rumore LIGO
        # Normalizziamo mean 0, std 1
        filtered_noise = (filtered_noise - np.mean(filtered_noise)) / np.std(filtered_noise)
        
        # Mappa in [0, 1] ma lasciando headroom per il glitch.
        # Diciamo che il rumore copre [0.1, 0.6] e il glitch andrà verso 1.0.
        # Clip e minmax
        clipped = np.clip(filtered_noise, -3, 3) # +/- 3 sigma
        normalized = (clipped + 3) / 6.0 # range [0, 1]
        
        # Riduciamo contrasto per far risaltare il glitch
        normalized = normalized * 0.5 + 0.1 
        
        return normalized

    def render_rgb(self, normalized_array):
        """Converte un array [0, 1] in RGB (256, 256, 3) usando cividis."""
        # clamp a [0, 1]
        clamped = np.clip(normalized_array, 0.0, 1.0)
        return (self.cmap(clamped)[..., :3] * 255).astype(np.uint8)

