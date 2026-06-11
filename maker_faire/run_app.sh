#!/bin/bash
echo "=============================================="
echo "  Avvio App 'Cacciatori di Onde'"
echo "  Maker Faire Rome 2026"
echo "=============================================="

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$BASE_DIR/.."

# Se esiste l'ambiente virtuale, attivalo
if [ -f "venv/bin/activate" ]; then
    echo "Attivazione virtual environment..."
    source venv/bin/activate
fi

echo "Lancio dell'interfaccia PyQt5..."
export PYTHONPATH=$(pwd)
python maker_faire/maker_faire_app.py
