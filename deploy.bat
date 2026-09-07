@echo off
REM Rebuild the page from fresh data, then deploy dist/ to Vercel production.
cd /d "%~dp0"
if not exist .venv (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)
call .venv\Scripts\activate.bat
python main.py
if errorlevel 1 exit /b 1
vercel deploy dist --prod
