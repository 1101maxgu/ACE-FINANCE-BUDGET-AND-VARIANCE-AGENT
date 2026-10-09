@echo off
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3.11 or newer is required. Install it from python.org, tick "Add to PATH", then run this again. & pause & exit /b 1)
if not exist .venv\Scripts\python.exe (
    echo First run: setting things up, this takes a few minutes...
    python -m venv .venv || (pause & exit /b 1)
    call .venv\Scripts\activate.bat
    python -m pip install -r requirements.txt || (pause & exit /b 1)
) else (
    call .venv\Scripts\activate.bat
)
python -m streamlit run app.py
pause
