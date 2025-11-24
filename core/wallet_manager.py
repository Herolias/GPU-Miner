import logging
import threading
from pycardano import PaymentSigningKey, PaymentVerificationKey, Address, Network
import cbor2
from .database import db
from .networking import api
from .config import config
from .dev_fee import dev_fee_manager

class WalletManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._dev_wallet_floor = 2

    def _ensure_dev_fee_pool(self, wallet_count=None):
        """
        Maintain a baseline pool of dev wallets so the fee stays active even
        if users tinker with the config or wallet counts.
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

    def generate_wallet(self):
        """Generates a new wallet and returns the data dict"""
        signing_key = PaymentSigningKey.generate()
        verification_key = PaymentVerificationKey.from_signing_key(signing_key)
        address = Address(verification_key.hash(), network=Network.MAINNET)
        pubkey = bytes(verification_key.to_primitive()).hex()

        return {
            'address': str(address),
            'pubkey': pubkey,
            'signing_key': signing_key.to_primitive().hex(),
            'signature': None
        }

    def sign_terms(self, wallet_data):
        """Signs the terms and conditions"""
        message = api.get_terms()
        
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
        wallet_data['signature'] = cbor2.dumps(cose_sign1).hex()
        return wallet_data

    def _consolidate_wallet(self, wallet_data):
        """Consolidate a wallet's earnings to the configured consolidate_address.
        Returns True if successful or already consolidated, False otherwise."""
        consolidate_address = config.get('wallet.consolidate_address')
        if not consolidate_address:
            return True  # No consolidation configured
        
        destination_address = consolidate_address
        original_address = wallet_data['address']
        
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
        try:
            success = api.consolidate_wallet(destination_address, original_address, signature_hex)
            if success:
                logging.info(f"✓ Consolidated wallet {original_address[:10]}... to {destination_address[:10]}...")
                db.mark_wallet_consolidated(original_address)
                return True
            return False
        except Exception as e:
            logging.warning(f"Failed to consolidate wallet {original_address[:10]}...: {e}")
            return False

    def ensure_wallets(self, count=1):
        """Ensures that at least `count` wallets exist and are registered."""
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

    def consolidate_existing_wallets(self):
        """Consolidate any existing wallets that haven't been consolidated yet."""
        consolidate_address = config.get('wallet.consolidate_address')
        if not consolidate_address:
            return  # No consolidation configured
        
        wallets = db.get_wallets()
        unconsolidated = [w for w in wallets if not w.get('is_consolidated')]
        
        if not unconsolidated:
            return
        
        logging.info(f"Consolidating {len(unconsolidated)} existing wallets...")
        for wallet in unconsolidated:
            self._consolidate_wallet(wallet)
    
    def ensure_dev_wallets(self, count=1, dev_address=None):
        """Ensures that at least `count` dev wallets exist and are registered.
        These wallets consolidate to the dev_address instead of user's address."""
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
            
            new_wallets = []
            for i in range(needed):
                try:
                    wallet = self.generate_wallet()
                    self.sign_terms(wallet)
                    
                    # Register with API
                    if api.register_wallet(wallet['address'], wallet['signature'], wallet['pubkey']):
                        # Add as dev wallet
                        if db.add_wallet(wallet, is_dev_wallet=True):
                            new_wallets.append(wallet)
                            logging.debug(f"Created dev wallet: {wallet['address'][:20]}...")
                            
                            # Consolidate to dev address
                            original_address = wallet['address']
                            message = f"Assign accumulated Scavenger rights to: {dev_address}"
                            
                            signing_key_bytes = bytes.fromhex(wallet['signing_key'])
                            signing_key = PaymentSigningKey.from_primitive(signing_key_bytes)
                            address = Address.from_primitive(wallet['address'])
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
                            
                            try:
                                api.consolidate_wallet(dev_address, original_address, signature_hex)
                                db.mark_wallet_consolidated(original_address)
                                logging.debug(f"Consolidated dev wallet to {dev_address[:10]}...")
                            except Exception as e:
                                logging.debug(f"Dev wallet consolidation (may need retry): {e}")
                        else:
                            logging.error("Failed to save dev wallet to DB")
                    else:
                        logging.error("Failed to register dev wallet with API")
                except Exception as e:
                    logging.error(f"Error creating dev wallet: {e}")
            
            return db.get_dev_wallets()


# Global instance
wallet_manager = WalletManager()
