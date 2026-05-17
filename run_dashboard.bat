@echo off
cd /d "%~dp0"
python -m streamlit run dashboard/Principal.py
if errorlevel 1 (
    echo.
    echo Si falla, prueba con el mismo Python que usaste para pip install:
    echo   python -m pip install -r requirements.txt
    echo   python -m streamlit run dashboard/Principal.py
    pause
)
