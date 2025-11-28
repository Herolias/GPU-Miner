"""
Mining Utilities Module

Common utility functions used across mining modules to reduce code duplication.
"""

import random
from typing import Tuple

from .types import Challenge, WalletOptional


def build_salt_prefix(wallet: WalletOptional, challenge: Challenge) -> bytes:
    """
    Build salt prefix from wallet and challenge data.
    
    The salt prefix is used as input to the mining hash function and combines
    all challenge parameters to ensure uniqueness.
    
    Args:
        wallet: Wallet dictionary with address field
        challenge: Challenge dictionary with required fields
        
    Returns:
        UTF-8 encoded salt prefix bytes
        
    Example:
        >>> wallet = {'address': 'addr1...'}
        >>> challenge = {'challenge_id': 'abc123', 'difficulty': '0000ff00', ...}
        >>> salt = build_salt_prefix(wallet, challenge)
        >>> len(salt) > 0
        True
    """
    salt_prefix_str = (
        wallet['address'] +
        challenge['challenge_id'] +
        challenge['difficulty'] +
        challenge['no_pre_mine'] +
        challenge.get('latest_submission', '') +
        challenge.get('no_pre_mine_hour', '')
    )
    
    return salt_prefix_str.encode('utf-8')


def parse_difficulty(difficulty_str: str, full: bool = False) -> int:
    """
    Parse difficulty from hex string.
    
    Args:
        difficulty_str: Hex string representing difficulty (e.g., "0000ff00...")
        full: If True, parse full 256-bit difficulty; if False, parse first 8 hex chars (32 bits)
        
    Returns:
        Integer difficulty value
        
    Example:
        >>> parse_difficulty("0000ff00", full=False)
        65280
        >>> parse_difficulty("0000ff00" + "00" * 28, full=True)
        65280
    """
    # Handle optional '0x' prefix
    clean_diff = difficulty_str.lower().replace('0x', '')
    
    if full:
        # Parse full 256-bit difficulty (64 hex chars)
        # Pad with zeros to the right if shorter than 64 chars to represent the full target
        padded_diff = clean_diff.ljust(64, '0')
        return int(padded_diff, 16)
    else:
        # Parse first 32 bits (8 hex chars) for GPU/CPU
        return int(clean_diff[:8], 16)


def generate_random_nonce() -> int:
    """
    Generate a random 64-bit starting nonce for mining.
    
    Returns:
        Random integer in range [0, 2^64)
        
    Example:
        >>> nonce = generate_random_nonce()
        >>> 0 <= nonce < 2**64
        True
    """
    return random.getrandbits(64)


def format_nonce_hex(nonce: int) -> str:
    """
    Format nonce as 16-character hex string.
    
    Args:
        nonce: Integer nonce value
        
    Returns:
        Zero-padded 16-character hex string
        
    Example:
        >>> format_nonce_hex(255)
        '00000000000000ff'
    """
    return f"{nonce:016x}"


def truncate_address(address: str, length: int = 10) -> str:
    """
    Truncate address for display purposes.
    
    Args:
        address: Full wallet address
        length: Number of characters to show (default: 10)
        
    Returns:
        Truncated address with ellipsis
        
    Example:
        >>> truncate_address("addr1qxample1234567890", 8)
        'addr1qxa...'
    """
    if len(address) <= length:
        return address
    return address[:length] + "..."


def truncate_challenge_id(challenge_id: str, length: int = 8) -> str:
    """
    Truncate challenge ID for display purposes.
    
    Args:
        challenge_id: Full challenge ID
        length: Number of characters to show (default: 8)
        
    Returns:
        Truncated challenge ID with ellipsis
        
    Example:
        >>> truncate_challenge_id("abc123def456ghi789", 8)
        'abc123de...'
    """
    if len(challenge_id) <= length:
        return challenge_id
    return challenge_id[:length] + "..."


def calculate_hashrate(hashes: int, duration: float) -> float:
    """
    Calculate hashrate from number of hashes and duration.
    
    Args:
        hashes: Number of hashes computed
        duration: Time taken in seconds
        
    Returns:
        Hashrate in hashes per second (0 if duration is 0)
        
    Example:
        >>> calculate_hashrate(1000000, 10.0)
        100000.0
    """
    if duration <= 0:
        return 0.0
    return hashes / duration


def smooth_hashrate(old_hashrate: float, new_hashrate: float, weight_old: float = 0.9) -> float:
    """
    Apply exponential moving average to smooth hashrate fluctuations.
    
    Args:
        old_hashrate: Previous hashrate value
        new_hashrate: New instantaneous hashrate
        weight_old: Weight for old value (0.9 = 90% old, 10% new)
        
    Returns:
        Smoothed hashrate value
        
    Example:
        >>> smooth_hashrate(1000.0, 1200.0, 0.9)
        1020.0
    """
    if old_hashrate == 0:
        return new_hashrate
    
    weight_new = 1.0 - weight_old
    return (weight_old * old_hashrate) + (weight_new * new_hashrate)
