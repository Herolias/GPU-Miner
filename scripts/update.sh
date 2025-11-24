#!/bin/bash
echo "Updating GPU Miner..."

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "Error: Git is not installed."
    exit 1
fi

# Pull latest changes
echo "Pulling latest changes..."
git pull
if [ $? -ne 0 ]; then
    echo "Error: Failed to pull changes."
    exit 1
fi

# Update dependencies
echo "Updating dependencies..."
source venv/bin/activate
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Error: Failed to update dependencies."
    exit 1
fi

echo "Update complete!"
