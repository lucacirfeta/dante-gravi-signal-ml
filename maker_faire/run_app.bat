@echo off
echo ==============================================
echo   Avvio App "Cacciatori di Onde"
echo   Maker Faire Rome 2026
echo ==============================================

set BASE_DIR=%~dp0
cd /d "%BASE_DIR%..\"

:: Se esiste l'ambiente virtuale, attivalo
if exist "venv\Scripts\activate.bat" (
    echo Attivazione virtual environment...
    call venv\Scripts\activate.bat
)

echo Lancio dell'interfaccia PyQt5...
set PYTHONPATH=%cd%
python maker_faire\maker_faire_app.py

pause
