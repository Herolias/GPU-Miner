import logging
import sys
import time
from pathlib import Path

# Add current directory to path so we can import core modules
sys.path.append(str(Path(__file__).parent))

from core.config import config
from core.wallet_pool import WalletPool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

def main():
    print("=" * 60)
    print("GPU Miner - Force Consolidation Tool")
    print("=" * 60)
    print("This script will attempt to consolidate ALL wallets found in")
    print("wallets_gpu_*.json files, ignoring their previous status.")
    print("\nIMPORTANT: Please ensure the miner is STOPPED before running this.")
    print("=" * 60)

    # 1. Check Configuration
    consolidate_address = config.get('wallet.consolidate_address')
    if not consolidate_address:
        logging.error("No 'consolidate_address' found in config.yaml!")
        logging.error("Please set a valid wallet address in config.yaml and try again.")
        return

    print(f"\nTarget Address: {consolidate_address}")
    print("Type 'yes' to proceed: ", end='', flush=True)
    
    # Use sys.stdin.readline() instead of input() to avoid buffering issues on some terminals
    try:
        confirm = sys.stdin.readline().strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return
    
    if confirm != 'yes':
        print("Aborted.")
        return

    # 2. Initialize Pool System
    wallet_pool = WalletPool()
    base_dir = Path(".")
    
    # 3. Find all wallet files (GPU and CPU)
    wallet_files = list(base_dir.glob("wallets_gpu_*.json"))
    cpu_wallet_file = base_dir / "wallets_cpu.json"
    if cpu_wallet_file.exists():
        wallet_files.append(cpu_wallet_file)
    
    if not wallet_files:
        logging.warning("No wallet files found (wallets_gpu_*.json or wallets_cpu.json).")
        return

    total_consolidated = 0
    total_failed = 0
    total_skipped = 0

    for file_path in wallet_files:
        print(f"\nProcessing {file_path.name}...")
        
        try:
            # Extract pool ID from filename
            # "wallets_gpu_0.json" → 0 (int)
            # "wallets_cpu.json" → "cpu" (str)
            try:
                if "cpu" in file_path.stem:
                    pool_id = "cpu"
                else:
                    pool_id = int(file_path.stem.split('_')[-1])
            except ValueError:
                logging.warning(f"Skipping file with unexpected name format: {file_path.name}")
                continue

            # Load pool directly using internal method to respect locks if possible
            # But since we are a separate process and miner should be stopped, 
            # we will just use the public methods or internal helpers if needed.
            # We'll use _load_pool and _save_pool from WalletPool instance
            
            # We need to acquire locks just in case
            thread_lock = wallet_pool._get_thread_lock(pool_id)
            file_lock = wallet_pool._get_file_lock(pool_id)
            
            with thread_lock:
                with file_lock:
                    pool_data = wallet_pool._load_pool(pool_id)
                    
                    if "wallets" not in pool_data or not pool_data["wallets"]:
                        print("  No wallets in this file.")
                        continue

                    file_consolidated = 0
                    
                    for i, wallet in enumerate(pool_data["wallets"]):
                        address = wallet.get("address", "unknown")
                        print(f"  [{i+1}/{len(pool_data['wallets'])}] Checking {address[:10]}... ", end="", flush=True)

                        if wallet.get("is_dev_wallet"):
                            print("SKIPPED (dev wallet)")
                            total_skipped += 1
                            continue
                        
                        # FORCE RESET status to ensure we try again
                        # We only skip if it's ALREADY marked true AND we trust it?
                        # No, user wants to re-consolidate "skipped" ones which might be marked True.
                        # So we fundamentally MUST try again.
                        
                        # However, _consolidate_wallet checks is_consolidated.
                        # So we must set it to False temporarily.
                        was_consolidated = wallet.get("is_consolidated", False)
                        wallet['is_consolidated'] = False
                        
                        # Attempt consolidation
                        # This will make the API call
                        success = wallet_pool._consolidate_wallet(wallet)
                        
                        if success:
                            print("SUCCESS")
                            file_consolidated += 1
                            total_consolidated += 1
                        else:
                            # If it failed, it might be because it has 0 balance.
                            # In that case, should we restore the old flag?
                            # The user said "wallets that have been marked as true and have been skipped".
                            # If they were skipped, they have balance.
                            # If they have 0 balance, API returns false.
                            # If we leave it as False, the miner will try again later (which is good).
                            print("SKIPPED/FAILED (Low balance?)")
                            # If it was previously True, and now failed, maybe we should keep it False
                            # so the miner retries later when it has balance?
                            # Or if it failed because of network error?
                            # Let's leave it as the result of _consolidate_wallet (which sets it to True on success)
                            # If it returns False, wallet['is_consolidated'] remains False (from our reset above).
                            total_failed += 1

                    # Save changes
                    if file_consolidated > 0 or total_failed > 0:
                        wallet_pool._save_pool(pool_id, pool_data)
                        print(f"  Saved updates to {file_path.name}")

        except Exception as e:
            logging.error(f"Error processing {file_path.name}: {e}")

    print("\n" + "=" * 60)
    print(f"Consolidation Complete.")
    print(f"  Consolidated: {total_consolidated}")
    print(f"  Skipped (dev wallets): {total_skipped}")
    print(f"  Failed/Already consolidated: {total_failed}")
    print(f"  Total processed: {total_consolidated + total_skipped + total_failed}")
    print("=" * 60)

if __name__ == "__main__":
    main()
