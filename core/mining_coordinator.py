"""
Mining Coordinator Module

Coordinates job dispatch to GPU and CPU workers, handling wallet allocation,
request building, and worker job queueing.
"""

import logging
from typing import Optional, Dict
import multiprocessing as mp

from .wallet_pool import wallet_pool
from .types import Challenge, WalletOptional, MineRequest, WorkerType, PoolId
from . import mining_utils


class MiningCoordinator:
    """
    Coordinates mining job dispatch to workers.
    
    Handles:
    - Wallet selection (user wallets vs dev wallets)
    - Mining request creation
    - Job queueing to workers
    - Logging mining status
    """
    
    def __init__(
        self,
        gpu_queue: Optional[mp.Queue] = None,
        cpu_queue: Optional[mp.Queue] = None
    ) -> None:
        """
        Initialize mining coordinator.
        
        Args:
            gpu_queue: Queue for GPU mining requests
            cpu_queue: Queue for CPU mining requests
        """
        self.gpu_queue = gpu_queue
        self.cpu_queue = cpu_queue
        self.last_logged_combos: Dict[str, tuple] = {}
        # Track sticky wallets for CPU workers: worker_id -> wallet_address
        self.cpu_sticky_wallets: Dict[int, str] = {}
        # Track deferred dev-fee assignments for CPU workers
        self.cpu_pending_dev_fee: Dict[int, bool] = {}
    
    def dispatch_job(
        self,
        worker_type: WorkerType,
        worker_id: int,
        available_challenges: list[Challenge],
        req_id: int,
        use_dev_wallet: bool = False,
        cached_rom_keys: Optional[set[str]] = None
    ) -> Optional[tuple[WalletOptional, str, bool]]:
        """
        Dispatch a mining job to a worker.
        
        Args:
            worker_type: 'gpu' or 'cpu'
            worker_id: Worker ID number
            available_challenges: List of valid challenges to choose from
            req_id: Request ID for tracking
            use_dev_wallet: Whether to use a dev wallet for this job
            cached_rom_keys: Set of ROM keys currently cached in GPU memory
            
        Returns:
            Tuple of (wallet, challenge_id, is_dev_solution) if job dispatched,
            None if no wallet available
        """
        # All CPU workers share a single "cpu" pool, GPU workers each get their own pool
        pool_id: PoolId = "cpu" if worker_type == 'cpu' else worker_id
        
        # Check for sticky wallet (CPU only)
        sticky_address = None
        desired_dev_wallet = use_dev_wallet
        if worker_type == 'cpu':
            sticky_address = self.cpu_sticky_wallets.get(worker_id)
            if self.cpu_pending_dev_fee.get(worker_id):
                desired_dev_wallet = True
            if sticky_address and desired_dev_wallet:
                # Can't swap wallets mid-stream; defer dev fee until wallet rotates
                self.cpu_pending_dev_fee[worker_id] = True
                desired_dev_wallet = False
            
        # Select wallet first (without challenge assignment yet)
        wallet, is_dev = self._select_wallet_only(
            pool_id,
            desired_dev_wallet,
            sticky_address,
            worker_id
        )
        if not wallet:
            return None
        
        # MULTI-CHALLENGE: Select optimal challenge for this specific wallet
        challenge = self.select_challenge_for_wallet(
            wallet['address'],
            available_challenges,
            cached_rom_keys or set()
        )
        
        if not challenge:
            logging.debug(f"No available challenge for wallet {wallet['address'][:8]}")
            # Release wallet since we can't use it
            wallet_pool.release_wallet(pool_id, wallet['address'])
            return None
        
        # Update wallet with the actual challenge
        # For sticky wallets, use reuse_wallet; for new allocations, update directly
        if sticky_address and wallet['address'] == sticky_address:
            # Sticky wallet - update its challenge
            wallet_pool.reuse_wallet(pool_id, wallet['address'], challenge['challenge_id'])
            wallet['current_challenge'] = challenge['challenge_id']
        else:
            # New allocation - update challenge info
            wallet['current_challenge'] = challenge['challenge_id']
            # Note: wallet is already marked in_use by allocate_wallet or manually above
            
        # Update sticky tracking if this is a CPU worker
        if worker_type == 'cpu' and not is_dev:
            if worker_id not in self.cpu_sticky_wallets:
                 logging.info(f"Coordinator: Assigned sticky wallet {wallet['address'][:8]} to worker {worker_id}")
            self.cpu_sticky_wallets[worker_id] = wallet['address']
            if not desired_dev_wallet and worker_id in self.cpu_pending_dev_fee and not self.cpu_pending_dev_fee[worker_id]:
                self.cpu_pending_dev_fee.pop(worker_id, None)
        elif worker_type == 'cpu' and is_dev:
            # Dev wallet assignment fulfilled; clear pending flag
            self.cpu_pending_dev_fee.pop(worker_id, None)
        elif worker_type == 'cpu' and desired_dev_wallet and not is_dev:
            # Dev wallet was requested but unavailable; remember to try again
            self.cpu_pending_dev_fee[worker_id] = True
        
        # Log new mining combination
        self._log_mining_start(worker_type, worker_id, pool_id, challenge, wallet)
        
        # Build and queue request
        # CPU uses full 256-bit difficulty, GPU uses first 32 bits for performance
        request = self._build_mine_request(
            req_id=req_id,
            wallet=wallet,
            challenge=challenge,
            full_difficulty=False # CPU now uses 32-bit difficulty same as GPU
        )
        
        # Send to appropriate queue
        queue = self.cpu_queue if worker_type == 'cpu' else self.gpu_queue
        if queue:
            queue.put(request)
        
        # Track ROM usage for cache optimization
        if not hasattr(self, 'recent_rom_keys'):
            self.recent_rom_keys = set()
        self.recent_rom_keys.add(challenge['no_pre_mine'])
        if len(self.recent_rom_keys) > 10:  # Keep last 10
            self.recent_rom_keys = set(list(self.recent_rom_keys)[-10:])
        
        return (wallet, challenge['challenge_id'], is_dev)
    
    def select_challenge_for_wallet(
        self,
        wallet_address: str,
        available_challenges: list[Challenge],
        cached_rom_keys: set[str]
    ) -> Optional[Challenge]:
        """
        Select best challenge for wallet using prioritization strategy.
        
        Strategy:
        1. Filter out challenges wallet has already solved
        2. Sort by difficulty (lowest first)
        3. Prefer challenges with cached ROMs for GPU efficiency
        
        Args:
            wallet_address: Wallet to select challenge for
            available_challenges: List of valid challenges
            cached_rom_keys: Set of ROM keys currently in GPU cache
            
        Returns:
            Selected challenge or None if no suitable challenge found
        """
        if not available_challenges:
            return None
        
        # Filter: wallet hasn't solved this challenge
        unsolved = [
            c for c in available_challenges
            if not self._has_wallet_solved(wallet_address, c['challenge_id'])
        ]
        
        if not unsolved:
            return None
        
        # Sort by difficulty (ascending - lowest first)
        unsolved.sort(key=lambda c: int(c['difficulty'], 16))
        
        # Optimize: prefer challenges with cached ROMs
        cached_challenges = [c for c in unsolved if c['no_pre_mine'] in cached_rom_keys]
        if cached_challenges:
            selected = cached_challenges[0]
            logging.debug(f"Selected cached ROM challenge {selected['challenge_id'][:8]}...")
            return selected
        
        # Otherwise return lowest difficulty
        selected = unsolved[0]
        logging.debug(f"Selected challenge {selected['challenge_id'][:8]}... (difficulty: {selected['difficulty'][:10]}...)")
        return selected
    
    def _has_wallet_solved(self, wallet_address: str, challenge_id: str) -> bool:
        """
        Check if a wallet has solved a specific challenge.
        
        Args:
            wallet_address: Wallet address to check
            challenge_id: Challenge ID to check
            
        Returns:
            True if wallet has solved this challenge
        """
        from .wallet_pool import wallet_pool
        
        # Check all pools for this wallet
        # Note: This is a simplified check - in production you'd track all pools
        for pool_id in [0, 1, 2, 3, "cpu"]:
            try:
                wallet = wallet_pool.get_wallet(pool_id, wallet_address)
                if wallet:
                    solved = wallet.get('solved_challenges', [])
                    if challenge_id in solved:
                        return True
            except:
                # Pool doesn't exist or other error, skip
                pass
        
        return False
    
    def _select_wallet_only(
        self,
        pool_id: PoolId,
        use_dev_wallet: bool,
        sticky_address: Optional[str] = None,
        worker_id: Optional[int] = None
    ) -> tuple[Optional[WalletOptional], bool]:
        """
        Select a wallet without challenge assignment.
        
        Args:
            pool_id: Pool identifier
            use_dev_wallet: Whether to prefer dev wallet
            sticky_address: Sticky wallet address for CPU workers
            worker_id: Worker ID for CPU sticky tracking
            
        Returns:
            Tuple of (wallet, is_dev_wallet_flag)
        """
        if use_dev_wallet:
            # For dev wallets, try to get any available dev wallet
            # We'll assign the specific challenge later
            wallet = wallet_pool.allocate_wallet(pool_id, "any", require_dev=True)
            if wallet:
                return (wallet, True)
            
            # Create new dev wallet if none available
            created = wallet_pool.create_wallet(pool_id, is_dev_wallet=True)
            if created:
                wallet = wallet_pool.allocate_wallet(pool_id, "any", require_dev=True)
                if wallet:
                    return (wallet, True)
            
            logging.warning("No dev wallets available for pool %s; skipping dev fee assignment", pool_id)
            return (None, False)
        
        # For user wallets with sticky logic (CPU workers)
        if sticky_address:
            logging.debug(
                "Coordinator: Attempting to reuse sticky wallet %s for worker %s",
                sticky_address[:8],
                worker_id
            )
            wallet = wallet_pool.get_wallet(pool_id, sticky_address)
            if wallet:
                # FIX: Just return the sticky wallet directly
                # We'll update it with the actual challenge after challenge selection
                if not wallet.get('in_use'):
                    # Mark as in use temporarily (will be updated with real challenge later)
                    wallet['in_use'] = True
                    return (wallet, False)
                else:
                    logging.debug(f"Sticky wallet {sticky_address[:8]} is in use, will try to get another")
            else:
                logging.warning(f"Sticky wallet {sticky_address[:8]} not found in pool")
        
        # Try to allocate any available user wallet
        wallet = wallet_pool.allocate_wallet(pool_id, "any", require_dev=False)
        if wallet:
            return (wallet, False)
        
        # Try creating a new wallet
        created = wallet_pool.create_wallet(pool_id, is_dev_wallet=False)
        if not created:
            return (None, False)
        
        wallet = wallet_pool.allocate_wallet(pool_id, "any", require_dev=False)
        return (wallet, False) if wallet else (None, False)
    
    def _select_wallet(
        self,
        pool_id: PoolId,
        challenge: Challenge,
        use_dev_wallet: bool,
        sticky_address: Optional[str] = None,
        worker_id: Optional[int] = None
    ) -> tuple[Optional[WalletOptional], bool]:
        """
        Select a wallet for mining.
        
        Args:
            pool_id: Pool identifier
            challenge: Challenge to mine
            use_dev_wallet: Whether to prefer dev wallet
            
        Returns:
            Tuple of (wallet, is_dev_wallet_flag)
        """
        if use_dev_wallet:
            wallet = self._allocate_dev_wallet(pool_id, challenge['challenge_id'])
            if wallet:
                return (wallet, True)
            logging.warning("No dev wallets available for pool %s; skipping dev fee assignment", pool_id)
            return (None, False)
        
        wallet = self._allocate_user_wallet(pool_id, challenge, sticky_address, worker_id)
        return (wallet, False)
    
    def _allocate_dev_wallet(self, pool_id: PoolId, challenge_id: str) -> Optional[WalletOptional]:
        """Allocate a dev wallet from the pool with bounded creation attempts."""
        # Try to allocate existing dev wallet first
        wallet = wallet_pool.allocate_wallet(pool_id, challenge_id, require_dev=True)
        if wallet:
            return wallet
        
        # BUG FIX: Only create ONE new dev wallet instead of infinite loop
        # This prevents dev wallet explosion over time
        created = wallet_pool.create_wallet(pool_id, is_dev_wallet=True)
        if not created:
            logging.error("Failed to create dev wallet for pool %s", pool_id)
            return None
        
        # Try one more time to allocate the newly created wallet
        wallet = wallet_pool.allocate_wallet(pool_id, challenge_id, require_dev=True)
        if not wallet:
            logging.warning("Dev wallet created but could not be allocated for pool %s", pool_id)
        return wallet
    
    def _allocate_user_wallet(
        self,
        pool_id: PoolId,
        challenge: Challenge,
        sticky_address: Optional[str],
        worker_id: Optional[int]
    ) -> Optional[WalletOptional]:
        """Allocate a user wallet, reusing sticky assignments when possible."""
        challenge_id = challenge['challenge_id']
        if sticky_address:
            logging.debug(
                "Coordinator: Attempting to reuse sticky wallet %s for worker %s",
                sticky_address[:8],
                worker_id
            )
            wallet = wallet_pool.get_wallet(pool_id, sticky_address)
            if wallet:
                if wallet.get('current_challenge') != challenge_id:
                    wallet_pool.reuse_wallet(pool_id, sticky_address, challenge_id)
                    wallet['current_challenge'] = challenge_id
                return wallet
            logging.warning("Sticky wallet %s not found via get_wallet", sticky_address[:8])
        
        wallet = wallet_pool.allocate_wallet(pool_id, challenge_id)
        if wallet:
            return wallet
        
        created = wallet_pool.create_wallet(pool_id, is_dev_wallet=False)
        if not created:
            return None
        return wallet_pool.allocate_wallet(pool_id, challenge_id)

    def clear_sticky_wallet(self, worker_id: int) -> None:
        """Clear the sticky wallet assignment for a worker."""
        if worker_id in self.cpu_sticky_wallets:
            logging.info(f"Coordinator: Clearing sticky wallet for worker {worker_id}")
            del self.cpu_sticky_wallets[worker_id]
        self.cpu_pending_dev_fee.pop(worker_id, None)
    
    def _log_mining_start(
        self,
        worker_type: WorkerType,
        worker_id: int,
        pool_id: PoolId,
        challenge: Challenge,
        wallet: WalletOptional
    ) -> None:
        """
        Log the start of mining if this is a new challenge/wallet combination.
        
        Args:
            worker_type: 'gpu' or 'cpu'
            worker_id: Worker ID
            pool_id: Pool identifier
            challenge: Challenge being mined
            wallet: Wallet being used
        """
        combo = (challenge['challenge_id'], wallet['address'])
        
        # Use worker-specific key for tracking to avoid log spam when workers share pools
        tracker_key = f"{worker_type}_{worker_id}"
        
        # Only log if this is a new combination for this specific worker
        if combo != self.last_logged_combos.get(tracker_key):
            challenge_short = mining_utils.truncate_challenge_id(challenge['challenge_id'], 8)
            wallet_short = mining_utils.truncate_address(wallet['address'], 10)
            
            logging.info(
                f"{worker_type.upper()} {worker_id} mining {challenge_short}... "
                f"with wallet {wallet_short}..."
            )
            
            self.last_logged_combos[tracker_key] = combo
    
    def _build_mine_request(
        self,
        req_id: int,
        wallet: WalletOptional,
        challenge: Challenge,
        full_difficulty: bool = False
    ) -> MineRequest:
        """
        Build a mining request for a worker.
        
        Args:
            req_id: Request ID
            wallet: Wallet to mine with
            challenge: Challenge to mine
            full_difficulty: If True, use full 256-bit difficulty (CPU),
                           if False, use first 32 bits (GPU)
            
        Returns:
            Mining request dictionary
        """
        salt_prefix = mining_utils.build_salt_prefix(wallet, challenge)
        difficulty = mining_utils.parse_difficulty(
            challenge['difficulty'],
            full=full_difficulty
        )
        start_nonce = mining_utils.generate_random_nonce()
        
        return {
            'id': req_id,
            'type': 'mine',
            'rom_key': challenge['no_pre_mine'],
            'salt_prefix': salt_prefix,
            'difficulty': difficulty,
            'start_nonce': start_nonce
        }
    
    def can_dispatch_gpu(self, num_gpus: int, active_gpu_requests: int) -> bool:
        """Check if we can dispatch more GPU jobs."""
        return active_gpu_requests < num_gpus
    
    def can_dispatch_cpu(
        self,
        num_cpus: int,
        active_requests: Dict[int, tuple]
    ) -> Optional[int]:
        """
        Check if we can dispatch more CPU jobs and find free worker.
        
        Args:
            num_cpus: Total number of CPU workers
            active_requests: Dictionary of active requests
            
        Returns:
            Free CPU worker ID if available, None otherwise
        """
        # Find busy CPUs
        busy_cpus = set()
        for req_info in active_requests.values():
            if req_info[0] == 'cpu':
                busy_cpus.add(req_info[1])
        
        if len(busy_cpus) >= num_cpus:
            return None
        
        # Find first free CPU
        for i in range(num_cpus):
            if i not in busy_cpus:
                return i
        
        return None
