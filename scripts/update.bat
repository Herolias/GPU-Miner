@echo off
echo Updating GPU Miner...

REM Check if git is installed
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Git is not installed or not in PATH.
    echo Please install Git to use the auto-update feature.
    pause
    exit /b 1
)

REM Pull latest changes
echo Pulling latest changes...
git pull
if %errorlevel% neq 0 (
    echo Error: Failed to pull changes.
    pause
    exit /b 1
)

REM Update dependencies
echo Updating dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Error: Failed to update dependencies.
    pause
    exit /b 1
)

echo Update complete!
pause
