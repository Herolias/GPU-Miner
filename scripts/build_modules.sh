#!/bin/bash
# Build GPU Modules Locally (Linux/macOS)
# Compiles engine.py and kernels.py into .so binaries

set -e  # Exit on error

echo "===================================="
echo "GPU Module Builder for Unix"
echo "===================================="
echo ""

# Detect platform
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    PLATFORM="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    PLATFORM="macos"
else
    echo "ERROR: Unsupported platform: $OSTYPE"
    exit 1
fi

echo "Platform detected: $PLATFORM"
echo ""

# Activate virtual environment if it exists
if [ -f "venv/bin/activate" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "Warning: No virtual environment found. Using system Python."
fi

# Install Nuitka if not present
echo ""
echo "Checking for Nuitka..."
if ! python -m pip show nuitka &>/dev/null; then
    echo "Nuitka not found. Installing..."
    python -m pip install nuitka ordered-set zstandard
else
    echo "Nuitka is already installed."
fi

# Install project dependencies
echo ""
echo "Installing project dependencies..."
python -m pip install -r requirements.txt

# Create output directory
echo ""
echo "Creating binary directory..."
mkdir -p "gpu_core/bin/$PLATFORM"

# Clean old build artifacts
echo ""
echo "Cleaning old build artifacts..."
rm -rf build_output
rm -f *.so

# Build modules
echo ""
echo "===================================="
echo "Building engine.py..."
echo "===================================="
python -m nuitka --module --output-dir=build_output gpu_core/engine.py

echo ""
echo "===================================="
echo "Building kernels.py..."
echo "===================================="
python -m nuitka --module --output-dir=build_output gpu_core/kernels.py

# Move binaries to destination
echo ""
echo "Moving binaries to gpu_core/bin/$PLATFORM/..."
find build_output -name "*.so" -exec mv {} "gpu_core/bin/$PLATFORM/" \;

# Verify binaries
echo ""
echo "===================================="
echo "Verifying binaries..."
echo "===================================="
ls -lh "gpu_core/bin/$PLATFORM/"*.so || {
    echo "ERROR: No .so files found!"
    exit 1
}

# Clean up
echo ""
echo "Cleaning up temporary files..."
rm -rf build_output

# Test import
echo ""
echo "===================================="
echo "Testing GPU module import..."
echo "===================================="
python -c "from gpu_core import GPU_AVAILABLE, GPUEngine; print(f'GPU Available: {GPU_AVAILABLE}'); print(f'GPUEngine: {GPUEngine}')" || {
    echo "ERROR: Failed to import GPU modules!"
    exit 1
}

echo ""
echo "===================================="
echo "SUCCESS! GPU modules built successfully."
echo "===================================="
echo ""
echo "The following files were created:"
ls -1 "gpu_core/bin/$PLATFORM/"*.so
echo ""
echo "You can now commit these binaries to your repository:"
echo "  git add gpu_core/bin/$PLATFORM/"
echo "  git commit -m \"Update GPU module binaries for $PLATFORM\""
echo ""
