#!/bin/bash
echo "Updating GPU Miner..."

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "Error: Git is not installed."
    exit 1
fi

# Stash local changes (like config.yaml edits)
echo "Saving your local changes..."
git stash push -m "Auto-stash before update"

# Pull latest changes
echo "Pulling latest changes..."
git pull
if [ $? -ne 0 ]; then
    echo "Error: Failed to pull changes."
    exit 1
fi

# Restore local changes
echo "Restoring your local changes..."
git stash pop
if [ $? -ne 0 ]; then
    echo ""
    echo "WARNING: There may be conflicts between your config and the new version."
    echo "Please check config.yaml and resolve any conflicts marked with <<<<<<<, =======, >>>>>>>"
    echo ""
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
