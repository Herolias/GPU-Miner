#!/usr/bin/env python3
"""
Config Migration Script

Handles backup and restoration of user configuration during updates.
Preserves user-changeable settings while allowing the codebase to update defaults.
"""

import os
import sys
import json
import yaml
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

CONFIG_FILE = Path("config.yaml")
BACKUP_FILE = Path("config_backup.json")

def load_yaml(path):
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return {}

def save_yaml(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        print(f"Saved config to {path}")
    except Exception as e:
        print(f"Error saving {path}: {e}")

def backup_config():
    """Backup user-changeable settings from config.yaml."""
    if not CONFIG_FILE.exists():
        print("No config.yaml found to backup.")
        return

    config = load_yaml(CONFIG_FILE)
    backup_data = {}

    # Define keys to preserve
    # We only want to preserve things the user MIGHT have changed.
    # We do NOT want to preserve things that we removed/refactored (like gpu.batch_size)
    
    # Miner settings
    if 'miner' in config:
        backup_data['miner'] = {}
        if 'api_url' in config['miner']:
            backup_data['miner']['api_url'] = config['miner']['api_url']
    
    # Wallet settings
    if 'wallet' in config:
        backup_data['wallet'] = {}
        if 'consolidate_address' in config['wallet']:
            backup_data['wallet']['consolidate_address'] = config['wallet']['consolidate_address']
        if 'wallets_per_gpu' in config['wallet']:
            backup_data['wallet']['wallets_per_gpu'] = config['wallet']['wallets_per_gpu']

    # CPU settings
    if 'cpu' in config:
        backup_data['cpu'] = {}
        if 'enabled' in config['cpu']:
            backup_data['cpu']['enabled'] = config['cpu']['enabled']
        if 'workers' in config['cpu']:
            backup_data['cpu']['workers'] = config['cpu']['workers']
            
    # GPU settings (only cuda path)
    if 'gpu' in config:
        if 'cuda_toolkit_path' in config['gpu']:
            if 'gpu' not in backup_data:
                backup_data['gpu'] = {}
            backup_data['gpu']['cuda_toolkit_path'] = config['gpu']['cuda_toolkit_path']

    try:
        with open(BACKUP_FILE, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2)
        print(f"Backed up user settings to {BACKUP_FILE}")
    except Exception as e:
        print(f"Error saving backup: {e}")

def restore_config():
    """Restore user settings into a clean config.yaml."""
    if not BACKUP_FILE.exists():
        print("No backup file found. Skipping restore.")
        return

    try:
        with open(BACKUP_FILE, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)
    except Exception as e:
        print(f"Error loading backup: {e}")
        return

    # Load the current (clean) config.yaml
    # If it doesn't exist (fresh checkout?), we might need to generate it or use defaults.
    # Assuming the update process checked out a clean config.yaml or we can import defaults.
    
    # Strategy:
    # 1. Try to load config.yaml (which should be the new version after git pull/checkout)
    # 2. If not exists, try to load DEFAULT_CONFIG from core.config and save it
    
    current_config = load_yaml(CONFIG_FILE)
    
    if not current_config:
        print("config.yaml not found or empty. Generating from defaults...")
        try:
            from core.config import DEFAULT_CONFIG
            current_config = DEFAULT_CONFIG.copy()
        except ImportError:
            print("Could not import DEFAULT_CONFIG. Cannot restore.")
            return

    # Merge backup into current
    # We do a deep merge for known sections
    
    for section, values in backup_data.items():
        if section not in current_config:
            current_config[section] = {}
        
        for key, value in values.items():
            # Only restore if the key is valid in the new config structure
            # OR if we want to force keep user settings.
            # Generally safer to only update existing keys or known keys.
            current_config[section][key] = value
            print(f"Restored {section}.{key} = {value}")

    save_yaml(CONFIG_FILE, current_config)
    
    # Cleanup backup
    try:
        os.remove(BACKUP_FILE)
        print("Backup file removed.")
    except:
        pass

def main():
    parser = argparse.ArgumentParser(description="Config Migration Tool")
    parser.add_argument("--backup", action="store_true", help="Backup user config")
    parser.add_argument("--restore", action="store_true", help="Restore user config")
    
    args = parser.parse_args()
    
    if args.backup:
        backup_config()
    elif args.restore:
        restore_config()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
