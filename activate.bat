@echo off
REM Enter the virtual environment.
cd /d "%~dp0"
if not exist .venv (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)
cmd /k .venv\Scripts\activate.bat
