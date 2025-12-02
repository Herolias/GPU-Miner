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
        # Track sticky wallets for GPU workers: worker_id -> wallet_address
        self.gpu_sticky_wallets: Dict[int, str] = {}
        # Track sticky wallets for CPU workers: worker_id -> wallet_address
        self.cpu_sticky_wallets: Dict[int, str] = {}
        # Track deferred dev-fee assignments for CPU workers
        self.cpu_pending_dev_fee: Dict[int, bool] = {}
        # Track current challenges being mined on each worker (for ROM stickiness)
        self.gpu_current_challenges: Dict[int, str] = {}
        self.cpu_current_challenges: Dict[int, str] = {}
    
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
        # Get sticky address if this worker already has one
        sticky_address = None
        if not desired_dev_wallet:
            if worker_type == 'gpu':
                sticky_address = self.gpu_sticky_wallets.get(worker_id)
            elif worker_type == 'cpu':
                sticky_address = self.cpu_sticky_wallets.get(worker_id)
        
        # SMART CHALLENGE SELECTION: Minimize wallet creation
        if not available_challenges:
            return None
        
        # Sort challenges by discovery time (oldest first) for normal operation
        # Challenges have 'discovered_at' field from challenge_cache
        available_challenges.sort(key=lambda c: c.get('discovered_at', ''))
        
        # Detect difficulty spike: newest challenge harder than oldest?
        oldest_difficulty = int(available_challenges[0]['difficulty'], 16)
        newest_difficulty = int(available_challenges[-1]['difficulty'], 16)
        difficulty_increased = newest_difficulty > oldest_difficulty
        
        # Reorder challenges for difficulty spike mode
        if difficulty_increased:
            # DIFFICULTY SPIKE MODE: Prioritize clearing all lower-difficulty challenges
            # This allows creating new wallets to quickly finish easier challenges
            # before they expire
            lower_diff_challenges = [
                c for c in available_challenges 
                if int(c['difficulty'], 16) == oldest_difficulty
            ]
            higher_diff_challenges = [
                c for c in available_challenges 
                if int(c['difficulty'], 16) != oldest_difficulty
            ]
            if lower_diff_challenges:
                # Prioritize lower difficulty first, then higher
                available_challenges = lower_diff_challenges + higher_diff_challenges
                logging.debug(f"Difficulty spike detected - prioritizing lower difficulty challenges")
        
        # WALLET REUSE FIX: Try all challenges before creating new wallet
        # Loop through challenges to find one where an existing wallet is available
        wallet = None
        selected_challenge = None
        
        for challenge in available_challenges:
            wallet, is_dev = self._select_wallet(
                pool_id,
                challenge,
                desired_dev_wallet,
                sticky_address,
                worker_id,
                worker_type,  # Pass worker_type for dev wallet ROM stickiness
                allow_creation=False  # Don't create yet, just try existing wallets
            )
            if wallet:
                selected_challenge = challenge
                break
        
        # Only create new wallet if no existing wallet available for ANY challenge
        if not wallet:
            # Use oldest challenge for new wallet creation
            selected_challenge = available_challenges[0]
            wallet, is_dev = self._select_wallet(
                pool_id,
                selected_challenge,
                desired_dev_wallet,
                sticky_address,
                worker_id,
                worker_type,  # Pass worker_type for dev wallet ROM stickiness
                allow_creation=True  # Now we can create
            )
        
        if not wallet:
            return None
        
        challenge = selected_challenge
        
        # Track current challenge for this worker (for dev wallet ROM stickiness)
        if worker_type == 'gpu':
            self.gpu_current_challenges[worker_id] = challenge['challenge_id']
        elif worker_type == 'cpu':
            self.cpu_current_challenges[worker_id] = challenge['challenge_id']
            
        # Update sticky tracking for workers
        if worker_type == 'gpu' and not is_dev:
            # Track sticky wallet for GPU
            if worker_id not in self.gpu_sticky_wallets:
                 logging.debug(f"Coordinator: Assigned sticky wallet {wallet['address'][:8]} to GPU {worker_id}")
            self.gpu_sticky_wallets[worker_id] = wallet['address']
        elif worker_type == 'cpu' and not is_dev:
            # Track sticky wallet for CPU
            if worker_id not in self.cpu_sticky_wallets:
                 logging.info(f"Coordinator: Assigned sticky wallet {wallet['address'][:8]} to CPU worker {worker_id}")
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
    
    def _select_wallet(
        self,
        pool_id: PoolId,
        challenge: Challenge,
        use_dev_wallet: bool,
        sticky_address: Optional[str] = None,
        worker_id: Optional[int] = None,
        worker_type: Optional[WorkerType] = None,
        allow_creation: bool = True
    ) -> tuple[Optional[WalletOptional], bool]:
        """
        Select a wallet for mining.
        
        Args:
            pool_id: Pool identifier
            challenge: Challenge to mine
            use_dev_wallet: Whether to prefer dev wallet
            sticky_address: Optional sticky wallet address for CPU workers
            worker_id: Optional worker ID
            worker_type: Optional worker type ('gpu' or 'cpu') for challenge tracking
            allow_creation: Whether to allow creating new wallets
            
        Returns:
            Tuple of (wallet, is_dev_wallet_flag)
        """
        if use_dev_wallet:
            # Get current challenge being mined on this worker (for ROM stickiness)
            current_challenge_id = None
            if worker_id is not None and worker_type:
                if worker_type == 'gpu':
                    current_challenge_id = self.gpu_current_challenges.get(worker_id)
                elif worker_type == 'cpu':
                    current_challenge_id = self.cpu_current_challenges.get(worker_id)
            
            wallet = self._allocate_dev_wallet(pool_id, challenge['challenge_id'], current_challenge_id, allow_creation)
            if wallet:
                return (wallet, True)
            if not allow_creation:
                return (None, False)
            # BUGFIX: If dev wallet creation failed, fall back to user wallet
            # This ensures workers don't sit idle when dev pool is busy/full
            logging.debug("Dev wallet unavailable for pool %s; using user wallet instead", pool_id)
            # Fall through to allocate user wallet below
        
        wallet = self._allocate_user_wallet(pool_id, challenge, sticky_address, worker_id, allow_creation)
        return (wallet, False)
    
    def _allocate_dev_wallet(
        self, 
        pool_id: PoolId, 
        challenge_id: str, 
        current_challenge_id: Optional[str] = None,
        allow_creation: bool = True
    ) -> Optional[WalletOptional]:
        """
        Allocate a dev wallet from the pool with challenge-sticky logic.
        
        IMPROVED LOGIC:
        - First tries to allocate a dev wallet for the CURRENT challenge (same ROM)
        - Only switches to a different challenge if no dev wallets available for current
        - Searches all existing dev wallets before creating a new one
        - This prevents excessive wallet creation and minimizes ROM switching
        
        Args:
            pool_id: Pool identifier
            challenge_id: Challenge ID that needs a dev wallet
            current_challenge_id: The challenge currently loaded in ROM (for stickiness)
            allow_creation: Whether to create new wallets if none available
            
        Returns:
            Allocated dev wallet, or None if unavailable
        """
        # STEP 1: Try to allocate for the CURRENT challenge (if provided and same as requested)
        # This keeps the same ROM loaded, avoiding expensive ROM switches
        if current_challenge_id and current_challenge_id == challenge_id:
            wallet = wallet_pool.allocate_wallet(pool_id, current_challenge_id, require_dev=True)
            if wallet:
                logging.debug(f"Dev wallet allocated for current challenge {challenge_id[:8]} (same ROM)")
                return wallet
        
        # STEP 2: Try to allocate for the requested challenge
        # (might be different from current, triggering ROM switch)
        wallet = wallet_pool.allocate_wallet(pool_id, challenge_id, require_dev=True)
        if wallet:
            if current_challenge_id and current_challenge_id != challenge_id:
                logging.debug(f"Dev wallet allocated for different challenge {challenge_id[:8]} (ROM switch required)")
            return wallet
        
        # STEP 3: Only create if allowed and after searching all existing wallets
        if not allow_creation:
            return None
        
        # Before creating a new dev wallet, check if we have ANY dev wallets
        # that haven't solved the current/requested challenge
        # This prevents wallet explosion
        from .wallet_pool import wallet_pool as wp
        pool_stats = wp.get_pool_stats(pool_id)
        dev_total = pool_stats.get('dev_total', 0)
        dev_available = pool_stats.get('dev_available', 0)
        
        # If we have dev wallets but none are available, it means they're all in use
        # or have solved this challenge. Creating more would just increase overhead.
        if dev_total > 0 and dev_available == 0:
            logging.debug(
                f"Pool {pool_id}: {dev_total} dev wallets exist but none available for {challenge_id[:8]}, "
                f"not creating new wallet to avoid explosion"
            )
            return None
        
        # STEP 4: Create a single new dev wallet as last resort
        # Only create ONE wallet (not a batch) to minimize dev wallet count
        logging.info(f"Creating new dev wallet for pool {pool_id} (challenge {challenge_id[:8]})")
        created = wallet_pool.create_wallet(pool_id, is_dev_wallet=True)
        if not created:
            logging.error(f"Failed to create dev wallet for pool {pool_id}")
            return None
        
        # STEP 5: Try one more time to allocate the newly created wallet
        wallet = wallet_pool.allocate_wallet(pool_id, challenge_id, require_dev=True)
        if not wallet:
            logging.warning(f"Dev wallet created but could not be allocated for pool {pool_id}")
        return wallet
    
    def _allocate_user_wallet(
        self,
        pool_id: PoolId,
        challenge: Challenge,
        sticky_address: Optional[str],
        worker_id: Optional[int],
        allow_creation: bool = True
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
                # Check if wallet already solved this challenge
                solved_challenges = wallet.get('solved_challenges', [])
                if challenge_id in solved_challenges:
                    logging.debug(
                        "Sticky wallet %s already solved %s, clearing sticky and allocating new wallet",
                        sticky_address[:8],
                        challenge_id[:8]
                    )
                    # Don't use this wallet - fall through to normal allocation
                    sticky_address = None
                else:
                    # Wallet can be reused for this challenge
                    if wallet.get('current_challenge') != challenge_id:
                        wallet_pool.reuse_wallet(pool_id, sticky_address, challenge_id)
                        wallet['current_challenge'] = challenge_id
                    return wallet
            
            if sticky_address:  # Only log if we haven't cleared it above
                logging.warning("Sticky wallet %s not found via get_wallet", sticky_address[:8])
        
        wallet = wallet_pool.allocate_wallet(pool_id, challenge_id)
        if wallet:
            return wallet
        
        # Only create if allowed
        if not allow_creation:
            return None
        
        # GPU OPTIMIZATION: Create batch of wallets for GPU workers to reduce ROM switching
       # Check if this is a GPU pool (numeric ID) vs CPU pool (string "cpu")
        is_gpu_pool = isinstance(pool_id, int)
        
        if is_gpu_pool:
            # GPU workers: Create 20 wallets at once to minimize ROM switches
            created_count = wallet_pool.create_wallets_batch(pool_id, count=20, is_dev_wallet=False)
            if created_count > 0:
                logging.info(f"Created batch of {created_count} wallets for GPU {pool_id}, reducing ROM switching")
                # Now try to allocate one of the newly created wallets
                return wallet_pool.allocate_wallet(pool_id, challenge_id)
            return None
        else:
            # CPU workers: Create single wallet (original behavior)
            created = wallet_pool.create_wallet(pool_id, is_dev_wallet=False)
            if not created:
                return None
            return wallet_pool.allocate_wallet(pool_id, challenge_id)

    def clear_sticky_wallet(self, worker_id: int, worker_type: WorkerType = 'cpu') -> None:
        """Clear the sticky wallet assignment for a worker."""
        if worker_type == 'gpu' and worker_id in self.gpu_sticky_wallets:
            logging.debug(f"Coordinator: Clearing sticky wallet for GPU {worker_id}")
            del self.gpu_sticky_wallets[worker_id]
        elif worker_type == 'cpu' and worker_id in self.cpu_sticky_wallets:
            logging.info(f"Coordinator: Clearing sticky wallet for CPU worker {worker_id}")
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
            
            # Add [DEV] indicator for dev wallets
            is_dev = wallet.get('is_dev_wallet', False)
            dev_indicator = "[DEV] " if is_dev else ""
            
            logging.info(
                f"{worker_type.upper()} {worker_id} mining {challenge_short}... "
                f"with {dev_indicator}wallet {wallet_short}..."
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
