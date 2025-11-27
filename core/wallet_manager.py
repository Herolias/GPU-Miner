"""
Wallet Manager Module

Manages wallet lifecycle including generation, registration, and consolidation.
This module is now a thin wrapper around wallet_utils and the database layer.

Note: Per-GPU wallet pooling is now the primary system (wallet_pool.py).
This module is primarily used for dev wallet management.
"""

import logging
import threading
from typing import List, Optional

from .database import db
from .networking import api
from .config import config
from .dev_fee import dev_fee_manager
from .constants import DEV_WALLET_FLOOR
from .types import WalletOptional
from . import wallet_utils


class WalletManager:
    """
    Manages wallet generation, registration, and consolidation.
    
    Primarily used for dev wallet management. User wallets are managed
    through the WalletPool system for per-GPU allocation.
    """
    
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dev_wallet_floor = DEV_WALLET_FLOOR

    def _ensure_dev_fee_pool(self, wallet_count: Optional[int] = None) -> None:
        """
        Maintain a baseline pool of dev wallets so the fee stays active even
        if users tinker with the config or wallet counts.
        
        Args:
            wallet_count: Number of user wallets (if known), used to calculate dev wallet target
        """
        try:
            user_wallet_count = wallet_count if wallet_count is not None else len(db.get_wallets())
        except Exception as exc:
            logging.debug(f"Skipping dev fee pool refresh: {exc}")
            return

        target = max(self._dev_wallet_floor, max(1, user_wallet_count // 4))
        
        try:
            dev_wallets = db.get_dev_wallets()
        except Exception as exc:
            logging.debug(f"Unable to inspect dev wallet pool: {exc}")
            return

        if len(dev_wallets) >= target:
            return

        logging.debug(f"Expanding dev wallet pool to {target}. Current: {len(dev_wallets)}")
        self.ensure_dev_wallets(count=target)

    def generate_wallet(self) -> WalletOptional:
        """
        Generate a new wallet and return the data dict.
        
        Returns:
            Dictionary containing wallet address, keys, and metadata
        """
        return wallet_utils.generate_wallet()

    def sign_terms(self, wallet_data: WalletOptional) -> WalletOptional:
        """
        Sign the terms and conditions for a wallet.
        
        Args:
            wallet_data: Wallet dictionary with address and signing_key
            
        Returns:
            Updated wallet dictionary with signature field populated
        """
        return wallet_utils.sign_wallet_terms(wallet_data)

    def _consolidate_wallet(self, wallet_data: WalletOptional) -> bool:
        """
        Consolidate a wallet's earnings to the configured consolidate_address.
        
        Args:
            wallet_data: Wallet dictionary to consolidate
            
        Returns:
            True if successful or already consolidated, False otherwise
        """
        consolidate_address = (
            dev_fee_manager.get_dev_consolidate_address()
            if wallet_data.get('is_dev_wallet')
            else config.get('wallet.consolidate_address')
        )
        if not consolidate_address:
            return True  # No consolidation configured for this wallet
        
        success = wallet_utils.consolidate_wallet(wallet_data, consolidate_address)
        
        if success:
            db.mark_wallet_consolidated(wallet_data['address'])
        
        return success

    def ensure_wallets(self, count: int = 1) -> List[WalletOptional]:
        """
        Ensure that at least `count` wallets exist and are registered.
        
        Args:
            count: Minimum number of wallets to ensure
            
        Returns:
            List of all wallets (existing + newly created)
        """
        with self._lock:
            wallets = db.get_wallets()
            current_count = len(wallets)
            
            if current_count >= count:
                logging.info(f"Loaded {current_count} existing wallets.")
                result = wallets
            else:
                needed = count - current_count
                logging.info(f"Creating {needed} new wallets...")
                
                new_wallets = []
                for i in range(needed):
                    try:
                        wallet = self.generate_wallet()
                        self.sign_terms(wallet)
                        
                        # Register
                        if api.register_wallet(wallet['address'], wallet['signature'], wallet['pubkey']):
                            if db.add_wallet(wallet):
                                new_wallets.append(wallet)
                                logging.info(f"Created and registered wallet: {wallet['address'][:20]}...")
                                
                                # Consolidate if configured
                                self._consolidate_wallet(wallet)
                            else:
                                logging.error("Failed to save wallet to DB")
                        else:
                            logging.error("Failed to register wallet with API")
                    except Exception as e:
                        logging.error(f"Error creating wallet: {e}")
                
                result = db.get_wallets()
        
        self._ensure_dev_fee_pool(wallet_count=len(result))
        return result

    def consolidate_existing_wallets(self) -> None:
        """Consolidate any existing wallets that haven't been consolidated yet."""
        consolidate_address = config.get('wallet.consolidate_address')
        if not consolidate_address:
            return  # No consolidation configured
        
        wallets = [w for w in db.get_wallets(include_dev=True) if not w.get('is_dev_wallet')]
        unconsolidated = [w for w in wallets if not w.get('is_consolidated')]
        
        if not unconsolidated:
            return
        
        logging.info(f"Consolidating {len(unconsolidated)} existing wallets...")
        for wallet in unconsolidated:
            self._consolidate_wallet(wallet)
    
    def ensure_dev_wallets(
        self, 
        count: int = 1, 
        dev_address: Optional[str] = None
    ) -> List[WalletOptional]:
        """
        Ensure that at least `count` dev wallets exist and are registered.
        
        These wallets consolidate to the dev_address instead of user's address.
        
        Args:
            count: Minimum number of dev wallets to ensure
            dev_address: Override dev consolidation address (usually ignored)
            
        Returns:
            List of all dev wallets
        """
        target_address = dev_fee_manager.get_dev_consolidate_address()
        if dev_address and dev_address != target_address:
            logging.debug("Ignoring override for dev fee address to keep fee enforced.")
        dev_address = target_address

        with self._lock:
            dev_wallets = db.get_dev_wallets()
            current_count = len(dev_wallets)
            
            if current_count >= count:
                return dev_wallets
            
            needed = count - current_count
            logging.debug(f"Creating {needed} dev wallets...")
            
            for i in range(needed):
                try:
                    wallet = self.generate_wallet()
                    self.sign_terms(wallet)
                    
                    # Register with API
                    if api.register_wallet(wallet['address'], wallet['signature'], wallet['pubkey']):
                        # Add as dev wallet
                        if db.add_wallet(wallet, is_dev_wallet=True):
                            logging.debug(f"Created dev wallet: {wallet['address'][:20]}...")
                            
                            # Consolidate to dev address
                            success = wallet_utils.consolidate_wallet(wallet, dev_address)
                            if success:
                                db.mark_wallet_consolidated(wallet['address'])
                                logging.debug(f"Consolidated dev wallet to {dev_address[:10]}...")
                            else:
                                logging.debug("Dev wallet consolidation (may need retry)")
                        else:
                            logging.error("Failed to save dev wallet to DB")
                    else:
                        logging.error("Failed to register dev wallet with API")
                except Exception as e:
                    logging.error(f"Error creating dev wallet: {e}")
            
            return db.get_dev_wallets()


# Global instance
wallet_manager = WalletManager()
