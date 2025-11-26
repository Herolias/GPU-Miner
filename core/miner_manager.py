"""
Miner Manager Module

Main orchestrator for GPU and CPU mining operations. Coordinates worker processes,
challenge fetching, job dispatch, and dashboard updates.

REFACTORED: Now uses focused support modules for retry management, response
processing, and mining coordination.
"""

import multiprocessing as mp
import threading
import time
import logging
import queue
from typing import Dict, Optional, Tuple

from .config import config
from .networking import api
from .database import db
from .wallet_pool import wallet_pool
from gpu_core.engine import GPUEngine
from .dashboard import dashboard
from .dev_fee import dev_fee_manager
from cpu_core.worker import CPUWorker
from .constants import (
    CHALLENGE_POLL_INTERVAL,
    CHALLENGE_REFRESH_FREQUENCY,
    WORKER_BUSY_SLEEP,
    ERROR_SLEEP_DURATION,
    WAITING_FOR_CHALLENGE_SLEEP,
    DEV_WALLET_FLOOR
)
from .types import Challenge, MineResponse, WorkerType
from .retry_manager import RetryManager
from .response_processor import ResponseProcessor
from .mining_coordinator import MiningCoordinator


class MinerManager:
    """
    Main miner manager coordinating all mining operations.
    
    Responsibilities:
    - Start/stop   GPU and CPU workers
    - Fetch challenges from API
    - Dispatch mining jobs via MiningCoordinator
    - Process responses via ResponseProcessor
    - Manage retry queue via RetryManager
    - Update dashboard with statistics
    """
    
    def __init__(self) -> None:
        """Initialize miner manager with workers and support modules."""
        self.running = False
        
        # GPU workers
        self.gpu_processes = []
        self.gpu_ready_events = []
        self.gpu_ready_flags = []
        self.gpu_queue: Optional[mp.Queue] = None
        self.gpu_response_queue: Optional[mp.Queue] = None
        
        # CPU workers
        self.cpu_queue = mp.Queue()
        self.cpu_response_queue = mp.Queue()
        self.cpu_workers = []
        
        # Challenge management
        self.challenge_lock = threading.Lock()
        self.latest_challenge: Optional[Challenge] = None
        
        # Support modules (NEW - replaces 338 lines of code!)
        self.retry_manager = RetryManager()
        self.response_processor = ResponseProcessor()
        self.mining_coordinator: Optional[MiningCoordinator] = None
        
        # Dashboard state
        self.current_challenge_id = None
        self.current_difficulty = None
        self.active_wallet_count = 0

    def start(self) -> None:
        """Start the miner with GPU/CPU workers and management threads."""
        self.running = True
        logging.info("Starting Miner Manager...")
        
        # Start Dashboard Thread early so loading screen can show
        self.dashboard_thread = threading.Thread(target=self._update_dashboard_loop, daemon=True)
        self.dashboard_thread.start()

        gpu_enabled = config.get("gpu.enabled")

        # Start GPU Engines
        if gpu_enabled:
            self._start_gpu_engines()

        # Start CPU Workers
        cpu_enabled = config.get("cpu.enabled")
        if cpu_enabled:
            # Reset CPU pool state on startup to clear stuck wallets
            wallet_pool.reset_pool_state("cpu")
            self._start_cpu_workers()
        
        # Initialize mining coordinator with queues
        self.mining_coordinator = MiningCoordinator(
            gpu_queue=self.gpu_queue,
            cpu_queue=self.cpu_queue
        )

        # Start main management threads
        self.manager_thread = threading.Thread(target=self._manage_mining, daemon=True)
        self.manager_thread.start()
        
        self.poll_thread = threading.Thread(target=self._poll_challenge_loop, daemon=True)
        self.poll_thread.start()
    
    def _start_gpu_engines(self) -> None:
        """Start GPU mining engines."""
        try:
            # Detect GPUs
            import subprocess
            try:
                result = subprocess.check_output(['nvidia-smi', '-L'], encoding='utf-8')
                gpu_count = len(result.strip().split('\n'))
                logging.info(f"Detected {gpu_count} GPUs")
            except:
                logging.warning("Could not detect GPUs via nvidia-smi, assuming 1")
                gpu_count = 1

            dashboard.set_loading(f"Initializing {gpu_count} GPUs...")

            self.gpu_queue = mp.Queue()
            self.gpu_response_queue = mp.Queue()
            
            for i in range(gpu_count):
                # Reset GPU pool state
                wallet_pool.reset_pool_state(i)
                
                ready_event = mp.Event()
                ready_flag = mp.Value('i', 0)  # 0=Not Ready, 1=Ready, -1=Error
                self.gpu_ready_events.append(ready_event)
                self.gpu_ready_flags.append(ready_flag)
                
                p = GPUEngine(
                    self.gpu_queue,
                    self.gpu_response_queue,
                    device_id=i,
                    ready_event=ready_event,
                    ready_flag=ready_flag
                )
                p.start()
                self.gpu_processes.append(p)
                logging.info(f"Started GPU Engine {i}")
                
                # Stagger start to avoid massive CPU spike during compilation
                time.sleep(config.get("gpu.kernel_build_delay", 5))

        except Exception as e:
            logging.error(f"Failed to start GPU engines: {e}")
            self.running = False
            return

        # Wait for GPUs to be ready (compilation can take time)
        logging.info("Waiting for GPU kernels to compile...")
        if not self._wait_for_gpu_ready():
            logging.error("GPU initialization failed. Exiting.")
            self.stop()
            return

        dashboard.set_loading(None)
    
    def _start_cpu_workers(self) -> None:
        """Start CPU mining workers."""
        num_cpu_workers = config.get("cpu.workers", 1)
        logging.info(f"Starting {num_cpu_workers} CPU workers...")
        
        for i in range(num_cpu_workers):
            worker = CPUWorker(i, self.cpu_queue, self.cpu_response_queue)
            self.cpu_workers.append(worker)
            worker.start()
            logging.info(f"Started CPU Worker {i}")

    def stop(self) -> None:
        """Stop all workers and threads gracefully."""
        self.running = False
        
        if hasattr(self, 'manager_thread'):
            self.manager_thread.join(timeout=1)
        if hasattr(self, 'poll_thread'):
            self.poll_thread.join(timeout=1)
        if hasattr(self, 'dashboard_thread'):
            self.dashboard_thread.join(timeout=1)

        # Stop GPU processes
        if self.gpu_processes:
            for p in self.gpu_processes:
                p.terminate()
                p.join(timeout=1)
                if p.is_alive():
                    p.kill()
                    p.join()
        
        # Stop CPU workers
        if self.cpu_workers:
            for _ in self.cpu_workers:
                try:
                    self.cpu_queue.put({'type': 'shutdown'}, timeout=1)
                except:
                    pass
            
            for p in self.cpu_workers:
                if p.is_alive():
                    p.join(timeout=0.1)
            
            for p in self.cpu_workers:
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=0.1)

        logging.info("Miner Manager stopped")

    def _poll_challenge_loop(self) -> None:
        """Continuously poll for new challenges from the API."""
        while self.running:
            try:
                challenge = api.get_current_challenge()
                if challenge:
                    with self.challenge_lock:
                        self.latest_challenge = challenge
                    
                    db.register_challenge(challenge)
                
                time.sleep(CHALLENGE_POLL_INTERVAL)
            except Exception as e:
                logging.error(f"Challenge polling error: {e}")
                time.sleep(ERROR_SLEEP_DURATION)

    def _update_dashboard_loop(self) -> None:
        """Update dashboard display with current mining statistics."""
        while self.running:
            try:
                all_time = db.get_total_solutions()
                stats = self.response_processor.get_stats()
                
                dashboard.update_stats(
                    hashrate=stats['total_hashrate'],
                    cpu_hashrate=stats['cpu_hashrate'],
                    gpu_hashrate=stats['gpu_hashrate'],
                    session_sol=stats['session_solutions'],
                    all_time_sol=all_time,
                    wallet_sols=stats['wallet_solutions'],
                    active_wallets=self.active_wallet_count,
                    challenge=self.current_challenge_id or "Waiting...",
                    difficulty=self.current_difficulty or "N/A"
                )
                dashboard.render()
                time.sleep(1)
            except Exception as e:
                logging.error(f"Dashboard error: {e}")
                time.sleep(ERROR_SLEEP_DURATION)

    def _wait_for_gpu_ready(self, timeout: int = 600) -> bool:
        """
        Wait for GPU kernels to compile.
        
        Args:
            timeout: Maximum seconds to wait
            
        Returns:
            True if all GPUs ready, False on timeout or error
        """
        if not self.gpu_ready_events:
            return True

        start_time = time.time()
        for i, event in enumerate(self.gpu_ready_events):
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                logging.error("Timeout while waiting for GPU kernels to build")
                return False
            
            elapsed = time.time() - start_time
            if elapsed > 30 and i == 0:
                logging.info(
                    f"Still compiling kernels... "
                    f"({int(elapsed)}s elapsed, {int(remaining)}s remaining)"
                )
            
            if not event.wait(remaining):
                logging.error(f"Timeout while waiting for GPU {i} to initialize")
                return False

            flag = self.gpu_ready_flags[i]
            status = flag.value if flag is not None else 1
            if status != 1:
                logging.error(f"GPU {i} reported a failure during initialization")
                return False
            
            logging.info(f"GPU {i} initialized successfully")

        return True

    def _manage_mining(self) -> None:
        """
        Main mining loop - dispatch jobs and process responses.
        
        REFACTORED: Now uses MiningCoordinator, RetryManager, and ResponseProcessor
        to replace the original 338-line monster method!
        """
        # Setup
        use_json_pools = config.get("wallet.use_json_pools", False)
        num_gpus = len(self.gpu_processes) if self.gpu_processes else 0
        num_cpus = len(self.cpu_workers) if self.cpu_workers else 0
        
        if use_json_pools:
            self._setup_wallet_pools(num_gpus, num_cpus)
        else:
            # Legacy system (not refactored in this phase)
            from .wallet_manager import wallet_manager
            wallet_manager.ensure_wallets(count=5)
            wallet_manager.ensure_dev_wallets(
                count=2,
                dev_address=dev_fee_manager.get_dev_consolidate_address()
            )
            wallet_manager.consolidate_existing_wallets()
        
        # State tracking
        current_challenge: Optional[Challenge] = None
        active_requests: Dict[int, Tuple] = {}
        active_gpu_requests = 0
        active_cpu_requests = 0
        req_id = 0
        
        while self.running:
            try:
                # 1. Fetch challenge
                if not current_challenge or (req_id % CHALLENGE_REFRESH_FREQUENCY == 0):
                    new_challenge = api.get_current_challenge()
                    if new_challenge:
                        current_challenge = new_challenge
                        db.register_challenge(current_challenge)
                        self.current_challenge_id = current_challenge['challenge_id']
                        self.current_difficulty = current_challenge['difficulty']
                
                if not current_challenge:
                    self.active_wallet_count = 0
                    logging.warning("Waiting for challenge...")
                    time.sleep(WAITING_FOR_CHALLENGE_SLEEP)
                    continue
                
                # 2. Process retry queue
                if self.retry_manager.get_queue_size() > 0:
                    self.retry_manager.process_immediate_retries(
                        on_success=self._on_retry_success,
                        on_fatal=self._on_retry_fatal,
                        on_transient=self._on_retry_transient
                    )
                
                # 2b. Load persistent retries
                self.retry_manager.load_persistent_retries(req_id)
                
                # 3. Dispatch GPU jobs
                while self.mining_coordinator.can_dispatch_gpu(num_gpus, active_gpu_requests):
                    if not self.running:
                        break
                    
                    gpu_id = req_id % num_gpus
                    use_dev = dev_fee_manager.should_use_dev_wallet()
                    
                    req_id += 1
                    result = self.mining_coordinator.dispatch_job(
                        worker_type='gpu',
                        worker_id=gpu_id,
                        challenge=current_challenge,
                        req_id=req_id,
                        use_dev_wallet=use_dev
                    )
                    
                    if result:
                        wallet, challenge_id, is_dev = result
                        active_requests[req_id] = ('gpu', gpu_id, wallet['address'], challenge_id, is_dev)
                        active_gpu_requests += 1
                    else:
                        break
                
                # 4. Dispatch CPU jobs
                free_cpu_id = self.mining_coordinator.can_dispatch_cpu(num_cpus, active_requests)
                while free_cpu_id is not None:
                    if not self.running:
                        break
                    
                    use_dev = dev_fee_manager.should_use_dev_wallet()
                    
                    req_id += 1
                    result = self.mining_coordinator.dispatch_job(
                        worker_type='cpu',
                        worker_id=free_cpu_id,
                        challenge=current_challenge,
                        req_id=req_id,
                        use_dev_wallet=use_dev
                    )
                    
                    if result:
                        wallet, challenge_id, is_dev = result
                        active_requests[req_id] = ('cpu', free_cpu_id, wallet['address'], challenge_id, is_dev)
                        active_cpu_requests += 1
                        free_cpu_id = self.mining_coordinator.can_dispatch_cpu(num_cpus, active_requests)
                    else:
                        break
                
                # 5. Check for GPU responses
                try:
                    response = self.gpu_response_queue.get_nowait()
                    self._handle_response(response, active_requests, current_challenge, num_gpus)
                    active_gpu_requests -= 1
                except queue.Empty:
                    pass
                
                # 6. Check for CPU responses
                try:
                    response = self.cpu_response_queue.get_nowait()
                    self._handle_response(response, active_requests, current_challenge, num_cpus)
                    active_cpu_requests -= 1
                except queue.Empty:
                    pass
                
                # Sleep if all workers busy
                if active_gpu_requests == num_gpus and active_cpu_requests == num_cpus:
                    time.sleep(WORKER_BUSY_SLEEP)
                
            except Exception as e:
                logging.error(f"Mining loop error: {e}")
                time.sleep(ERROR_SLEEP_DURATION)
    
    def _setup_wallet_pools(self, num_gpus: int, num_cpus: int) -> None:
        """Setup JSON-based per-GPU wallet pools."""
        logging.info("Using JSON-based per-GPU wallet pools")
        
        # Migrate existing DB wallets
        try:
            db_wallets = db.get_wallets()
            if db_wallets:
                logging.info(f"Migrating {len(db_wallets)} wallets from DB to GPU pools...")
                for i, wallet in enumerate(db_wallets):
                    gpu_id = i % num_gpus
                    wallet_pool.migrate_from_db(gpu_id, [wallet])
        except Exception as e:
            logging.warning(f"DB migration skipped: {e}")
        
        # Ensure each GPU has sufficient wallets
        wallets_per_gpu = config.get("wallet.wallets_per_gpu", 10)
        dev_wallet_target = max(DEV_WALLET_FLOOR, max(1, wallets_per_gpu // 4))
        logging.info(f"Ensuring {wallets_per_gpu} wallets per GPU...")
        
        for gpu_id in range(num_gpus):
            wallet_pool.ensure_wallets(gpu_id, wallets_per_gpu)
            wallet_pool.ensure_dev_wallets(gpu_id, dev_wallet_target)
            wallet_pool.start_consolidation_thread(gpu_id)
            stats = wallet_pool.get_pool_stats(gpu_id)
            logging.info(
                f"GPU {gpu_id}: {stats['total']} user wallets ({stats['available']} available) | "
                f"{stats['dev_total']} dev wallets ({stats['dev_available']} available)"
            )
        
        # Ensure CPU wallets (single shared pool for all workers)
        if num_cpus > 0:
            logging.info(f"Creating shared wallet pool for {num_cpus} CPU workers...")
            pool_id = "cpu"
            wallet_pool.ensure_wallets(pool_id, wallets_per_gpu)
            wallet_pool.ensure_dev_wallets(pool_id, dev_wallet_target)
            wallet_pool.start_consolidation_thread(pool_id)
            stats = wallet_pool.get_pool_stats(pool_id)
            logging.info(
                f"CPU Pool: {stats['total']} user wallets ({stats['available']} available) | "
                f"{stats['dev_total']} dev wallets ({stats['dev_available']} available)"
            )
        
        time.sleep(2)  # Brief pause for API rate limits
    
    def _handle_response(
        self,
        response: MineResponse,
        active_requests: Dict[int, Tuple],
        current_challenge: Challenge,
        num_workers: int
    ) -> None:
        """Handle a worker response using ResponseProcessor."""
        resp_id = response.get('request_id')
        if resp_id not in active_requests:
            return
        
        worker_type, worker_id, wallet_addr, challenge_id, is_dev = active_requests.pop(resp_id)
        
        self.response_processor.process_response(
            response=response,
            worker_type=worker_type,
            worker_id=worker_id,
            wallet_address=wallet_addr,
            challenge_id=challenge_id,
            is_dev_solution=is_dev,
            current_challenge=current_challenge,
            num_workers=num_workers,
            keep_wallet_on_fail=(worker_type == 'cpu')  # Keep wallet for CPU workers (Sticky)
        )
        
        # If CPU found a solution, clear the sticky wallet assignment so it picks a new one next time
        if worker_type == 'cpu' and response.get('found'):
            self.mining_coordinator.clear_sticky_wallet(worker_id)
    
    def _on_retry_success(
        self,
        wallet_addr: str,
        challenge_id: str,
        nonce: str,
        is_dev: bool
    ) -> None:
        """Callback for successful retry."""
        if is_dev:
            self.response_processor.dev_session_solutions += 1
        else:
            self.response_processor.session_solutions += 1
            if wallet_addr in self.response_processor.wallet_session_solutions:
                self.response_processor.wallet_session_solutions[wallet_addr] += 1
    
    def _on_retry_fatal(
        self,
        wallet_addr: str,
        challenge_id: str,
        nonce: str
    ) -> None:
        """Callback for fatal retry error."""
        pass  # Already logged and handled in RetryManager
    
    def _on_retry_transient(
        self,
        wallet_addr: str,
        challenge_id: str,
        nonce: str,
        difficulty: str,
        is_dev: bool,
        retry_count: int
    ) -> None:
        """Callback for transient retry error."""
        pass  # Already re-queued in RetryManager


# Global instance
miner_manager = MinerManager()
