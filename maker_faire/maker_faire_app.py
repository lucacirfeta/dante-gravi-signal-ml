import sys
import os
import json
import logging
from pathlib import Path

# IMPORT CRITICO: Importare torch PRIMA di PyQt5 su Windows per evitare OSError: [WinError 1114]
import numpy as np
import torch
import torch.nn.functional as F
from torchvision import transforms

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QTabWidget, QGraphicsScene, QGraphicsView,
                             QProgressBar, QScrollArea, QGridLayout, QFrame, QSizePolicy)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont, QRadialGradient, QBrush
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QRectF, QPointF, QEvent

from PIL import Image
import matplotlib.pyplot as plt

# Importazione moduli progetto
# Siccome l'app è in maker_faire/, src è nel parent directory.
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.core.encoder import DINOv2Encoder
from maker_faire.synthetic_noise import SpectrogramGenerator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MakerFaireApp")

# Costanti
SIZE = 256
PATCH_GRID = 37  # 256/14 = 18? No, DINOv2 usa 518x518. 518/14 = 37.
# L'encoder fa resize a 518x518, quindi avremo sempre 37x37 patch = 1369 patch.
PATCH_COUNT = 1369
BRUSH_RADIUS = 8
INTENSITY = 0.5  # intensità pennello

class ModelWorker(QThread):
    result_ready = pyqtSignal(dict)
    
    def __init__(self, encoder, bg_matrix, vq_centroids, image_rgb):
        super().__init__()
        self.encoder = encoder
        self.bg_matrix = bg_matrix
        self.vq_centroids = vq_centroids
        self.image_rgb = image_rgb
        
    def run(self):
        try:
            device = self.encoder.device
            
            # Preparazione tensore immagine
            img = Image.fromarray(self.image_rgb)
            tensor = self.encoder.transform(img).unsqueeze(0).to(device)
            
            # Estrazione feature
            with torch.inference_mode():
                out = self.encoder.model.forward_features(tensor)
                cls_token = out['x_norm_clstoken']  # [1, 384]
                patch_tokens = out['x_norm_patchtokens']  # [1, 1369, 384]
                
                # Normalizzazione
                cls_token = F.normalize(cls_token, p=2, dim=-1)
                patch_tokens = F.normalize(patch_tokens, p=2, dim=-1).squeeze(0)  # [1369, 384]
                
                # Calcolo CLS Score (con VQ centroids)
                if self.vq_centroids is not None:
                    # cos_sim: [1, 1216]
                    cls_sims = torch.mm(cls_token, self.vq_centroids.T)
                    cls_max_sim = torch.max(cls_sims).item()
                    cls_novelty = 1.0 - cls_max_sim
                else:
                    cls_novelty = 0.0
                
                # Calcolo Patch-Level Score (con background matrix spaziale)
                if self.bg_matrix is not None:
                    # cos_sim_patch: [1369]
                    # Poiché L2 normati, prodotto scalare = cosine similarity
                    patch_sims = torch.sum(patch_tokens * self.bg_matrix, dim=1)
                    patch_anomaly = 1.0 - patch_sims
                    
                    # Top-68
                    top68_scores, top68_idx = torch.topk(patch_anomaly, 68)
                    patch_novelty = torch.mean(top68_scores).item()
                    
                    # Salva mappa anomalia completa per saliency
                    anomaly_map = patch_anomaly.view(PATCH_GRID, PATCH_GRID).cpu().numpy()
                else:
                    patch_novelty = 0.0
                    anomaly_map = np.zeros((PATCH_GRID, PATCH_GRID))
            
            # Pulizia GPU Memory
            torch.cuda.empty_cache()
            
            self.result_ready.emit({
                'cls_novelty': cls_novelty,
                'patch_novelty': patch_novelty,
                'anomaly_map': anomaly_map
            })
            
        except Exception as e:
            logger.error(f"Errore ModelWorker: {e}")
            self.result_ready.emit({'error': str(e)})


class DrawingScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.noise_gen = SpectrogramGenerator(size=SIZE)
        self.base_noise_normalized = self.noise_gen.generate_base_noise_normalized()
        self.draw_mask = np.zeros((SIZE, SIZE), dtype=np.float32)
        
        self.setSceneRect(0, 0, SIZE, SIZE)
        self.last_point = None
        
        self.update_image()
        
    def update_image(self):
        # Combina noise base con la maschera di disegno
        combined = self.base_noise_normalized + self.draw_mask
        rgb = self.noise_gen.render_rgb(combined)
        self.current_rgb = rgb
        
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self.clear()
        self.addPixmap(QPixmap.fromImage(qimg))
        
    def reset(self):
        self.base_noise_normalized = self.noise_gen.generate_base_noise_normalized()
        self.draw_mask.fill(0)
        self.update_image()
        
    def add_drawing(self, p1, p2):
        # Rasterizzazione semplice di una linea su draw_mask
        x1, y1 = int(p1.x()), int(p1.y())
        x2, y2 = int(p2.x()), int(p2.y())
        
        # Disegna un cerchio sfumato per ogni step lungo la linea
        dist = max(abs(x2 - x1), abs(y2 - y1))
        steps = max(dist, 1)
        for i in range(steps + 1):
            x = int(x1 + (x2 - x1) * i / steps)
            y = int(y1 + (y2 - y1) * i / steps)
            
            # Applica pennello gaussiano
            for dy in range(-BRUSH_RADIUS, BRUSH_RADIUS+1):
                for dx in range(-BRUSH_RADIUS, BRUSH_RADIUS+1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < SIZE and 0 <= ny < SIZE:
                        r2 = dx*dx + dy*dy
                        if r2 <= BRUSH_RADIUS*BRUSH_RADIUS:
                            weight = np.exp(-r2 / (BRUSH_RADIUS**2 / 2)) * INTENSITY
                            self.draw_mask[ny, nx] = min(1.0, self.draw_mask[ny, nx] + weight)
        self.update_image()

    def mousePressEvent(self, event):
        self.last_point = event.scenePos()
        
    def mouseMoveEvent(self, event):
        if self.last_point:
            new_point = event.scenePos()
            self.add_drawing(self.last_point, new_point)
            self.last_point = new_point
            
    def mouseReleaseEvent(self, event):
        self.last_point = None


class DashPanel(QFrame):
    def __init__(self, title, threshold, parent=None):
        super().__init__(parent)
        self.threshold = threshold
        self.setStyleSheet("""
            QFrame { border: 2px solid #444; border-radius: 10px; background-color: #222; }
            QLabel { border: none; }
        """)
        
        layout = QVBoxLayout(self)
        
        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("Arial", 16, QFont.Bold))
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet("color: white;")
        layout.addWidget(title_lbl)
        
        self.status_lbl = QLabel("NESSUN SEGNALE")
        self.status_lbl.setFont(QFont("Arial", 20, QFont.Bold))
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setStyleSheet("color: #00FF00;")
        layout.addWidget(self.status_lbl)
        
        self.score_lbl = QLabel("Score: 0.000")
        self.score_lbl.setFont(QFont("Arial", 14))
        self.score_lbl.setAlignment(Qt.AlignCenter)
        self.score_lbl.setStyleSheet("color: #AAA;")
        layout.addWidget(self.score_lbl)
        
    def update_score(self, score):
        self.score_lbl.setText(f"Score: {score:.4f}")
        if score > self.threshold:
            self.status_lbl.setText("ANOMALIA RILEVATA")
            self.status_lbl.setStyleSheet("color: #FF0000;")
        else:
            self.status_lbl.setText("NESSUN SEGNALE")
            self.status_lbl.setStyleSheet("color: #00FF00;")

    def reset(self):
        self.score_lbl.setText("Score: 0.000")
        self.status_lbl.setText("NESSUN SEGNALE")
        self.status_lbl.setStyleSheet("color: #00FF00;")


class MakerFaireApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cacciatori di Onde - Maker Faire 2026")
        self.setStyleSheet("background-color: #111; color: white;")
        
        # Logica Modelli
        self.encoder = None
        self.bg_matrix = None
        self.vq_centroids = None
        
        self.trick_score_wins = 0
        self.trick_score_total = 0
        
        self.init_ui()
        self.load_models()
        
        # Timer inattività (90 secondi)
        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.timeout.connect(self.check_inactivity)
        self.inactivity_timer.start(1000) # Check ogni secondo
        self.time_since_last_action = 0

    def init_ui(self):
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab { background: #333; color: white; padding: 15px; font-size: 16px; min-width: 200px; }
            QTabBar::tab:selected { background: #555; font-weight: bold; }
            QTabWidget::pane { border: 1px solid #444; }
        """)
        self.setCentralWidget(self.tabs)
        
        self.tab1 = QWidget()
        self.tab2 = QWidget()
        self.tab3 = QWidget()
        
        self.tabs.addTab(self.tab1, "Dipingi il Glitch")
        self.tabs.addTab(self.tab2, "Trick the AI")
        self.tabs.addTab(self.tab3, "Catalogo dei Mostri Cosmici")
        
        self.setup_tab1()
        self.setup_tab2()
        self.setup_tab3()
        
        # Cattura eventi globali per reset timer
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        # Reset timer su qualsiasi input
        if event.type() in [QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.TouchBegin]:
            self.time_since_last_action = 0
        return super().eventFilter(obj, event)

    def check_inactivity(self):
        self.time_since_last_action += 1
        if self.time_since_last_action >= 90:
            self.reset_all()
            self.tabs.setCurrentIndex(0)
            self.time_since_last_action = 0
            
    def load_models(self):
        # Mostra loading
        self.tab1_progress.show()
        self.tab1_progress.setValue(10)
        QApplication.processEvents()
        
        try:
            self.encoder = DINOv2Encoder(batch_size=1)
            self.tab1_progress.setValue(50)
            QApplication.processEvents()
            
            # Carica file
            base_dir = Path(__file__).resolve().parent
            
            bg_path = base_dir / 'background_matrix.npy'
            if bg_path.exists():
                # Carica su GPU in formato tensore [1369, 384]
                self.bg_matrix = torch.from_numpy(np.load(bg_path)).float().to(self.encoder.device)
            else:
                logger.warning("background_matrix.npy non trovata!")
            self.tab1_progress.setValue(70)
            
            vq_path = base_dir.parent / 'data' / 'reference' / 'patch_compressed_index.npz'
            if vq_path.exists():
                vq_data = np.load(vq_path)
                # Assumendo che la chiave sia 'embeddings'
                if 'embeddings' in vq_data:
                    self.vq_centroids = torch.from_numpy(vq_data['embeddings']).float().to(self.encoder.device)
            else:
                logger.warning("patch_compressed_index.npz non trovata!")
                
            self.tab1_progress.setValue(100)
            self.tab1_progress.hide()
            
        except Exception as e:
            logger.error(f"Errore caricamento modelli: {e}")
            self.tab1_progress.hide()

    # --- TAB 1: DIPINGI IL GLITCH ---
    def setup_tab1(self):
        layout = QHBoxLayout(self.tab1)
        
        # Colonna Sinistra (Spettrogramma)
        left_col = QVBoxLayout()
        self.scene1 = DrawingScene(self)
        self.view1 = QGraphicsView(self.scene1)
        self.view1.setFixedSize(SIZE+10, SIZE+10)
        self.view1.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view1.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        left_col.addWidget(self.view1, alignment=Qt.AlignCenter)
        
        btn_layout = QHBoxLayout()
        self.btn_send1 = QPushButton("INVIA AI MODELLI")
        self.btn_send1.setMinimumHeight(60)
        self.btn_send1.setFont(QFont("Arial", 14, QFont.Bold))
        self.btn_send1.setStyleSheet("background-color: #007ACC;")
        self.btn_send1.clicked.connect(self.process_tab1)
        
        self.btn_reset1 = QPushButton("RESET")
        self.btn_reset1.setMinimumHeight(60)
        self.btn_reset1.setFont(QFont("Arial", 14, QFont.Bold))
        self.btn_reset1.setStyleSheet("background-color: #CC4400;")
        self.btn_reset1.clicked.connect(self.scene1.reset)
        
        btn_layout.addWidget(self.btn_send1)
        btn_layout.addWidget(self.btn_reset1)
        left_col.addLayout(btn_layout)
        
        self.tab1_progress = QProgressBar()
        self.tab1_progress.hide()
        left_col.addWidget(self.tab1_progress)
        
        layout.addLayout(left_col, stretch=1)
        
        # Colonna Destra (Cruscotti)
        right_col = QVBoxLayout()
        self.dash_cls = DashPanel("MODELLO STANDARD (CLS Globale)", threshold=0.874)
        self.dash_patch = DashPanel("NOSTRO MODELLO (Patch-Level Top-68)", threshold=0.4122)
        
        right_col.addWidget(self.dash_cls)
        right_col.addWidget(self.dash_patch)
        layout.addLayout(right_col, stretch=1)

    def process_tab1(self):
        if not self.encoder:
            return
            
        self.btn_send1.setEnabled(False)
        self.tab1_progress.setRange(0, 0)
        self.tab1_progress.show()
        
        self.worker1 = ModelWorker(self.encoder, self.bg_matrix, self.vq_centroids, self.scene1.current_rgb)
        self.worker1.result_ready.connect(self.on_tab1_result)
        self.worker1.start()

    def on_tab1_result(self, res):
        self.tab1_progress.hide()
        self.btn_send1.setEnabled(True)
        
        if 'error' in res:
            logger.error(res['error'])
            return
            
        self.dash_cls.update_score(res['cls_novelty'])
        self.dash_patch.update_score(res['patch_novelty'])

    # --- TAB 2: TRICK THE AI ---
    def setup_tab2(self):
        layout = QHBoxLayout(self.tab2)
        
        left_col = QVBoxLayout()
        self.scene2 = DrawingScene(self)
        self.view2 = QGraphicsView(self.scene2)
        self.view2.setFixedSize(SIZE+10, SIZE+10)
        self.view2.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view2.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_col.addWidget(self.view2, alignment=Qt.AlignCenter)
        
        # Saliency overlay view
        self.saliency_overlay2 = QLabel(self.view2)
        self.saliency_overlay2.setGeometry(5, 5, SIZE, SIZE)
        self.saliency_overlay2.hide()
        
        btn_layout = QHBoxLayout()
        self.btn_send2 = QPushButton("INVIA SFIDA")
        self.btn_send2.setMinimumHeight(60)
        self.btn_send2.setFont(QFont("Arial", 14, QFont.Bold))
        self.btn_send2.setStyleSheet("background-color: #007ACC;")
        self.btn_send2.clicked.connect(self.process_tab2)
        
        self.btn_reset2 = QPushButton("NUOVA SFIDA")
        self.btn_reset2.setMinimumHeight(60)
        self.btn_reset2.setFont(QFont("Arial", 14, QFont.Bold))
        self.btn_reset2.setStyleSheet("background-color: #00CC44;")
        self.btn_reset2.clicked.connect(self.new_challenge_tab2)
        
        btn_layout.addWidget(self.btn_send2)
        btn_layout.addWidget(self.btn_reset2)
        left_col.addLayout(btn_layout)
        
        self.tab2_progress = QProgressBar()
        self.tab2_progress.hide()
        left_col.addWidget(self.tab2_progress)
        
        layout.addLayout(left_col, stretch=1)
        
        right_col = QVBoxLayout()
        
        title_lbl = QLabel("TRICK THE AI")
        title_lbl.setFont(QFont("Arial", 24, QFont.Bold))
        title_lbl.setAlignment(Qt.AlignCenter)
        right_col.addWidget(title_lbl)
        
        self.trick_score_lbl = QLabel("Hai ingannato l'AI 0 volte su 0 tentativi")
        self.trick_score_lbl.setFont(QFont("Arial", 16))
        self.trick_score_lbl.setAlignment(Qt.AlignCenter)
        right_col.addWidget(self.trick_score_lbl)
        
        self.trick_result_lbl = QLabel("")
        self.trick_result_lbl.setFont(QFont("Arial", 18, QFont.Bold))
        self.trick_result_lbl.setAlignment(Qt.AlignCenter)
        right_col.addWidget(self.trick_result_lbl)
        
        layout.addLayout(right_col, stretch=1)
        
        # Scacchiera Positional Embedding
        self.pos_embed_timer = QTimer(self)
        self.pos_embed_timer.setSingleShot(True)
        self.pos_embed_timer.timeout.connect(self.hide_pos_embed)
        self.tabs.currentChanged.connect(self.on_tab_changed)

    def process_tab2(self):
        if not self.encoder:
            return
        self.btn_send2.setEnabled(False)
        self.tab2_progress.setRange(0, 0)
        self.tab2_progress.show()
        
        self.worker2 = ModelWorker(self.encoder, self.bg_matrix, None, self.scene2.current_rgb)
        self.worker2.result_ready.connect(self.on_tab2_result)
        self.worker2.start()

    def on_tab2_result(self, res):
        self.tab2_progress.hide()
        self.btn_send2.setEnabled(True)
        
        if 'error' in res:
            return
            
        patch_score = res['patch_novelty']
        self.trick_score_total += 1
        
        if patch_score < 0.4122:
            self.trick_score_wins += 1
            self.trick_result_lbl.setText("COMPLIMENTI! Hai ingannato l'AI!")
            self.trick_result_lbl.setStyleSheet("color: #00FF00;")
            self.saliency_overlay2.hide()
        else:
            self.trick_result_lbl.setText("L'AI HA TROVATO IL TUO GLITCH!")
            self.trick_result_lbl.setStyleSheet("color: #FF0000;")
            
            # Show saliency mask
            anomaly_map = res['anomaly_map'] # 37x37
            max_val = np.max(anomaly_map)
            if max_val == 0: max_val = 1.0
            # resize to 256x256
            mask_img = Image.fromarray((anomaly_map / max_val * 255).astype(np.uint8)).resize((SIZE, SIZE), Image.Resampling.BILINEAR)
            self._mask_rgba_cache = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
            self._mask_rgba_cache[..., 0] = 255  # Red
            self._mask_rgba_cache[..., 3] = np.array(mask_img) // 2  # Alpha blending
            
            qimg = QImage(self._mask_rgba_cache.data, SIZE, SIZE, SIZE*4, QImage.Format_RGBA8888)
            self.saliency_overlay2.setPixmap(QPixmap.fromImage(qimg))
            self.saliency_overlay2.show()
            
        self.trick_score_lbl.setText(f"Hai ingannato l'AI {self.trick_score_wins} volte su {self.trick_score_total} tentativi")

    def new_challenge_tab2(self):
        self.scene2.reset()
        self.saliency_overlay2.hide()
        self.trick_result_lbl.setText("")

    def on_tab_changed(self, index):
        if index == 1:
            self.show_pos_embed()

    def show_pos_embed(self):
        if self.encoder and hasattr(self.encoder.model, 'pos_embed'):
            pos_emb = self.encoder.model.pos_embed[:, 1:, :] # [1, 1369, 384]
            # Usa magnitude media
            mag = torch.mean(torch.abs(pos_emb), dim=-1).squeeze(0).cpu().numpy()
            mag = mag.reshape(PATCH_GRID, PATCH_GRID)
            mag = (mag - np.min(mag)) / (np.max(mag) - np.min(mag)) * 255
            mag_img = Image.fromarray(mag.astype(np.uint8)).resize((SIZE, SIZE), Image.Resampling.NEAREST)
            
            # Applica colormap plasma o converti a grigio colorato
            self._mag_rgba_cache = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
            self._mag_rgba_cache[..., 0] = np.array(mag_img)
            self._mag_rgba_cache[..., 1] = 0
            self._mag_rgba_cache[..., 2] = 255 - np.array(mag_img)
            self._mag_rgba_cache[..., 3] = 180
            
            qimg = QImage(self._mag_rgba_cache.data, SIZE, SIZE, SIZE*4, QImage.Format_RGBA8888)
            self.saliency_overlay2.setPixmap(QPixmap.fromImage(qimg))
            self.saliency_overlay2.show()
            
            self.trick_result_lbl.setText("Senza segnale fisico, l'AI 'allucina' la\npropria struttura: Positional Embeddings di DINOv2.")
            self.trick_result_lbl.setStyleSheet("color: #AAAAAA;")
            
            self.pos_embed_timer.start(3000)

    def hide_pos_embed(self):
        if self.tabs.currentIndex() == 1:
            self.saliency_overlay2.hide()
            self.trick_result_lbl.setText("")

    # --- TAB 3: CATALOGO ---
    def setup_tab3(self):
        layout = QVBoxLayout(self.tab3)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.grid_layout = QGridLayout(self.scroll_content)
        
        self.scroll_area.setWidget(self.scroll_content)
        layout.addWidget(self.scroll_area)
        
        btn_compare = QPushButton("CONFRONTA CON IL TUO DISEGNO")
        btn_compare.setMinimumHeight(60)
        btn_compare.setFont(QFont("Arial", 16, QFont.Bold))
        btn_compare.setStyleSheet("background-color: #6600CC;")
        btn_compare.clicked.connect(lambda: self.tabs.setCurrentIndex(0))
        layout.addWidget(btn_compare)
        
        self.load_gallery()

    def load_gallery(self):
        gallery_dir = Path(__file__).resolve().parent / 'gallery'
        if not gallery_dir.exists():
            return
            
        row, col = 0, 0
        max_cols = 3
        
        for png_path in sorted(gallery_dir.glob("*.png")):
            if "_saliency" in png_path.name:
                continue
                
            json_path = png_path.with_suffix('.json')
            if not json_path.exists():
                json_path = gallery_dir / f"{png_path.stem}_metadata.json"
                
            frame = QFrame()
            frame.setStyleSheet("QFrame { border: 2px solid #555; background-color: #222; margin: 10px; }")
            flayout = QVBoxLayout(frame)
            
            img_lbl = QLabel()
            pix = QPixmap(str(png_path)).scaled(200, 200, Qt.KeepAspectRatio)
            img_lbl.setPixmap(pix)
            img_lbl.setAlignment(Qt.AlignCenter)
            flayout.addWidget(img_lbl)
            
            if json_path.exists():
                try:
                    with open(json_path, 'r') as f:
                        meta = json.load(f)
                    
                    text = f"Cluster: {meta.get('cluster_id', 'N/A')}\nStabilità: {meta.get('stability', '')}\nScore: {meta.get('novelty_score', '')}"
                    desc_lbl = QLabel(text)
                    desc_lbl.setStyleSheet("color: white; border: none;")
                    flayout.addWidget(desc_lbl)
                except Exception as e:
                    logger.error(f"Error loading metadata: {e}")
            
            self.grid_layout.addWidget(frame, row, col)
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    def reset_all(self):
        self.scene1.reset()
        self.scene2.reset()
        self.dash_cls.reset()
        self.dash_patch.reset()
        self.trick_score_wins = 0
        self.trick_score_total = 0
        self.trick_score_lbl.setText("Hai ingannato l'AI 0 volte su 0 tentativi")
        self.trick_result_lbl.setText("")
        self.saliency_overlay2.hide()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MakerFaireApp()
    # window.showFullScreen() # Utile per la modalità finale
    window.showMaximized()
    sys.exit(app.exec_())
