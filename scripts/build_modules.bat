@echo off
REM Build GPU Modules Locally (Windows)
REM Compiles engine.py and kernels.py into .pyd binaries

echo ====================================
echo GPU Module Builder for Windows
echo ====================================
echo.

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo Warning: No virtual environment found. Using system Python.
)

REM Install Nuitka if not present
echo.
echo Checking for Nuitka...
python -m pip show nuitka >nul 2>&1
if errorlevel 1 (
    echo Nuitka not found. Installing...
    python -m pip install nuitka ordered-set zstandard
) else (
    echo Nuitka is already installed.
)

REM Install project dependencies
echo.
echo Installing project dependencies...
python -m pip install -r requirements.txt

REM Create output directory
echo.
echo Creating binary directory...
if not exist "gpu_core\bin\windows" mkdir gpu_core\bin\windows

REM Clean old build artifacts
echo.
echo Cleaning old build artifacts...
if exist "build_output" rmdir /s /q build_output
if exist "*.pyd" del /q *.pyd

REM Build modules
echo.
echo ====================================
echo Building engine.py...
echo ====================================
python -m nuitka --module --output-dir=build_output gpu_core\engine.py
if errorlevel 1 (
    echo ERROR: Failed to compile engine.py
    pause
    exit /b 1
)

echo.
echo ====================================
echo Building kernels.py...
echo ====================================
python -m nuitka --module --output-dir=build_output gpu_core\kernels.py
if errorlevel 1 (
    echo ERROR: Failed to compile kernels.py
    pause
    exit /b 1
)

REM Move binaries to destination
echo.
echo Moving binaries to gpu_core\bin\windows\...
move build_output\*.pyd gpu_core\bin\windows\ >nul 2>&1

REM Verify binaries
echo.
echo ====================================
echo Verifying binaries...
echo ====================================
dir gpu_core\bin\windows\*.pyd
if errorlevel 1 (
    echo ERROR: No .pyd files found!
    pause
    exit /b 1
)

REM Clean up
echo.
echo Cleaning up temporary files...
if exist "build_output" rmdir /s /q build_output

REM Test import
echo.
echo ====================================
echo Testing GPU module import...
echo ====================================
python -c "from gpu_core import GPU_AVAILABLE, GPUEngine; print(f'GPU Available: {GPU_AVAILABLE}'); print(f'GPUEngine: {GPUEngine}')"
if errorlevel 1 (
    echo ERROR: Failed to import GPU modules!
    pause
    exit /b 1
)

echo.
echo ====================================
echo SUCCESS! GPU modules built successfully.
echo ====================================
echo.
echo The following files were created:
dir /b gpu_core\bin\windows\*.pyd
echo.
echo You can now commit these binaries to your repository:
echo   git add gpu_core/bin/windows/
echo   git commit -m "Update GPU module binaries for Windows"
echo.
pause
