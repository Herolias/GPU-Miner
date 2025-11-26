"""
Retry Manager Module

Manages retry queue for failed solution submissions, handling both immediate
retries and persistent retries from database.
"""

import time
import logging
from typing import List, Tuple, Optional

from .database import db
from .networking import api
from .constants import MAX_IMMEDIATE_RETRIES, RETRY_CHECK_FREQUENCY
from .types import RetryQueueItem


class RetryManager:
    """
    Manages solution submission retries with two-tier system:
    - Immediate retries: In-memory queue for transient failures
    - Persistent retries: Database-backed for long-term retry attempts
    """
    
    def __init__(self) -> None:
        """Initialize retry manager with empty immediate queue."""
        self.immediate_queue: List[Tuple[str, str, str, str, bool, int]] = []
        self.last_persistent_check = 0
    
    def add_to_queue(
        self,
        wallet_address: str,
        challenge_id: str,
        nonce: str,
        difficulty: str,
        is_dev_solution: bool,
        retry_count: int = 0
    ) -> None:
        """
        Add a failed solution to the immediate retry queue.
        
        Args:
            wallet_address: Wallet that found the solution
            challenge_id: Challenge ID
            nonce: Solution nonce (hex string)
            difficulty: Difficulty hex string
            is_dev_solution: Whether this is a dev fee solution
            retry_count: Current retry attempt count
        """
        self.immediate_queue.append((
            wallet_address,
            challenge_id,
            nonce,
            difficulty,
            is_dev_solution,
            retry_count
        ))
        logging.debug(
            f"Added to retry queue: {challenge_id[:8]}... "
            f"(attempt {retry_count + 1}/{MAX_IMMEDIATE_RETRIES})"
        )
    
    def process_immediate_retries(
        self,
        on_success: callable,
        on_fatal: callable,
        on_transient: callable
    ) -> int:
        """
        Process immediate retry queue.
        
        Args:
            on_success: Callback(wallet_addr, challenge_id, nonce, is_dev) called on success
            on_fatal: Callback(wallet_addr, challenge_id, nonce) called on fatal error
            on_transient: Callback(wallet_addr, challenge_id, nonce, difficulty, is_dev, count) 
                         called on transient error
        
        Returns:
            Number of solutions successfully resubmitted
        """
        if not self.immediate_queue:
            return 0
        
        # Process one retry per call to avoid blocking
        retry_item = self.immediate_queue.pop(0)
        wallet_addr, challenge_id, nonce, difficulty, is_dev, retry_count = retry_item
        
        logging.info(
            f"Retrying submission for {wallet_addr[:8]}... "
            f"(Attempt {retry_count + 1}/{MAX_IMMEDIATE_RETRIES})"
        )
        
        success, is_fatal = api.submit_solution(wallet_addr, challenge_id, nonce)
        
        if success:
            logging.info("✓ Retry successful!")
            db.update_solution_status(challenge_id, nonce, 'accepted')
            db.update_retry_status(challenge_id, nonce, True)
            on_success(wallet_addr, challenge_id, nonce, is_dev)
            return 1
            
        elif is_fatal:
            logging.error("✗ Retry failed fatally. Dropping.")
            db.update_solution_status(challenge_id, nonce, 'rejected')
            db.update_retry_status(challenge_id, nonce, True)
            on_fatal(wallet_addr, challenge_id, nonce)
            return 0
            
        else:
            # Transient error - re-queue if not at max retries
            if retry_count < MAX_IMMEDIATE_RETRIES - 1:
                new_count = retry_count + 1
                self.immediate_queue.append((
                    wallet_addr, challenge_id, nonce, difficulty, is_dev, new_count
                ))
                logging.warning(f"Retry failed (transient). Re-queueing ({new_count + 1}/{MAX_IMMEDIATE_RETRIES})")
                on_transient(wallet_addr, challenge_id, nonce, difficulty, is_dev, new_count)
            else:
                logging.error(f"Max immediate retries reached. Moving to persistent storage.")
                db.update_solution_status(challenge_id, nonce, 'failed_max_retries')
                db.update_retry_status(challenge_id, nonce, False)
            
            return 0
    
    def load_persistent_retries(self, req_id: int) -> int:
        """
        Load pending retries from database if it's time to check.
        
        Args:
            req_id: Current request ID (used to determine check frequency)
            
        Returns:
            Number of retries loaded from database
        """
        # Only check periodically to avoid database overhead
        if req_id % RETRY_CHECK_FREQUENCY != 0:
            return 0
        
        pending_retries = db.get_pending_retries()
        loaded_count = 0
        
        for retry_item in pending_retries:
            # Check if already in queue
            in_queue = any(
                item[1] == retry_item['challenge_id'] and item[2] == retry_item['nonce']
                for item in self.immediate_queue
            )
            
            if not in_queue:
                self.immediate_queue.append((
                    retry_item['wallet_address'],
                    retry_item['challenge_id'],
                    retry_item['nonce'],
                    retry_item['difficulty'],
                    retry_item['is_dev_solution'],
                    retry_item.get('retry_count', 0)
                ))
                loaded_count += 1
                logging.info(
                    f"Loaded pending retry from DB: "
                    f"{retry_item['challenge_id'][:8]}..."
                )
        
        if loaded_count > 0:
            logging.info(f"Loaded {loaded_count} pending retries from database")
        
        return loaded_count
    
    def get_queue_size(self) -> int:
        """Get current size of immediate retry queue."""
        return len(self.immediate_queue)
    
    def clear_queue(self) -> None:
        """Clear the immediate retry queue (use with caution)."""
        cleared = len(self.immediate_queue)
        self.immediate_queue.clear()
        if cleared > 0:
            logging.warning(f"Cleared {cleared} items from retry queue")
