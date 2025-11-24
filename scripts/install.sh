#!/bin/bash
echo "Installing GPU Miner..."

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is not installed! Please install it and try again."
    exit 1
fi

# Create Virtual Environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate and Install
echo "Installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt

echo ""
echo "Installation Complete!"
echo "To start the miner, run: ./venv/bin/python main.py"
echo ""
