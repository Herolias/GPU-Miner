"""
Per-GPU Wallet Pool Management System

This module provides JSON-based wallet management with per-GPU pools
to prevent wallet contention in multi-GPU mining setups.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from filelock import FileLock
from typing import Dict, Optional, List, Union

from pycardano import PaymentSigningKey, PaymentVerificationKey, Address, Network
import cbor2

from .config import config
from .networking import api


class WalletPool:
    """Manages per-GPU wallet pools using JSON files with file locking."""
    
    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._locks = {}  # gpu_id -> threading.Lock
        self._file_locks = {}  # gpu_id -> FileLock for file access
        
    def _get_pool_path(self, pool_id: Union[int, str]) -> Path:
        """Get the JSON file path for a specific pool (GPU or CPU)."""
        if isinstance(pool_id, int):
            return self.base_dir / f"wallets_gpu_{pool_id}.json"
        return self.base_dir / f"wallets_{pool_id}.json"
    
    def _get_lock_path(self, pool_id: Union[int, str]) -> Path:
        """Get the lock file path for a specific pool."""
        if isinstance(pool_id, int):
            return self.base_dir / f"wallets_gpu_{pool_id}.json.lock"
        return self.base_dir / f"wallets_{pool_id}.json.lock"
    
    def _get_thread_lock(self, pool_id: Union[int, str]) -> threading.Lock:
        """Get or create a thread lock for a pool."""
        if pool_id not in self._locks:
            self._locks[pool_id] = threading.Lock()
        return self._locks[pool_id]
    
    def _get_file_lock(self, pool_id: Union[int, str]) -> FileLock:
        """Get or create a file lock for a pool."""
        if pool_id not in self._file_locks:
            lock_path = self._get_lock_path(pool_id)
            self._file_locks[pool_id] = FileLock(str(lock_path), timeout=10)
        return self._file_locks[pool_id]
    
    def _load_pool(self, pool_id: Union[int, str]) -> Dict:
        """Load wallet pool from JSON file."""
        pool_path = self._get_pool_path(pool_id)
        
        if not pool_path.exists():
            return {"pool_id": pool_id, "wallets": []}
        
        try:
            with open(pool_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading wallet pool for GPU {gpu_id}: {e}")
            return {"gpu_id": gpu_id, "wallets": []}
    
    def _save_pool(self, pool_id: Union[int, str], pool_data: Dict):
        """Save wallet pool to JSON file."""
        pool_path = self._get_pool_path(pool_id)
        
        try:
            with open(pool_path, 'w') as f:
                json.dump(pool_data, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving wallet pool {pool_id}: {e}")
        except Exception as e:
            logging.error(f"Error saving wallet pool for GPU {gpu_id}: {e}")
            
    def _consolidate_wallet(self, wallet_data: Dict) -> bool:
        """
        Consolidate a wallet's earnings to the configured consolidate_address.
        Returns True if successful or already consolidated, False otherwise.
        """
        consolidate_address = config.get('wallet.consolidate_address')
        if not consolidate_address:
            return False  # No consolidation configured, so it's NOT consolidated
        
        # Skip if already consolidated
        if wallet_data.get('is_consolidated', False):
            return True
            
        destination_address = consolidate_address
        original_address = wallet_data['address']
        
        try:
            # Create signature for donation message
            message = f"Assign accumulated Scavenger rights to: {destination_address}"
            
            signing_key_bytes = bytes.fromhex(wallet_data['signing_key'])
            signing_key = PaymentSigningKey.from_primitive(signing_key_bytes)
            address = Address.from_primitive(wallet_data['address'])
            address_bytes = bytes(address.to_primitive())
            
            protected = {1: -8, "address": address_bytes}
            protected_encoded = cbor2.dumps(protected)
            unprotected = {"hashed": False}
            payload = message.encode('utf-8')
            
            sig_structure = ["Signature1", protected_encoded, b'', payload]
            to_sign = cbor2.dumps(sig_structure)
            signature_bytes = signing_key.sign(to_sign)
            
            cose_sign1 = [protected_encoded, unprotected, payload, signature_bytes]
            signature_hex = cbor2.dumps(cose_sign1).hex()
            
            # Make API call to consolidate
            success = api.consolidate_wallet(destination_address, original_address, signature_hex)
            if success:
                logging.info(f"✓ Consolidated wallet {original_address[:10]}... to {destination_address[:10]}...")
                wallet_data['is_consolidated'] = True
                return True
            return False
        except Exception as e:
            logging.warning(f"Failed to consolidate wallet {original_address[:10]}...: {e}")
            return False

    def start_consolidation_thread(self, pool_id: Union[int, str]):
        """
        Start a background thread to consolidate wallets for this pool.
        """
        t = threading.Thread(target=self.consolidate_pool, args=(pool_id,), daemon=True)
        t.start()
        logging.info(f"Started background consolidation thread for pool {pool_id}")

    def consolidate_pool(self, pool_id: Union[int, str]):
        """
        Consolidate all unconsolidated wallets in the pool.
        """
        try:
            consolidate_address = config.get('wallet.consolidate_address')
            if not consolidate_address:
                return

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
                            if not wallet.get('is_consolidated', False):
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

    def allocate_wallet(self, pool_id: Union[int, str], challenge_id: str) -> Optional[Dict]:
        """
        Allocate an available wallet for a pool to mine a specific challenge.
        Returns wallet dict or None if no wallets available.
        """
        thread_lock = self._get_thread_lock(pool_id)
        file_lock = self._get_file_lock(pool_id)
        
        with thread_lock:
            with file_lock:
                pool = self._load_pool(pool_id)
                
                # Find an available wallet not currently solving this challenge
                for wallet in pool.get("wallets", []):
                    solved_challenges = wallet.get("solved_challenges", [])
                    in_use = wallet.get("in_use", False)
                    
                    # Skip if already solved this challenge or in use
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
                    logging.debug(f"Allocated wallet {wallet['address'][:8]} for {challenge_id[:8]}")
                    return wallet
                
                return None
    
    def release_wallet(self, pool_id: Union[int, str], address: str, challenge_id: str = None, solved: bool = False):
        """
        Release a wallet back to the pool, optionally marking a challenge as solved.
        
        Args:
            pool_id: Pool ID (GPU ID or CPU ID)
            address: Wallet address
            challenge_id: Challenge ID (if marking as solved)
            solved: Whether the challenge was solved
        """
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
    
    def create_wallet(self, pool_id: Union[int, str]) -> Dict:
        """
        Generate a new wallet and add it to the pool.
        Returns the wallet dict.
        """
        thread_lock = self._get_thread_lock(pool_id)
        file_lock = self._get_file_lock(pool_id)
        
        # Generate wallet
        signing_key = PaymentSigningKey.generate()
        verification_key = PaymentVerificationKey.from_signing_key(signing_key)
        address = Address(verification_key.hash(), network=Network.MAINNET)
        pubkey = bytes(verification_key.to_primitive()).hex()
        
        wallet_data = {
            'address': str(address),
            'pubkey': pubkey,
            'signing_key': signing_key.to_primitive().hex(),
            'signature': None,
            'created_at': datetime.now().isoformat(),
            'is_consolidated': False,
            'in_use': False,
            'current_challenge': None,
            'solved_challenges': []
        }
        
        # Sign terms
        try:
            message = api.get_terms()
            signing_key_bytes = bytes.fromhex(wallet_data['signing_key'])
            signing_key = PaymentSigningKey.from_primitive(signing_key_bytes)
            address_obj = Address.from_primitive(wallet_data['address'])
            address_bytes = bytes(address_obj.to_primitive())

            protected = {1: -8, "address": address_bytes}
            protected_encoded = cbor2.dumps(protected)
            unprotected = {"hashed": False}
            payload = message.encode('utf-8')

            sig_structure = ["Signature1", protected_encoded, b'', payload]
            to_sign = cbor2.dumps(sig_structure)
            signature_bytes = signing_key.sign(to_sign)

            cose_sign1 = [protected_encoded, unprotected, payload, signature_bytes]
            wallet_data['signature'] = cbor2.dumps(cose_sign1).hex()
        except Exception as e:
            logging.error(f"Error signing terms for new wallet: {e}")
            return None
        
        # Register with API
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
        
        logging.info(f"Created new wallet for pool {pool_id}: {wallet_data['address'][:20]}...")
        
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
    
    def ensure_wallets(self, pool_id: Union[int, str], count: int = 10):
        """
        Ensure a pool has at least 'count' wallets.
        Creates new wallets if needed.
        """
        thread_lock = self._get_thread_lock(pool_id)
        file_lock = self._get_file_lock(pool_id)
        
        with thread_lock:
            with file_lock:
                pool = self._load_pool(pool_id)
                current_count = len(pool.get("wallets", []))
                
                if current_count >= count:
                    logging.info(f"Pool {pool_id} already has {current_count} wallets")
                    return
        
        # Create wallets outside the lock to avoid holding it too long
        needed = count - current_count
        logging.info(f"Creating {needed} new wallets for pool {pool_id}...")
        
        for i in range(needed):
            self.create_wallet(pool_id)
            time.sleep(1.0)  # Rate limit protection
    
    def migrate_from_db(self, pool_id: Union[int, str], db_wallets: List[Dict]):
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
    
    def get_pool_stats(self, pool_id: Union[int, str]) -> Dict:
        """Get statistics about a wallet pool."""
        file_lock = self._get_file_lock(pool_id)
        
        with file_lock:
            pool = self._load_pool(pool_id)
            wallets = pool.get("wallets", [])
            
            return {
                "total": len(wallets),
                "available": len([w for w in wallets if not w.get("in_use", False)]),
                "in_use": len([w for w in wallets if w.get("in_use", False)])
            }


# Global instance
wallet_pool = WalletPool()
