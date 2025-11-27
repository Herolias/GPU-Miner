"""
Response Processor Module

Handles processing of mining responses from GPU and CPU workers, including
solution submission, wallet management, and hashrate calculations.
"""

import logging
from typing import Dict, Optional

from .database import db
from .networking import api
from .wallet_pool import wallet_pool
from .constants import HASHRATE_EMA_WEIGHT_OLD, HASHRATE_EMA_WEIGHT_NEW
from .types import MineResponse, Challenge, WorkerType, PoolId
from . import mining_utils


class ResponseProcessor:
    """
    Processes mining responses from workers and manages solution submission.
    
    Handles:
    - Solution validation and submission
    - Wallet pool management (allocation/release)
    - Hashrate calculation and smoothing
    - Statistics tracking
    """
    
    def __init__(self) -> None:
        """Initialize response processor with default stats."""
        self.gpu_hashrate = 0.0
        self.cpu_hashrate = 0.0
        self.session_solutions = 0
        self.dev_session_solutions = 0
        self.wallet_session_solutions: Dict[str, int] = {}
    
    def process_response(
        self,
        response: MineResponse,
        worker_type: WorkerType,
        worker_id: int,
        wallet_address: str,
        challenge_id: str,
        is_dev_solution: bool,
        current_challenge: Challenge,
        num_workers: int,
        keep_wallet_on_fail: bool = False
    ) -> None:
        """
        Process a mining response from a worker.
        
        Args:
            response: Response dictionary from worker
            worker_type: 'gpu' or 'cpu'
            worker_id: Worker ID number
            wallet_address: Wallet that was mining
            challenge_id: Challenge ID that was being mined
            is_dev_solution: Whether this is a dev fee solution
            current_challenge: Current challenge object
            num_workers: Total number of workers of this type (for hashrate calc)
            keep_wallet_on_fail: If True, don't release wallet if no solution found
        """
        # All CPU workers share a single "cpu" pool, GPUs each have their own
        pool_id: PoolId = "cpu" if worker_type == 'cpu' else worker_id
        
        # Handle errors
        if response.get('error'):
            logging.error(f"{worker_type.upper()} {worker_id} Error: {response['error']}")
            wallet_pool.release_wallet(pool_id, wallet_address, challenge_id, solved=False)
            return
        
        # Handle solutions
        if response.get('found'):
            self._handle_solution(
                response=response,
                worker_type=worker_type,
                worker_id=worker_id,
                pool_id=pool_id,
                wallet_address=wallet_address,
                challenge_id=challenge_id,
                is_dev_solution=is_dev_solution,
                current_challenge=current_challenge
            )
        else:
            # No solution found
            if not is_dev_solution:
                if not keep_wallet_on_fail:
                    wallet_pool.release_wallet(pool_id, wallet_address, challenge_id, solved=False)
                else:
                    # Sticky wallet: Don't release, so it stays "in_use" for this worker
                    pass
        
        # Update hashrate
        self._update_hashrate(response, worker_type, num_workers)
    
    def _handle_solution(
        self,
        response: MineResponse,
        worker_type: WorkerType,
        worker_id: int,
        pool_id: PoolId,
        wallet_address: str,
        challenge_id: str,
        is_dev_solution: bool,
        current_challenge: Challenge
    ) -> None:
        """
        Handle a found solution - submit and update stats.
        
        Args:
            response: Response with solution
            worker_type: 'gpu' or 'cpu'
            worker_id: Worker ID
            pool_id: Pool identifier
            wallet_address: Wallet that found solution
            challenge_id: Challenge ID
            is_dev_solution: Whether dev fee solution
            current_challenge: Current challenge object
        """
        nonce_hex = mining_utils.format_nonce_hex(response['nonce'])
        
        if not is_dev_solution:
            logging.info(
                f"{worker_type.upper()} {worker_id} SOLUTION FOUND! "
                f"Nonce: {response['nonce']}"
            )
        
        # Submit solution
        success, is_fatal = api.submit_solution(wallet_address, challenge_id, nonce_hex)
        
        if success:
            self._handle_successful_submission(
                wallet_address=wallet_address,
                challenge_id=challenge_id,
                nonce_hex=nonce_hex,
                is_dev_solution=is_dev_solution,
                pool_id=pool_id,
                current_challenge=current_challenge
            )
        else:
            self._handle_failed_submission(
                wallet_address=wallet_address,
                challenge_id=challenge_id,
                nonce_hex=nonce_hex,
                is_dev_solution=is_dev_solution,
                is_fatal=is_fatal,
                pool_id=pool_id,
                current_challenge=current_challenge
            )
    
    def _handle_successful_submission(
        self,
        wallet_address: str,
        challenge_id: str,
        nonce_hex: str,
        is_dev_solution: bool,
        pool_id: PoolId,
        current_challenge: Challenge
    ) -> None:
        """Handle successful solution submission."""
        if not is_dev_solution:
            logging.info("✓ Solution submitted successfully!")
        wallet_pool.release_wallet(pool_id, wallet_address, challenge_id, solved=True)
        
        # Update database
        db.mark_challenge_solved(wallet_address, challenge_id)
        db.add_solution(
            challenge_id,
            nonce_hex,
            wallet_address,
            current_challenge['difficulty'],
            is_dev_solution=is_dev_solution
        )
        db.update_solution_status(challenge_id, nonce_hex, 'accepted')
        
        # Update session stats
        if is_dev_solution:
            self.dev_session_solutions += 1
        else:
            self.session_solutions += 1
            if wallet_address not in self.wallet_session_solutions:
                self.wallet_session_solutions[wallet_address] = 0
            self.wallet_session_solutions[wallet_address] += 1
    
    def _handle_failed_submission(
        self,
        wallet_address: str,
        challenge_id: str,
        nonce_hex: str,
        is_dev_solution: bool,
        is_fatal: bool,
        pool_id: PoolId,
        current_challenge: Challenge
    ) -> None:
        """Handle failed solution submission."""
        if is_fatal:
            logging.error("✗ Fatal error submitting solution (Rejected). Marking as solved.")
            wallet_pool.release_wallet(pool_id, wallet_address, challenge_id, solved=True)
            
            # Still mark as solved so we don't retry
            db.mark_challenge_solved(wallet_address, challenge_id)
            db.add_solution(
                challenge_id,
                nonce_hex,
                wallet_address,
                current_challenge['difficulty'],
                is_dev_solution=is_dev_solution
            )
            db.update_solution_status(challenge_id, nonce_hex, 'rejected')
        else:
            # Transient error - release wallet and add to retry queue
            wallet_pool.release_wallet(pool_id, wallet_address, challenge_id, solved=False)
            logging.error("✗ Solution submission failed (transient error)")
            
            # Add to persistent storage for retry
            db.add_failed_solution(
                wallet_address,
                challenge_id,
                nonce_hex,
                current_challenge['difficulty'],
                is_dev_solution
            )
    
    def _update_hashrate(
        self,
        response: MineResponse,
        worker_type: WorkerType,
        num_workers: int
    ) -> None:
        """Update hashrate estimates based on worker response."""
        if not response.get('hashes') or not response.get('duration'):
            return
        
        hashes = response['hashes']
        duration = response['duration']
        
        if duration <= 0:
            return
        
        instant_hashrate = mining_utils.calculate_hashrate(hashes, duration)
        total_hashrate = instant_hashrate * num_workers
        
        if worker_type == 'gpu':
            self.gpu_hashrate = mining_utils.smooth_hashrate(
                self.gpu_hashrate,
                total_hashrate,
                HASHRATE_EMA_WEIGHT_OLD
            )
        elif worker_type == 'cpu':
            self.cpu_hashrate = mining_utils.smooth_hashrate(
                self.cpu_hashrate,
                total_hashrate,
                HASHRATE_EMA_WEIGHT_OLD
            )
            logging.debug(
                f"CPU Hashrate Updated: {self.cpu_hashrate:.2f} "
                f"(Instant: {instant_hashrate:.2f}, Total: {total_hashrate:.2f})"
            )
    
    def get_total_hashrate(self) -> float:
        """Get combined GPU + CPU hashrate."""
        return self.gpu_hashrate + self.cpu_hashrate
    
    def get_stats(self) -> Dict[str, any]:
        """
        Get current statistics.
        
        Returns:
            Dictionary with hashrate and solution counts
        """
        return {
            'gpu_hashrate': self.gpu_hashrate,
            'cpu_hashrate': self.cpu_hashrate,
            'total_hashrate': self.get_total_hashrate(),
            'session_solutions': self.session_solutions,
            'dev_session_solutions': self.dev_session_solutions,
            'wallet_solutions': self.wallet_session_solutions.copy()
        }
