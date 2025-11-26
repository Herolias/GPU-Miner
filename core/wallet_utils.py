"""
Shared wallet utility functions.

This module provides common wallet operations to eliminate code duplication
between wallet_manager.py and wallet_pool.py.
"""

import logging
from typing import Dict
from pycardano import PaymentSigningKey, PaymentVerificationKey, Address, Network
import cbor2

from .types import WalletOptional
from .networking import api


def generate_wallet() -> WalletOptional:
    """
    Generate a new Cardano wallet with signing and verification keys.
    
    Returns:
        Dictionary containing wallet address, keys, and metadata
        
    Example:
        >>> wallet = generate_wallet()
        >>> print(wallet['address'][:10])
        addr1...
    """
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


def sign_wallet_terms(wallet_data: WalletOptional) -> WalletOptional:
    """
    Sign the terms and conditions for wallet registration.
    
    Args:
        wallet_data: Wallet dictionary with address and signing_key
        
    Returns:
        Updated wallet dictionary with signature field populated
        
    Raises:
        Exception: If terms retrieval or signing fails
        
    Example:
        >>> wallet = generate_wallet()
        >>> wallet = sign_wallet_terms(wallet)
        >>> assert wallet['signature'] is not None
    """
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


def create_cose_signature(wallet_data: WalletOptional, message: str) -> str:
    """
    Create a COSE signature for wallet consolidation or other operations.
    
    This is the standard signing pattern used for wallet consolidation requests
    to assign accumulated Scavenger rights to a destination address.
    
    Args:
        wallet_data: Wallet dictionary with address and signing_key
        message: Message to sign (e.g., consolidation assignment message)
        
    Returns:
        Hex-encoded COSE signature
        
    Raises:
        Exception: If signing fails
        
    Example:
        >>> wallet = generate_wallet()
        >>> msg = f"Assign accumulated Scavenger rights to: {dest_addr}"
        >>> signature = create_cose_signature(wallet, msg)
        >>> assert len(signature) > 0
    """
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
    
    return signature_hex


def consolidate_wallet(
    wallet_data: WalletOptional,
    destination_address: str
) -> bool:
    """
    Consolidate a wallet's earnings to the specified destination address.
    
    Args:
        wallet_data: Wallet dictionary to consolidate
        destination_address: Address to send accumulated rights to
        
    Returns:
        True if consolidation successful or already consolidated, False otherwise
        
    Example:
        >>> wallet = generate_wallet()
        >>> success = consolidate_wallet(wallet, "addr1...")
    """
    # Skip if already consolidated
    if wallet_data.get('is_consolidated', False):
        return True
    
    original_address = wallet_data['address']
    
    try:
        # Create signature for donation message
        message = f"Assign accumulated Scavenger rights to: {destination_address}"
        signature_hex = create_cose_signature(wallet_data, message)
        
        # Make API call to consolidate
        success = api.consolidate_wallet(destination_address, original_address, signature_hex)
        
        if success:
            logging.info(
                f"✓ Consolidated wallet {original_address[:10]}... "
                f"to {destination_address[:10]}..."
            )
            wallet_data['is_consolidated'] = True
            return True
        
        return False
        
    except Exception as e:
        logging.warning(
            f"Failed to consolidate wallet {original_address[:10]}...: {e}"
        )
        return False
