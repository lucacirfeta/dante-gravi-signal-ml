import os
import random

base_dir = "E:/o4a"
if not os.path.exists(base_dir):
    base_dir = "/mnt/e/o4a"

try:
    sessions = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d)) and d.isdigit()]
    print(f"Total sessions available: {len(sessions)}")
    
    random.seed(42)
    pilot = random.sample(sorted(sessions), min(5, len(sessions)))
    print(f"Selected pilot sessions: {pilot}")
except Exception as e:
    print(f"Error: {e}")
