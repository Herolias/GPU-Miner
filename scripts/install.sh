#!/bin/bash
set -e

echo "============================================"
echo "  GPU Miner - Smart Installer"
echo "============================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

#==========================================
# Check 1: Python
#==========================================
echo "[1/5] Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR] Python 3 is not installed!${NC}"
    echo ""
    echo "Please install Python 3.12+ using your package manager:"
    echo "  Ubuntu/Debian: sudo apt update && sudo apt install python3 python3-pip python3-venv"
    echo "  Fedora/RHEL:   sudo dnf install python3 python3-pip"
    echo "  Arch:          sudo pacman -S python python-pip"
    echo ""
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo -e "${GREEN}[OK] Python $PYTHON_VERSION found${NC}"
echo ""

#==========================================
# Check 2: NVIDIA GPU
#==========================================
echo "[2/5] Checking NVIDIA GPU..."
if ! command -v nvidia-smi &> /dev/null; then
    echo -e "${YELLOW}[WARNING] nvidia-smi not found - NVIDIA GPU may not be available${NC}"
    echo ""
    echo "This miner requires an NVIDIA GPU with CUDA support."
    echo "Please ensure you have:"
    echo "  1. An NVIDIA GPU (GTX 10-series or newer)"
    echo "  2. NVIDIA drivers installed"
    echo ""
    echo "To install NVIDIA drivers:"
    echo "  Ubuntu: sudo ubuntu-drivers autoinstall"
    echo "  Or download from: https://www.nvidia.com/Download/index.aspx"
    echo ""
    read -p "Continue anyway? (GPU features will be disabled) [y/N]: " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "${GREEN}[OK] NVIDIA GPU detected${NC}"
    nvidia-smi --query-gpu=name --format=csv,noheader
fi
echo ""

#==========================================
# Check 3: CUDA Toolkit
#==========================================
echo "[3/5] Checking CUDA Toolkit..."
CUDA_FOUND=0
CUDA_VERSION=""
CUDA_PATH_TO_EXPORT=""

# Check for nvcc (CUDA compiler) in PATH first
if command -v nvcc &> /dev/null; then
    CUDA_FOUND=1
    CUDA_VERSION=$(nvcc --version | grep "release" | sed 's/.*release //' | awk '{print $1}' | sed 's/,//')
    echo -e "${GREEN}[OK] CUDA Toolkit $CUDA_VERSION found (nvcc in PATH)${NC}"
else
    # nvcc not in PATH, check common CUDA installation paths
    for cuda_path in /usr/local/cuda-13.* /usr/local/cuda-12.* /usr/local/cuda-11.* /usr/local/cuda /opt/cuda; do
        if [ -d "$cuda_path" ] && [ -f "$cuda_path/bin/nvcc" ]; then
            CUDA_FOUND=1
            CUDA_VERSION=$($cuda_path/bin/nvcc --version | grep "release" | sed 's/.*release //' | awk '{print $1}' | sed 's/,//')
            CUDA_PATH_TO_EXPORT="$cuda_path"
            echo -e "${YELLOW}[WARNING] CUDA Toolkit $CUDA_VERSION found at $cuda_path${NC}"
            echo -e "${YELLOW}          but nvcc is not in PATH${NC}"
            break
        fi
    done
fi

if [ $CUDA_FOUND -eq 0 ]; then
    echo -e "${YELLOW}[WARNING] CUDA Toolkit not found${NC}"
    echo ""
    echo "CUDA is required for GPU acceleration. Without it, PyCUDA installation will fail."
    echo ""
    echo "Download CUDA Toolkit from:"
    echo "  https://developer.nvidia.com/cuda-downloads"
    echo ""
    echo "Installation guide:"
    echo "  https://docs.nvidia.com/cuda/cuda-installation-guide-linux/"
    echo ""
    echo "Recommended versions: CUDA 11.8, 12.x, or 13.x"
    echo ""
    read -p "Continue without CUDA (installation will likely fail)? [y/N]: " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
elif [ -n "$CUDA_PATH_TO_EXPORT" ]; then
    # CUDA found but not in PATH - provide instructions
    echo ""
    echo -e "${YELLOW}IMPORTANT: Add CUDA to your environment${NC}"
    echo "Run these commands or add them to ~/.bashrc:"
    echo ""
    echo "  export PATH=\"$CUDA_PATH_TO_EXPORT/bin:\$PATH\""
    echo "  export LD_LIBRARY_PATH=\"$CUDA_PATH_TO_EXPORT/lib64:\$LD_LIBRARY_PATH\""
    echo ""
    echo "Then run 'source ~/.bashrc' or restart your terminal."
    echo ""
    
    # Temporarily export for this session
    export PATH="$CUDA_PATH_TO_EXPORT/bin:$PATH"
    export LD_LIBRARY_PATH="$CUDA_PATH_TO_EXPORT/lib64:$LD_LIBRARY_PATH"
    echo "Temporarily added CUDA to PATH for this installation session."
    echo ""
    
    read -p "Continue with installation? [y/N]: " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
echo ""

#==========================================
# Check 4: Build Tools
#==========================================
echo "[4/5] Checking Build Tools..."
BUILD_TOOLS_OK=1

# Check for g++
if ! command -v g++ &> /dev/null; then
    echo -e "${YELLOW}[WARNING] g++ compiler not found${NC}"
    BUILD_TOOLS_OK=0
fi

# Check for make
if ! command -v make &> /dev/null; then
    echo -e "${YELLOW}[WARNING] make not found${NC}"
    BUILD_TOOLS_OK=0
fi

# Check for python3-dev headers
if ! dpkg -l | grep -q "python3-dev\|python3\.12-dev" 2>/dev/null && ! rpm -qa | grep -q "python3-devel" 2>/dev/null; then
    echo -e "${YELLOW}[WARNING] Python development headers not found${NC}"
    BUILD_TOOLS_OK=0
fi

if [ $BUILD_TOOLS_OK -eq 0 ]; then
    echo ""
    echo "Build tools and Python development headers are required to compile PyCUDA."
    echo ""
    echo "Install required packages using your package manager:"
    echo "  Ubuntu/Debian: sudo apt-get install python3-dev python3.12-dev build-essential"
    echo "  Fedora/RHEL:   sudo dnf groupinstall 'Development Tools' && sudo dnf install python3-devel"
    echo "  Arch:          sudo pacman -S base-devel python"
    echo ""
    read -p "Continue without build tools (PyCUDA installation will fail)? [y/N]: " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "${GREEN}[OK] Build tools found${NC}"
fi
echo ""

#==========================================
# Installation
#==========================================
echo "[5/5] Installing GPU Miner..."
echo ""

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo -e "${RED}[ERROR] Failed to create virtual environment${NC}"
        exit 1
    fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Failed to activate virtual environment${NC}"
    exit 1
fi

# Upgrade pip
echo "Upgrading pip..."
python -m pip install --upgrade pip > /dev/null 2>&1

# Install dependencies
echo "Installing dependencies from requirements.txt..."
echo "This may take several minutes, especially for PyCUDA..."
echo ""
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}[ERROR] Installation failed!${NC}"
    echo ""
    echo "Common reasons:"
    echo "  1. Missing CUDA Toolkit - Install from https://developer.nvidia.com/cuda-downloads"
    echo "  2. Missing build tools - Install build-essential (Ubuntu) or Development Tools (Fedora)"
    echo "  3. Incompatible versions - Ensure CUDA 11.8+ and Python 3.12+"
    echo ""
    echo "Please fix the issues above and run this script again."
    echo ""
    exit 1
fi

# Make update script executable
echo "Setting up update script permissions..."
chmod +x scripts/update.sh

echo ""
echo "============================================"
echo "  Installation Complete!"
echo "============================================"
echo ""
echo "To start the miner:"
echo "  1. Activate venv: source venv/bin/activate"
echo "  2. Run: python main.py"
echo ""
echo "Or simply run: ./venv/bin/python main.py"
echo ""
echo "For configuration, edit config.yaml"
echo ""
