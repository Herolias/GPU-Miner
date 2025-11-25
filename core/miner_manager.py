import multiprocessing as mp
import threading
import time
import logging
import os
import signal
import sys
import random
import queue
from pathlib import Path

from .config import config
from .networking import api
from .database import db
from .wallet_manager import wallet_manager
from gpu_core.engine import GPUEngine
from .dashboard import dashboard
from .dev_fee import dev_fee_manager
from .wallet_pool import wallet_pool
from cpu_core.worker import CPUWorker

class MinerManager:
    def __init__(self):
        self.running = False
        self.gpu_processes = []
        self.gpu_ready_events = []
        self.gpu_ready_flags = []
        
        self.cpu_queue = mp.Queue()
        self.cpu_response_queue = mp.Queue()
        self.cpu_workers = []
        
        self.workers = []
        self.retry_queue = [] # List of (wallet_addr, challenge_id, nonce_hex, difficulty, is_dev, retry_count)
        self.challenge_lock = threading.Lock()
        
        self.gpu_hashrate = 0
        self.cpu_hashrate = 0
        self.current_hashrate = 0
        self.session_solutions = 0
        self.dev_session_solutions = 0
        self.wallet_session_solutions = {}

    def start(self):
        self.running = True
        logging.info("Starting Miner Manager...")
        
        # Start Dashboard Thread early so loading screen can show
        self.dashboard_thread = threading.Thread(target=self._update_dashboard_loop)
        self.dashboard_thread.start()

        gpu_enabled = config.get("gpu.enabled")

        # Start GPU Engines
        if gpu_enabled:
            try:
                # Detect GPUs (using nvidia-smi or similar, simplified here)
                # For now, we assume 1 GPU or config based.
                # In a real scenario, we'd enumerate devices.
                # Let's assume we launch one engine per GPU found.
                # If no auto-detect, check config.
                
                # Simple GPU detection via nvidia-smi
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
                    ready_event = mp.Event()
                    ready_flag = mp.Value('i', 0) # 0=Not Ready, 1=Ready, -1=Error
                    self.gpu_ready_events.append(ready_event)
                    self.gpu_ready_flags.append(ready_flag)
                    
                    p = GPUEngine(self.gpu_queue, self.gpu_response_queue, device_id=i, ready_event=ready_event, ready_flag=ready_flag)
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
            
        # Start CPU Workers
        cpu_enabled = config.get("cpu.enabled")
        if cpu_enabled:
            num_cpu_workers = config.get("cpu.workers", 1)
            logging.info(f"Starting {num_cpu_workers} CPU workers...")
            
            for i in range(num_cpu_workers):
                worker = CPUWorker(i, self.cpu_queue, self.cpu_response_queue)
                self.cpu_workers.append(worker)
                worker.start()
                logging.info(f"Started CPU Worker {i}")

        self.manager_thread = threading.Thread(target=self._manage_mining)
        self.manager_thread.start()
        
        # Start Challenge Polling
        self.poll_thread = threading.Thread(target=self._poll_challenge_loop)
        self.poll_thread.start()

    def stop(self):
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
        
        # Stop all CPU workers
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

    def _poll_challenge_loop(self):
        while self.running:
            try:
                # Poll for new challenge
                challenge = api.get_current_challenge()
                if challenge:
                    with self.challenge_lock:
                        self.latest_challenge = challenge
                    
                    # Register the challenge in DB
                    db.register_challenge(challenge)
                
                time.sleep(1.0) # Poll every second
            except Exception as e:
                logging.error(f"Challenge polling error: {e}")
                time.sleep(5)

    def _update_dashboard_loop(self):
        while self.running:
            try:
                all_time = db.get_total_solutions()
                
                dashboard.update_stats(
                    hashrate=self.current_hashrate if hasattr(self, 'current_hashrate') else 0,
                    cpu_hashrate=self.cpu_hashrate if hasattr(self, 'cpu_hashrate') else 0,
                    gpu_hashrate=self.gpu_hashrate if hasattr(self, 'gpu_hashrate') else 0,
                    session_sol=self.session_solutions if hasattr(self, 'session_solutions') else 0,
                    all_time_sol=all_time,
                    wallet_sols=self.wallet_session_solutions if hasattr(self, 'wallet_session_solutions') else {},
                    active_wallets=self.active_wallet_count if hasattr(self, 'active_wallet_count') else 0,
                    challenge=self.current_challenge_id if hasattr(self, 'current_challenge_id') else "Waiting...",
                    difficulty=self.current_difficulty if hasattr(self, 'current_difficulty') else "N/A"
                )
                dashboard.render()
                time.sleep(1)
            except Exception as e:
                logging.error(f"Dashboard error: {e}")
                time.sleep(5)

    def _wait_for_gpu_ready(self, timeout=600):
        """Wait for GPU kernels to compile. Increased timeout for multi-GPU systems."""
        if not self.gpu_ready_events:
            return True

        start_time = time.time()
        for i, event in enumerate(self.gpu_ready_events):
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                logging.error("Timeout while waiting for GPU kernels to build")
                logging.error("This can happen on slower systems or with many GPUs compiling in parallel")
                return False
            
            # Log progress every 30 seconds
            elapsed = time.time() - start_time
            if elapsed > 30 and i == 0:
                logging.info(f"Still compiling kernels... ({int(elapsed)}s elapsed, {int(remaining)}s remaining)")
            
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

    def _manage_mining(self):
        # Check if we should use JSON-based per-GPU wallet pools
        use_json_pools = config.get("wallet.use_json_pools", False)
        num_gpus = len(self.gpu_processes) if self.gpu_processes else 0
        num_cpus = len(self.cpu_workers) if self.cpu_workers else 0
        
        if use_json_pools:
            logging.info("Using JSON-based per-GPU wallet pools")
            
            # Migrate existing DB wallets to GPU pools (one-time)
            try:
                db_wallets = db.get_wallets()
                if db_wallets:
                    logging.info(f"Migrating {len(db_wallets)} wallets from DB to GPU pools...")
                    # Distribute wallets evenly across GPUs
                    for i, wallet in enumerate(db_wallets):
                        gpu_id = i % num_gpus
                        wallet_pool.migrate_from_db(gpu_id, [wallet])
            except Exception as e:
                logging.warning(f"DB migration skipped: {e}")
            
            # Ensure each GPU has sufficient wallets
            wallets_per_gpu = config.get("wallet.wallets_per_gpu", 10)
            logging.info(f"Ensuring {wallets_per_gpu} wallets per GPU...")
            for gpu_id in range(num_gpus):
                wallet_pool.ensure_wallets(gpu_id, wallets_per_gpu)
                wallet_pool.ensure_wallets(gpu_id, wallets_per_gpu)
                # Consolidate any existing wallets that might have been missed (ASYNC)
                wallet_pool.start_consolidation_thread(gpu_id)
                
                stats = wallet_pool.get_pool_stats(gpu_id)
                logging.info(f"GPU {gpu_id}: {stats['total']} wallets ({stats['available']} available)")
            
            # Ensure CPU wallets
            if num_cpus > 0:
                logging.info(f"Ensuring wallets for {num_cpus} CPU workers...")
                for i in range(num_cpus):
                    pool_id = f"cpu_{i}"
                    wallet_pool.ensure_wallets(pool_id, wallets_per_gpu) # Reuse same count
                    wallet_pool.start_consolidation_thread(pool_id)
                    stats = wallet_pool.get_pool_stats(pool_id)
                    logging.info(f"CPU {i}: {stats['total']} wallets ({stats['available']} available)")
            
            # Brief pause to let API rate limits reset after potential consolidations
            time.sleep(2)
            
            # Track active requests: req_id -> (type, worker_id, wallet_addr, challenge_id, is_dev_solution)
            active_requests = {}
            
            # Separate tracking for dispatching
            active_gpu_requests = 0
            active_cpu_requests = 0
        else:
            logging.info("Using legacy DB-based wallet management")
            # Legacy system
            max_workers = max(1, config.get("miner.max_workers", 1))
            wallets = wallet_manager.ensure_wallets(count=5)
            dev_wallets = wallet_manager.ensure_dev_wallets(
                count=2,
                dev_address=dev_fee_manager.get_dev_consolidate_address()
            )
            wallet_manager.consolidate_existing_wallets()
            
            # Track active requests: req_id -> (wallet, challenge, is_dev_solution)
            active_requests = {}
            wallet_index = 0
            dev_wallet_index = 0
        
        current_challenge = None
        self.current_challenge_id = None
        self.current_difficulty = None
        self.session_solutions = 0
        self.dev_session_solutions = 0
        self.wallet_session_solutions = {}
        self.current_hashrate = 0
        self.gpu_hashrate = 0
        self.cpu_hashrate = 0
        self.active_wallet_count = 0
        req_id = 0
        last_logged_combos = {}
        
        while self.running:
            try:
                # 1. Fetch and Register Current Challenge (if needed)
                if not current_challenge or (req_id % 10 == 0): # Check every 10 requests
                    new_challenge = api.get_current_challenge()
                    if new_challenge:
                        current_challenge = new_challenge
                        db.register_challenge(current_challenge)
                        self.current_challenge_id = current_challenge['challenge_id']
                        self.current_difficulty = current_challenge['difficulty']
                
                if not current_challenge:
                    self.active_wallet_count = 0
                    logging.warning("Waiting for challenge...")
                    time.sleep(1)
                    continue

                # 1.5 Process Retry Queue
                # Try to resubmit failed solutions
                if self.retry_queue:
                    retry_item = self.retry_queue.pop(0)
                    r_wallet, r_chal, r_nonce, r_diff, r_is_dev, r_count = retry_item
                    
                    logging.info(f"Retrying submission for {r_wallet[:8]}... (Attempt {r_count+1})")
                    success, is_fatal = api.submit_solution(r_wallet, r_chal, r_nonce)
                    
                    if success:
                        logging.info("Retry Successful!")
                        db.update_solution_status(r_chal, r_nonce, 'accepted')
                        # Update DB retry status
                        db.update_retry_status(r_chal, r_nonce, True)
                        
                        if r_is_dev:
                            self.dev_session_solutions += 1
                        else:
                            self.session_solutions += 1
                            if r_wallet in self.wallet_session_solutions:
                                self.wallet_session_solutions[r_wallet] += 1
                    else:
                        if is_fatal:
                            logging.error(f"Retry failed fatally. Dropping.")
                            db.update_solution_status(r_chal, r_nonce, 'rejected')
                            db.update_retry_status(r_chal, r_nonce, True) # Remove from retry list as it's fatal
                        else:
                            # Re-queue if not max retries (Immediate)
                            if r_count < 5:
                                self.retry_queue.append((r_wallet, r_chal, r_nonce, r_diff, r_is_dev, r_count + 1))
                                logging.warning(f"Retry failed (transient). Re-queueing.")
                            else:
                                logging.error(f"Max immediate retries reached. Updating DB status.")
                                db.update_solution_status(r_chal, r_nonce, 'failed_max_retries')
                                db.update_retry_status(r_chal, r_nonce, False) # Mark as failed in DB for later retry

                # 1b. Check for pending retries from DB (Persistent)
                # Only check occasionally
                if req_id % 100 == 0:
                    pending_retries = db.get_pending_retries()
                    for p in pending_retries:
                        # Add to retry queue if not already there
                        in_queue = False
                        for q_item in self.retry_queue:
                            if q_item[1] == p['challenge_id'] and q_item[2] == p['nonce']:
                                in_queue = True
                                break
                        
                        if not in_queue:
                            self.retry_queue.append((
                                p['wallet_address'],
                                p['challenge_id'],
                                p['nonce'],
                                p['difficulty'],
                                p['is_dev_solution'],
                                p.get('retry_count', 0)
                            ))
                            logging.info(f"Loaded pending retry from DB: {p['challenge_id'][:8]}...")

                # 2. Dispatch new jobs if we have capacity
                # --- GPU DISPATCH ---
                while active_gpu_requests < num_gpus and self.running:
                    gpu_id = req_id % num_gpus
                    use_dev_wallet = dev_fee_manager.should_use_dev_wallet()
                    selected_wallet = None
                    selected_challenge = None
                    
                    if use_json_pools:
                        if use_dev_wallet:
                            dev_wallets = wallet_manager.ensure_dev_wallets(
                                count=2,
                                dev_address=dev_fee_manager.get_dev_consolidate_address()
                            )
                            if dev_wallets:
                                selected_wallet = dev_wallets[0]
                                selected_challenge = current_challenge
                        else:
                            selected_wallet = wallet_pool.allocate_wallet(gpu_id, current_challenge['challenge_id'])
                            if not selected_wallet:
                                selected_wallet = wallet_pool.create_wallet(gpu_id)
                                if selected_wallet:
                                    selected_wallet = wallet_pool.allocate_wallet(gpu_id, current_challenge['challenge_id'])
                            
                            if selected_wallet:
                                selected_challenge = current_challenge
                                combo = (current_challenge['challenge_id'], selected_wallet['address'])
                                pool_key = f"gpu_{gpu_id}"
                                if combo != last_logged_combos.get(pool_key):
                                    logging.info(f"GPU {gpu_id} mining {current_challenge['challenge_id'][:8]}... with wallet {selected_wallet['address'][:10]}...")
                                    last_logged_combos[pool_key] = combo
                    else:
                        # Legacy (omitted for brevity, assume JSON pools active)
                        pass
                    
                    if not selected_wallet or not selected_challenge:
                        break
                    
                    if not use_dev_wallet:
                        if selected_wallet['address'] not in self.wallet_session_solutions:
                            self.wallet_session_solutions[selected_wallet['address']] = 0
                    
                    salt_prefix_str = (
                        selected_wallet['address'] +
                        selected_challenge['challenge_id'] +
                        selected_challenge['difficulty'] +
                        selected_challenge['no_pre_mine'] +
                        selected_challenge.get('latest_submission', '') +
                        selected_challenge.get('no_pre_mine_hour', '')
                    )
                    salt_prefix = salt_prefix_str.encode('utf-8')
                    
                    difficulty_value = int(selected_challenge['difficulty'][:8], 16)
                    start_nonce = random.getrandbits(64)
                    
                    req_id += 1
                    request = {
                        'id': req_id,
                        'type': 'mine',
                        'rom_key': selected_challenge['no_pre_mine'],
                        'salt_prefix': salt_prefix,
                        'difficulty': difficulty_value,
                        'start_nonce': start_nonce
                    }
                    
                    if use_json_pools:
                        active_requests[req_id] = ('gpu', gpu_id, selected_wallet['address'], selected_challenge['challenge_id'], use_dev_wallet)
                        active_gpu_requests += 1
                    else:
                        active_requests[req_id] = (selected_wallet, selected_challenge, use_dev_wallet)
                    
                    self.gpu_queue.put(request)

                # --- CPU DISPATCH ---
                while active_cpu_requests < num_cpus and self.running:
                    busy_cpus = set()
                    for r_info in active_requests.values():
                        if r_info[0] == 'cpu':
                            busy_cpus.add(r_info[1])
                    
                    if len(busy_cpus) >= num_cpus:
                        break
                        
                    free_cpu_id = -1
                    for i in range(num_cpus):
                        if i not in busy_cpus:
                            free_cpu_id = i
                            break
                    
                    if free_cpu_id == -1:
                        break
                        
                    use_dev_wallet = dev_fee_manager.should_use_dev_wallet()
                    selected_wallet = None
                    selected_challenge = None
                    pool_id = f"cpu_{free_cpu_id}"
                    
                    if use_dev_wallet:
                        dev_wallets = wallet_manager.ensure_dev_wallets(
                            count=2,
                            dev_address=dev_fee_manager.get_dev_consolidate_address()
                        )
                        if dev_wallets:
                            selected_wallet = dev_wallets[0]
                            selected_challenge = current_challenge
                    else:
                        selected_wallet = wallet_pool.allocate_wallet(pool_id, current_challenge['challenge_id'])
                        if not selected_wallet:
                            selected_wallet = wallet_pool.create_wallet(pool_id)
                            if selected_wallet:
                                selected_wallet = wallet_pool.allocate_wallet(pool_id, current_challenge['challenge_id'])
                    
                    if selected_wallet:
                        selected_challenge = current_challenge
                        combo = (current_challenge['challenge_id'], selected_wallet['address'])
                        if combo != last_logged_combos.get(pool_id):
                            logging.info(f"CPU {free_cpu_id} mining {current_challenge['challenge_id'][:8]}... with wallet {selected_wallet['address'][:10]}...")
                            last_logged_combos[pool_id] = combo
                    
                    if not selected_wallet or not selected_challenge:
                        break
                        
                    if not use_dev_wallet:
                        if selected_wallet['address'] not in self.wallet_session_solutions:
                            self.wallet_session_solutions[selected_wallet['address']] = 0

                    salt_prefix_str = (
                        selected_wallet['address'] +
                        selected_challenge['challenge_id'] +
                        selected_challenge['difficulty'] +
                        selected_challenge['no_pre_mine'] +
                        selected_challenge.get('latest_submission', '') +
                        selected_challenge.get('no_pre_mine_hour', '')
                    )
                    salt_prefix = salt_prefix_str.encode('utf-8')
                    
                    # Parse full 256-bit difficulty
                    difficulty_full = int(selected_challenge['difficulty'], 16)
                    start_nonce = random.getrandbits(64)
                    
                    req_id += 1
                    request = {
                        'id': req_id,
                        'type': 'mine',
                        'rom_key': selected_challenge['no_pre_mine'],
                        'salt_prefix': salt_prefix,
                        'difficulty': difficulty_full,
                        'start_nonce': start_nonce
                    }
                    
                    active_requests[req_id] = ('cpu', free_cpu_id, selected_wallet['address'], selected_challenge['challenge_id'], use_dev_wallet)
                    active_cpu_requests += 1
                    
                    self.cpu_queue.put(request)
                
                # 3. Check for Responses
                # GPU
                try:
                    response = self.gpu_response_queue.get_nowait()
                    self._process_response(response, active_requests, use_json_pools, current_challenge)
                    active_gpu_requests -= 1
                except queue.Empty:
                    pass
                except Exception as e:
                    pass

                # CPU
                try:
                    response = self.cpu_response_queue.get_nowait()
                    self._process_response(response, active_requests, use_json_pools, current_challenge)
                    active_cpu_requests -= 1
                except queue.Empty:
                    pass
                except Exception as e:
                    pass

                if active_gpu_requests == num_gpus and active_cpu_requests == num_cpus:
                    time.sleep(0.01)
                
            except Exception as e:
                logging.error(f"Mining loop error: {e}")
                time.sleep(5)

    def _process_response(self, response, active_requests, use_json_pools, current_challenge):
        resp_id = response.get('request_id')
        if resp_id in active_requests:
            if use_json_pools:
                worker_type, worker_id, wallet_addr, challenge_id, is_dev_solution = active_requests.pop(resp_id)
                pool_id = f"cpu_{worker_id}" if worker_type == 'cpu' else worker_id
                
                if response.get('error'):
                    logging.error(f"{worker_type.upper()} {worker_id} Error: {response['error']}")
                    if not is_dev_solution:
                        wallet_pool.release_wallet(pool_id, wallet_addr, challenge_id, solved=False)
                elif response.get('found'):
                    nonce_hex = f"{response['nonce']:016x}"
                    
                    if not is_dev_solution:
                        logging.info(f"{worker_type.upper()} {worker_id} SOLUTION FOUND! Nonce: {response['nonce']}")
                    
                    success, is_fatal = api.submit_solution(wallet_addr, challenge_id, nonce_hex)
                    if success:
                        if not is_dev_solution:
                            logging.info("Solution Submitted Successfully!")
                        
                        if not is_dev_solution:
                            wallet_pool.release_wallet(pool_id, wallet_addr, challenge_id, solved=True)
                        
                        db.mark_challenge_solved(wallet_addr, challenge_id)
                        db.add_solution(
                            challenge_id,
                            nonce_hex,
                            wallet_addr,
                            current_challenge['difficulty'],
                            is_dev_solution=is_dev_solution
                        )
                        db.update_solution_status(challenge_id, nonce_hex, 'accepted')
                        
                        if is_dev_solution:
                            self.dev_session_solutions += 1
                        else:
                            self.session_solutions += 1
                            self.wallet_session_solutions[wallet_addr] += 1
                    else:
                        if is_fatal:
                            logging.error(f"Fatal error submitting solution (Rejected). Marking as solved.")
                            if not is_dev_solution:
                                wallet_pool.release_wallet(pool_id, wallet_addr, challenge_id, solved=True)
                            db.mark_challenge_solved(wallet_addr, challenge_id)
                            db.add_solution(
                                challenge_id,
                                nonce_hex,
                                wallet_addr,
                                current_challenge['difficulty'],
                                is_dev_solution=is_dev_solution
                            )
                            db.update_solution_status(challenge_id, nonce_hex, 'rejected')
                        else:
                            if not is_dev_solution:
                                wallet_pool.release_wallet(pool_id, wallet_addr, challenge_id, solved=False)

                        if not is_dev_solution:
                            logging.error("Solution Submission Failed")
                            
                            # Add to retry queue (Immediate)
                            self.retry_queue.append((
                                wallet_addr, 
                                challenge_id, 
                                nonce_hex, 
                                current_challenge['difficulty'], 
                                is_dev_solution, 
                                1
                            ))
                            
                            # Persist to DB
                            db.add_failed_solution(
                                wallet_addr,
                                challenge_id,
                                nonce_hex,
                                current_challenge['difficulty'],
                                is_dev_solution
                            )
                            
                            logging.info("Added solution to retry queue and persisted to DB")
                else:
                    if not is_dev_solution:
                        wallet_pool.release_wallet(pool_id, wallet_addr, challenge_id, solved=False)
            else:
                # LEGACY system (Not updated for CPU as we enforce JSON pools for CPU)
                pass

            # Update hashrate estimate
            if response.get('hashes') and response.get('duration'):
                hashes = response['hashes']
                duration = response['duration']
                if duration > 0:
                    instant_hashrate = (hashes / duration)
                    
                    if worker_type == 'gpu':
                        num_gpus = len(self.gpu_processes) if self.gpu_processes else 1
                        total_gpu_rate = instant_hashrate * num_gpus
                        
                        if self.gpu_hashrate == 0:
                            self.gpu_hashrate = total_gpu_rate
                        else:
                            self.gpu_hashrate = (0.9 * self.gpu_hashrate) + (0.1 * total_gpu_rate)
                    
                    elif worker_type == 'cpu':
                        num_cpus = len(self.cpu_workers) if self.cpu_workers else 1
                        total_cpu_rate = instant_hashrate * num_cpus
                        
                        if self.cpu_hashrate == 0:
                            self.cpu_hashrate = total_cpu_rate
                        else:
                            self.cpu_hashrate = (0.9 * self.cpu_hashrate) + (0.1 * total_cpu_rate)
                        
                        logging.debug(f"CPU Hashrate Updated: {self.cpu_hashrate} (Instant: {instant_hashrate}, Total: {total_cpu_rate})")
                    
                    self.current_hashrate = self.gpu_hashrate + self.cpu_hashrate

# Global instance
miner_manager = MinerManager()
