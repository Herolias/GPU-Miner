@echo off
echo Installing GPU Miner...

REM Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed! Please install Python 3.10+ and try again.
    pause
    exit /b 1
)

REM Create Virtual Environment
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate and Install
echo Installing dependencies...
call venv\Scripts\activate
pip install -r requirements.txt

echo.
echo Installation Complete!
echo To start the miner, run: venv\Scripts\python main.py
echo.
pause
