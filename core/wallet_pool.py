"""
Per-GPU Wallet Pool Management System

This module provides JSON-based wallet management with per-GPU pools
to prevent wallet contention in multi-GPU mining setups.
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from filelock import FileLock
from typing import Dict, Optional, List

from .config import config
from .types import WalletOptional, PoolId
from . import wallet_utils
from .dev_fee import dev_fee_manager


class WalletPool:
    """Manages per-GPU wallet pools using JSON files with file locking."""
    
    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[PoolId, threading.Lock] = {}
        self._file_locks: Dict[PoolId, FileLock] = {}
        self._consolidation_threads: Dict[PoolId, threading.Thread] = {}
        self._stop_consolidation = threading.Event()
    
    def _normalize_pool(self, pool: Dict) -> bool:
        """Ensure wallet entries contain required metadata. Returns True if mutated."""
        changed = False
        wallets = pool.get("wallets", [])
        for wallet in wallets:
            if 'is_dev_wallet' not in wallet:
                wallet['is_dev_wallet'] = False
                changed = True
            if 'solved_challenges' not in wallet:
                wallet['solved_challenges'] = wallet.get('solved_challenges', [])
            if 'in_use' not in wallet:
                wallet['in_use'] = wallet.get('in_use', False)
            if 'current_challenge' not in wallet:
                wallet['current_challenge'] = wallet.get('current_challenge', None)
            if 'allocated_at' not in wallet and wallet.get('in_use'):
                wallet['allocated_at'] = wallet.get('allocated_at', datetime.now().isoformat())
        return changed
    
    def _count_wallets(self, pool: Dict, *, is_dev_wallet: bool) -> int:
        """Count wallets in a pool filtered by dev flag."""
        return len([
            w for w in pool.get("wallets", [])
            if w.get('is_dev_wallet', False) is is_dev_wallet
        ])
    
    def _get_consolidate_target(self, wallet_data: WalletOptional) -> Optional[str]:
        """Return consolidation destination for a wallet."""
        if wallet_data.get('is_dev_wallet'):
            return dev_fee_manager.get_dev_consolidate_address()
        return config.get('wallet.consolidate_address')
        
    def _get_pool_path(self, pool_id: PoolId) -> Path:
        """Get the JSON file path for a specific pool (GPU or CPU)."""
        if isinstance(pool_id, int):
            return self.base_dir / f"wallets_gpu_{pool_id}.json"
        return self.base_dir / f"wallets_{pool_id}.json"
    
    def _get_lock_path(self, pool_id: PoolId) -> Path:
        """Get the lock file path for a specific pool."""
        if isinstance(pool_id, int):
            return self.base_dir / f"wallets_gpu_{pool_id}.json.lock"
        return self.base_dir / f"wallets_{pool_id}.json.lock"
    
    def _get_thread_lock(self, pool_id: PoolId) -> threading.Lock:
        """Get or create a thread lock for a pool."""
        if pool_id not in self._locks:
            self._locks[pool_id] = threading.Lock()
        return self._locks[pool_id]
    
    def _get_file_lock(self, pool_id: PoolId) -> FileLock:
        """Get or create a file lock for a pool."""
        if pool_id not in self._file_locks:
            lock_path = self._get_lock_path(pool_id)
            self._file_locks[pool_id] = FileLock(str(lock_path), timeout=10)
        return self._file_locks[pool_id]
    
    def _load_pool(self, pool_id: PoolId) -> Dict:
        """Load wallet pool from JSON file."""
        pool_path = self._get_pool_path(pool_id)
        
        if not pool_path.exists():
            return {"pool_id": pool_id, "wallets": []}
        
        try:
            with open(pool_path, 'r', encoding='utf-8') as f:
                pool = json.load(f)
        except Exception as e:
            logging.error(f"Error loading wallet pool {pool_id}: {e}")
            return {"pool_id": pool_id, "wallets": []}
        
        if "wallets" not in pool:
            pool["wallets"] = []
        
        try:
            if self._normalize_pool(pool):
                self._save_pool(pool_id, pool)
        except Exception as e:
            logging.debug(f"Unable to normalize wallet pool {pool_id}: {e}")
        
        return pool
    
    def _save_pool(self, pool_id: PoolId, pool_data: Dict) -> None:
        """Save wallet pool to JSON file."""
        pool_path = self._get_pool_path(pool_id)
        
        try:
            with open(pool_path, 'w', encoding='utf-8') as f:
                json.dump(pool_data, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving wallet pool {pool_id}: {e}")
            
    def _consolidate_wallet(self, wallet_data: WalletOptional) -> bool:
        """
        Consolidate a wallet's earnings to the configured consolidate_address.
        
        Args:
            wallet_data: Wallet dictionary to consolidate
            
        Returns:
            True if successful or already consolidated, False otherwise
        """
        consolidate_address = self._get_consolidate_target(wallet_data)
        if not consolidate_address:
            return False  # No consolidation configured for this wallet
        
        # Skip if already consolidated
        if wallet_data.get('is_consolidated', False):
            return True
        
        # Use centralized consolidation logic
        return wallet_utils.consolidate_wallet(wallet_data, consolidate_address)

    def start_consolidation_thread(self, pool_id: PoolId) -> None:
        """
        Start a background thread to consolidate wallets for this pool.
        
        Args:
            pool_id: Pool identifier (GPU ID or CPU pool name)
        """
        # Check if thread is stopping
        if self._stop_consolidation.is_set():
            return
        
        t = threading.Thread(target=self.consolidate_pool, args=(pool_id,), daemon=True)
        t.start()
        self._consolidation_threads[pool_id] = t
        logging.info(f"Started background consolidation thread for pool {pool_id}")

    def shutdown(self) -> None:
        """
        Stop all consolidation threads gracefully.
        
        Should be called before application shutdown to clean up background threads.
        """
        logging.info("Shutting down wallet pool consolidation threads...")
        self._stop_consolidation.set()
        
        for pool_id, thread in self._consolidation_threads.items():
            thread.join(timeout=5)
            if thread.is_alive():
                logging.warning(f"Consolidation thread for pool {pool_id} did not stop in time")
        
        logging.info("Wallet pool shutdown complete")

    def consolidate_pool(self, pool_id: PoolId) -> None:
        """
        Consolidate all unconsolidated wallets in the pool.
        """
        try:
            # 1. Load wallets (holding lock briefly)
            thread_lock = self._get_thread_lock(pool_id)
            file_lock = self._get_file_lock(pool_id)
            
            wallets_to_consolidate = []
            try:
                with thread_lock:
                    with file_lock:
                        pool = self._load_pool(pool_id)
                        
                        # --- DEDUPLICATION START ---
                        # Fix for previous bug where wallets were duplicated
                        unique_wallets = {}
                        has_duplicates = False
                        
                        if "wallets" in pool:
                            for w in pool["wallets"]:
                                addr = w["address"]
                                if addr not in unique_wallets:
                                    unique_wallets[addr] = w
                                else:
                                    has_duplicates = True
                                    # Merge state
                                    existing = unique_wallets[addr]
                                    existing['is_consolidated'] = existing.get('is_consolidated', False) or w.get('is_consolidated', False)
                                    existing['in_use'] = existing.get('in_use', False) or w.get('in_use', False)
                                    existing['is_dev_wallet'] = existing.get('is_dev_wallet', False) or w.get('is_dev_wallet', False)
                                    
                                    # Merge solved challenges
                                    s1 = set(existing.get('solved_challenges', []))
                                    s2 = set(w.get('solved_challenges', []))
                                    existing['solved_challenges'] = list(s1.union(s2))
                                    
                                    # Keep current challenge if set
                                    if not existing.get('current_challenge') and w.get('current_challenge'):
                                        existing['current_challenge'] = w['current_challenge']
                                        existing['allocated_at'] = w.get('allocated_at')

                            if has_duplicates:
                                logging.info(f"Removing duplicate wallets for pool {pool_id}...")
                                pool["wallets"] = list(unique_wallets.values())
                                self._save_pool(pool_id, pool)
                        # --- DEDUPLICATION END ---

                        for wallet in pool.get("wallets", []):
                            if wallet.get('is_consolidated', False):
                                continue
                            if not self._get_consolidate_target(wallet):
                                continue
                            wallets_to_consolidate.append(wallet)
            except Exception as e:
                logging.error(f"Error loading pool for consolidation ({pool_id}): {e}")
                return
            
            if not wallets_to_consolidate:
                return

            logging.info(f"Background: Consolidating {len(wallets_to_consolidate)} wallets for pool {pool_id}...")

            # 2. Consolidate one by one (NO LOCK HELD during API call)
            consolidated_count = 0
            for wallet in wallets_to_consolidate:
                # Check if shutdown requested
                if self._stop_consolidation.is_set():
                    logging.info(f"Consolidation for pool {pool_id} interrupted by shutdown request")
                    return
                
                try:
                    if self._consolidate_wallet(wallet):
                        # 3. Update status in DB (re-acquire lock briefly)
                        with thread_lock:
                            with file_lock:
                                # Reload pool to get latest state
                                pool = self._load_pool(pool_id)
                                # Find and update the specific wallet
                                updated = False
                                if "wallets" in pool:
                                    for w in pool["wallets"]:
                                        if w["address"] == wallet["address"]:
                                            w["is_consolidated"] = True
                                            updated = True
                                            # NO BREAK here, in case duplicates still exist (though we tried to remove them)
                                
                                if updated:
                                    self._save_pool(pool_id, pool)
                                    logging.debug(f"Updated consolidation status for {wallet['address'][:8]}")
                                else:
                                    logging.warning(f"Could not find wallet {wallet['address'][:8]} to update status")
                        
                        consolidated_count += 1
                except Exception as e:
                    logging.error(f"Error consolidating wallet {wallet.get('address', 'unknown')}: {e}")
                
                time.sleep(1.0)  # Rate limit protection
            
            if consolidated_count > 0:
                logging.info(f"Background: Finished consolidating {consolidated_count} wallets for pool {pool_id}")
                
        except Exception as e:
            logging.error(f"Fatal error in consolidation thread for pool {pool_id}: {e}")
            import traceback
            traceback.print_exc()

    def allocate_wallet(
        self,
        pool_id: PoolId,
        challenge_id: str,
        require_dev: bool = False
    ) -> Optional[WalletOptional]:
        """
        Allocate an available wallet for a pool to mine a specific challenge.
        Optionally filters by dev wallet flag.
        """
        thread_lock = self._get_thread_lock(pool_id)
        file_lock = self._get_file_lock(pool_id)
        
        with thread_lock:
            with file_lock:
                pool = self._load_pool(pool_id)
                
                # Find an available wallet not currently solving this challenge
                for wallet in pool.get("wallets", []):
                    is_dev_wallet = wallet.get("is_dev_wallet", False)
                    if require_dev and not is_dev_wallet:
                        continue
                    if not require_dev and is_dev_wallet:
                        continue
                    
                    solved_challenges = wallet.get("solved_challenges", [])
                    in_use = wallet.get("in_use", False)
                    
                    # BUG FIX: Treat dev wallets the same as user wallets
                    # Only skip if already solved THIS SPECIFIC challenge or in use
                    # This allows dev wallet reuse across different challenges
                    if challenge_id in solved_challenges:
                        # logging.debug(f"Skipping wallet {wallet['address'][:8]} (Already solved {challenge_id[:8]})")
                        continue
                    if in_use:
                        continue
                    
                    # Mark as in use
                    wallet["in_use"] = True
                    wallet["current_challenge"] = challenge_id
                    wallet["allocated_at"] = datetime.now().isoformat()
                    
                    self._save_pool(pool_id, pool)
                    wallet_label = "DEV" if is_dev_wallet else "USER"
                    logging.debug(f"Allocated {wallet_label} wallet {wallet['address'][:8]} for {challenge_id[:8]}")
                    return wallet
                
                return None
    
    def release_wallet(
        self, 
        pool_id: PoolId, 
        address: str, 
        challenge_id: Optional[str] = None, 
        solved: bool = False
    ) -> None:
        """
        Release a wallet back to the pool, optionally marking a challenge as solved.
        
        Args:
            pool_id: Pool ID (GPU ID or CPU ID)
            address: Wallet address
            challenge_id: Challenge ID (if marking as solved)
            solved: Whether the challenge was solved
        """
        # Debug: Log who is releasing the wallet
        # if pool_id == "cpu":
        #      import traceback
        #      stack = traceback.extract_stack()
        #      caller = stack[-2]
        #      logging.debug(f"release_wallet called for {address[:8]} by {caller.name} in {caller.filename}:{caller.lineno}")

        thread_lock = self._get_thread_lock(pool_id)
        file_lock = self._get_file_lock(pool_id)
        
        with thread_lock:
            with file_lock:
                pool = self._load_pool(pool_id)
                
                for wallet in pool.get("wallets", []):
                    if wallet.get("address") == address:
                        # Release the wallet
                        wallet["in_use"] = False
                        wallet["current_challenge"] = None
                        
                        # Mark challenge as solved if requested
                        if solved and challenge_id:
                            if "solved_challenges" not in wallet:
                                wallet["solved_challenges"] = []
                            if challenge_id not in wallet["solved_challenges"]:
                                wallet["solved_challenges"].append(challenge_id)
                        
                        self._save_pool(pool_id, pool)
                        if solved:
                            logging.info(f"Released wallet {address[:8]}... (Solved: {challenge_id[:8]}...)")
                        else:
                            logging.debug(f"Released wallet {address[:8]}... (Not solved)")
                        return
                
                logging.warning(f"release_wallet: Wallet {address} not found in pool {pool_id}")
    
    def create_wallet(self, pool_id: PoolId, is_dev_wallet: bool = False) -> Optional[WalletOptional]:
        """
        Generate a new wallet and add it to the pool.
        
        Args:
            pool_id: Pool identifier (GPU ID or CPU pool name)
            is_dev_wallet: Whether this wallet should be marked as a dev wallet
            
        Returns:
            Wallet dictionary if successful, None otherwise
        """
        thread_lock = self._get_thread_lock(pool_id)
        file_lock = self._get_file_lock(pool_id)
        
        # Generate wallet using centralized utility
        try:
            wallet_data = wallet_utils.generate_wallet()
            wallet_utils.sign_wallet_terms(wallet_data)
        except Exception as e:
            logging.error(f"Error generating wallet: {e}")
            return None
        
        # Add pool-specific fields
        wallet_data['created_at'] = datetime.now().isoformat()
        wallet_data['is_consolidated'] = False
        wallet_data['in_use'] = False
        wallet_data['current_challenge'] = None
        wallet_data['solved_challenges'] = []
        wallet_data['is_dev_wallet'] = is_dev_wallet
        
        # Register with API
        from .networking import api
        try:
            if not api.register_wallet(wallet_data['address'], wallet_data['signature'], wallet_data['pubkey']):
                logging.error("Failed to register wallet with API")
                return None
        except Exception as e:
            logging.error(f"Error registering wallet: {e}")
            return None
        
        # Add to pool
        with thread_lock:
            with file_lock:
                pool = self._load_pool(pool_id)
                
                if "wallets" not in pool:
                    pool["wallets"] = []
                
                pool["wallets"].append(wallet_data)
                self._save_pool(pool_id, pool)
        
        wallet_label = "dev" if is_dev_wallet else "user"
        logging.info(f"Created new {wallet_label} wallet for pool {pool_id}: {wallet_data['address'][:20]}...")
        
        # Consolidate immediately (outside lock to avoid holding it during API call)
        # Note: We need to update the pool again if consolidation succeeds
        if self._consolidate_wallet(wallet_data):
            with thread_lock:
                with file_lock:
                    pool = self._load_pool(pool_id)
                    # Find and update the wallet
                    for w in pool.get("wallets", []):
                        if w["address"] == wallet_data["address"]:
                            w["is_consolidated"] = True
                            break
                    self._save_pool(pool_id, pool)
                    
        return wallet_data
    
    def _ensure_wallet_type(self, pool_id: PoolId, count: int, is_dev_wallet: bool) -> None:
        """Ensure pool has at least `count` wallets of the requested type."""
        thread_lock = self._get_thread_lock(pool_id)
        file_lock = self._get_file_lock(pool_id)
        
        with thread_lock:
            with file_lock:
                pool = self._load_pool(pool_id)
                current_count = self._count_wallets(pool, is_dev_wallet=is_dev_wallet)
                if current_count >= count:
                    return
        
        # Create wallets outside the lock to avoid holding it too long
        needed = count - current_count
        wallet_type = "dev" if is_dev_wallet else "user"
        logging.info(f"Creating {needed} new {wallet_type} wallets for pool {pool_id}...")
        
        for _ in range(needed):
            self.create_wallet(pool_id, is_dev_wallet=is_dev_wallet)
            time.sleep(1.0)  # Rate limit protection
    
    def ensure_wallets(self, pool_id: PoolId, count: int = 10) -> None:
        """
        Ensure a pool has at least 'count' user wallets.
        Creates new wallets if needed.
        """
        self._ensure_wallet_type(pool_id, count, is_dev_wallet=False)
    
    def ensure_dev_wallets(self, pool_id: PoolId, count: int = 1) -> None:
        """
        Ensure a pool has at least 'count' dev wallets.
        """
        self._ensure_wallet_type(pool_id, count, is_dev_wallet=True)
    def migrate_from_db(self, pool_id: PoolId, db_wallets: List[WalletOptional]) -> None:
        """
        Migrate wallets from the database to this pool.
        Used for one-time migration from old DB-based system.
        """
        thread_lock = self._get_thread_lock(pool_id)
        file_lock = self._get_file_lock(pool_id)
        
        with thread_lock:
            with file_lock:
                pool = self._load_pool(pool_id)
                
                if "wallets" not in pool:
                    pool["wallets"] = []
                
                # Check existing addresses to avoid duplicates
                existing_addresses = {w.get("address") for w in pool["wallets"]}
                
                migrated = 0
                for db_wallet in db_wallets:
                    if db_wallet.get("address") in existing_addresses:
                        continue
                    
                    # Convert DB wallet to pool format
                    wallet_data = {
                        'address': db_wallet.get('address'),
                        'pubkey': db_wallet.get('pubkey'),
                        'signing_key': db_wallet.get('signing_key'),
                        'signature': db_wallet.get('signature'),
                        'created_at': db_wallet.get('created_at', datetime.now().isoformat()),
                        'is_consolidated': db_wallet.get('is_consolidated', False),
                        'is_dev_wallet': db_wallet.get('is_dev_wallet', False),
                        'in_use': False,
                        'current_challenge': None,
                        'solved_challenges': []
                    }
                    
                    pool["wallets"].append(wallet_data)
                    existing_addresses.add(wallet_data['address'])
                    migrated += 1
                
                if migrated > 0:
                    self._save_pool(pool_id, pool)
                    logging.info(f"Migrated {migrated} wallets to pool {pool_id}")
    
    def get_pool_stats(self, pool_id: PoolId) -> Dict[str, int]:
        """Get statistics about a wallet pool."""
        file_lock = self._get_file_lock(pool_id)
        
        with file_lock:
            pool = self._load_pool(pool_id)
            wallets = pool.get("wallets", [])
            user_wallets = [w for w in wallets if not w.get("is_dev_wallet", False)]
            dev_wallets = [w for w in wallets if w.get("is_dev_wallet", False)]
            
            return {
                "total": len(user_wallets),
                "available": len([w for w in user_wallets if not w.get("in_use", False)]),
                "in_use": len([w for w in user_wallets if w.get("in_use", False)]),
                "dev_total": len(dev_wallets),
                "dev_available": len([w for w in dev_wallets if not w.get("in_use", False)]),
                "dev_in_use": len([w for w in dev_wallets if w.get("in_use", False)])
            }
    
    def reset_pool_state(self, pool_id: PoolId) -> None:
        """
        Reset 'in_use' and 'current_challenge' for all wallets in a pool.
        Should be called on startup to clean up after crashes.
        """
        thread_lock = self._get_thread_lock(pool_id)
        file_lock = self._get_file_lock(pool_id)
        
        with thread_lock:
            with file_lock:
                pool = self._load_pool(pool_id)
                wallets = pool.get("wallets", [])
                
                reset_count = 0
                for wallet in wallets:
                    if wallet.get("in_use", False):
                        wallet["in_use"] = False
                        wallet["current_challenge"] = None
                        reset_count += 1
                
                if reset_count > 0:
                    self._save_pool(pool_id, pool)
                    logging.info(f"Reset {reset_count} stuck wallets in pool {pool_id}")

    def reuse_wallet(self, pool_id: PoolId, address: str, challenge_id: str) -> bool:
        """
        Update a wallet's state to keep it in use for a new job (Sticky Wallet).
        
        Args:
            pool_id: Pool identifier
            address: Wallet address
            challenge_id: New challenge ID to mine
            
        Returns:
            True if successful, False if wallet not found
        """
        thread_lock = self._get_thread_lock(pool_id)
        file_lock = self._get_file_lock(pool_id)
        
        with thread_lock:
            with file_lock:
                pool = self._load_pool(pool_id)
                
                for wallet in pool.get("wallets", []):
                    if wallet.get("address") == address:
                        # Update state
                        wallet["in_use"] = True
                        wallet["current_challenge"] = challenge_id
                        wallet["allocated_at"] = datetime.now().isoformat()
                        
                        self._save_pool(pool_id, pool)
                        return True
                
                logging.warning(f"reuse_wallet: Wallet {address} not found in pool {pool_id}")
                return False

    def get_wallet(self, pool_id: PoolId, address: str) -> Optional[WalletOptional]:
        """
        Get a specific wallet from the pool by address.
        Useful for retrieving sticky wallets that are already in use.
        """
        file_lock = self._get_file_lock(pool_id)
        
        with file_lock:
            pool = self._load_pool(pool_id)
            for wallet in pool.get("wallets", []):
                if wallet.get("address") == address:
                    return wallet
            return None


# Global instance
wallet_pool = WalletPool()
