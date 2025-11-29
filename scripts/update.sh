#!/bin/bash
echo "Updating GPU Miner..."

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "Error: Git is not installed."
    exit 1
fi

# Backup user config
echo "Backing up configuration..."
python3 scripts/migrate_config.py --backup

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
    echo "Error: Failed to update dependencies."
    exit 1
fi

echo "Update complete!"
