import sys
import os
import yaml
import shutil
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.getcwd())

from core.config import config, DEFAULT_CONFIG

def verify_self_healing():
    print("Verifying Self-Healing Config...")
    
    config_path = "config.yaml"
    broken_path = "config.yaml.broken"
    
    # 1. Test Recovery from Corrupted File
    print("\n1. Testing Recovery from Corrupted File...")
    
    # Create corrupted file with some valid data
    corrupted_content = """
<<<<<<< HEAD
miner:
  api_url: https://old.api.com
=======
miner:
  api_url: https://recovered.api.com
>>>>>>> feature/new-api

wallet:
  consolidate_address: recovered_wallet
  wallets_per_gpu: 20

gpu:
  cuda_toolkit_path: /usr/local/cuda-12.0
  
cpu:
  enabled: True
  workers: 4
"""
    with open(config_path, 'w') as f:
        f.write(corrupted_content)
        
    # Force reload
    print("Loading corrupted config...")
    config.load(config_path)
    
    # Verify Recovery
    if config.data['miner']['api_url'] == "https://recovered.api.com":
        print("PASS: Recovered api_url")
    else:
        print(f"FAIL: api_url mismatch. Got {config.data['miner']['api_url']}")
        return False
        
    if config.data['wallet']['consolidate_address'] == "recovered_wallet":
        print("PASS: Recovered consolidate_address")
    else:
        print(f"FAIL: consolidate_address mismatch. Got {config.data['wallet']['consolidate_address']}")
        return False

    if config.data['wallet']['wallets_per_gpu'] == 20:
        print("PASS: Recovered wallets_per_gpu")
    else:
        print(f"FAIL: wallets_per_gpu mismatch. Got {config.data['wallet']['wallets_per_gpu']}")
        return False
        
    if config.data['gpu']['cuda_toolkit_path'] == "/usr/local/cuda-12.0":
        print("PASS: Recovered cuda_toolkit_path")
    else:
        print(f"FAIL: cuda_toolkit_path mismatch. Got {config.data['gpu']['cuda_toolkit_path']}")
        return False

    if config.data['cpu']['enabled'] == True:
        print("PASS: Recovered cpu.enabled")
    else:
        print(f"FAIL: cpu.enabled mismatch. Got {config.data['cpu']['enabled']}")
        return False

    if config.data['cpu']['workers'] == 4:
        print("PASS: Recovered cpu.workers")
    else:
        print(f"FAIL: cpu.workers mismatch. Got {config.data['cpu']['workers']}")
        return False
        
    if os.path.exists(broken_path):
        print("PASS: Broken file backed up")
    else:
        print("FAIL: Broken file NOT backed up")
        return False

    # 2. Test Sanitization (Removal of deprecated keys)
    print("\n2. Testing Sanitization...")
    
    # Create dirty config
    dirty_config = DEFAULT_CONFIG.copy()
    dirty_config['gpu']['batch_size'] = 123456
    dirty_config['miner']['max_workers'] = 10
    
    with open(config_path, 'w') as f:
        yaml.dump(dirty_config, f)
        
    # Reload
    print("Loading dirty config...")
    config.load(config_path)
    
    # Verify Removal
    with open(config_path, 'r') as f:
        clean_config = yaml.safe_load(f)
        
    if 'batch_size' not in clean_config.get('gpu', {}):
        print("PASS: Removed gpu.batch_size")
    else:
        print("FAIL: gpu.batch_size still present")
        return False
        
    if 'max_workers' not in clean_config.get('miner', {}):
        print("PASS: Removed miner.max_workers")
    else:
        print("FAIL: miner.max_workers still present")
        return False

    # Cleanup
    if os.path.exists(config_path): os.remove(config_path)
    if os.path.exists(broken_path): os.remove(broken_path)
    
    return True

if __name__ == "__main__":
    if verify_self_healing():
        print("\nSUCCESS: Self-healing verified!")
        sys.exit(0)
    else:
        print("\nFAILURE: Verification failed!")
        sys.exit(1)
