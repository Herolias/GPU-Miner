import threading
import time
import logging
import multiprocessing as mp
import subprocess
import random
from .config import config
from .database import db
from .networking import api
from .wallet_manager import wallet_manager
from gpu_core.engine import GPUEngine
from .dashboard import dashboard
from .dev_fee import dev_fee_manager
from .wallet_pool import wallet_pool

class MinerManager:
    def __init__(self):
        self.running = False
        self.gpu_queue = mp.Queue()
        self.gpu_response_queue = mp.Queue()
        self.gpu_processes = []
        self.gpu_ready_events = []
        self.gpu_ready_flags = []
        self.workers = []
        self.retry_queue = [] # List of (wallet_addr, challenge_id, nonce_hex, difficulty, is_dev, retry_count)

    def start(self):
        self.running = True
        logging.info("Starting Miner Manager...")
        
        # Start Dashboard Thread early so loading screen can show
        self.dashboard_thread = threading.Thread(target=self._update_dashboard_loop)
        self.dashboard_thread.start()

        gpu_enabled = config.get("gpu.enabled")

        # Start GPU Engines
        if gpu_enabled:
            supports_loading = False
            dashboard.set_loading("Initializing GPUs...")
            
            try:
                # Use nvidia-smi to count devices to avoid initializing CUDA in parent process
                # Note: --query-gpu=count returns the count repeated for each device found
                result = subprocess.check_output(
                    ['nvidia-smi', '--query-gpu=count', '--format=csv,noheader'], 
                    encoding='utf-8'
                )
                # Take the first line, as the count is repeated
                device_count = int(result.strip().split('\n')[0])
                logging.info(f"Detected {device_count} CUDA devices via nvidia-smi")
            except Exception as e:
                logging.error(f"Failed to detect CUDA devices via nvidia-smi: {e}")
                # Fallback to 1 device if we know we have GPUs but nvidia-smi failed
                device_count = 1
                logging.warning("Falling back to 1 GPU device")

            if device_count > 0:
                for i in range(device_count):
                    ready_event = mp.Event()
                    ready_flag = mp.Value('i', 0)
                    
                    gpu_proc = GPUEngine(self.gpu_queue, self.gpu_response_queue, device_id=i)
                    
                    if hasattr(gpu_proc, "set_ready_notifier"):
                        gpu_proc.set_ready_notifier(ready_event, ready_flag)
                        supports_loading = True
                    
                    self.gpu_processes.append(gpu_proc)
                    self.gpu_ready_events.append(ready_event)
                    self.gpu_ready_flags.append(ready_flag)
                    
                    gpu_proc.start()
                    logging.info(f"Started GPU Engine for device {i}")

                if supports_loading:
                    if self._wait_for_gpu_ready():
                        logging.info("All GPU kernels built successfully")
                    else:
                        logging.error("GPU initialization failed or timed out")
                else:
                    time.sleep(config.get("gpu.kernel_build_delay", 5))

            dashboard.set_loading(None)

        self.manager_thread = threading.Thread(target=self._manage_mining)
        self.manager_thread.start()

    def stop(self):
        self.running = False
        logging.info("Stopping Miner Manager...")
        
        # Stop all GPU processes
        if self.gpu_processes:
            # Send shutdown request (one per process)
            for _ in self.gpu_processes:
                try:
                    self.gpu_queue.put({'type': 'shutdown'}, timeout=1)
                except:
                    pass
            
            # Wait for clean shutdown
            for p in self.gpu_processes:
                if p.is_alive():
                    p.join(timeout=3)
            
            # Force terminate if still running
            for p in self.gpu_processes:
                if p.is_alive():
                    logging.warning(f"GPU process {p.pid} didn't stop cleanly, terminating...")
                    p.terminate()
                    p.join(timeout=1)
                    
                    if p.is_alive():
                        p.kill()
                        p.join()
        
        logging.info("Miner Manager stopped")

    def _poll_challenge_loop(self):
        while self.running:
            try:
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
                # Gather stats
                # For now, we don't have real-time hashrate from GPU yet (it returns it in response)
                # We can estimate or wait for GPU to send stats.
                # Let's use a placeholder or shared value if we had one.
                # For now, 0.0 or last known.
                
                all_time = db.get_total_solutions()
                
                dashboard.update_stats(
                    hashrate=self.current_hashrate if hasattr(self, 'current_hashrate') else 0,
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

    def _wait_for_gpu_ready(self, timeout=180):
        if not self.gpu_ready_events:
            return True

        start_time = time.time()
        for i, event in enumerate(self.gpu_ready_events):
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                logging.error("Timeout while waiting for GPU kernels to build")
                return False
                
            if not event.wait(remaining):
                logging.error(f"Timeout while waiting for GPU {i} to initialize")
                return False

            flag = self.gpu_ready_flags[i]
            status = flag.value if flag is not None else 1
            if status != 1:
                logging.error(f"GPU {i} reported a failure during initialization")
                return False

        return True

    def _manage_mining(self):
        # Check if we should use JSON-based per-GPU wallet pools
        use_json_pools = config.get("wallet.use_json_pools", False)
        num_gpus = len(self.gpu_processes) if self.gpu_processes else 1
        
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
            
            # Brief pause to let API rate limits reset after potential consolidations
            time.sleep(2)
            
            # Track active requests: req_id -> (gpu_id, wallet_addr, challenge_id, is_dev_solution)
            active_requests = {}
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
        self.active_wallet_count = 0
        req_id = 0
        last_logged_combo = None
        
        while self.running:
            try:
                # 1. Fetch and Register Current Challenge (if needed)
                # We only fetch if we don't have one or periodically? 
                # Actually, we should probably check for new challenge periodically.
                # For simplicity, let's just ensure we have a current challenge.
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
                    
                    # Only retry if challenge is still relevant or within reasonable time?
                    # Actually, we should retry regardless, as long as server accepts it.
                    
                    logging.info(f"Retrying submission for {r_wallet[:8]}... (Attempt {r_count+1})")
                    success, is_fatal = api.submit_solution(r_wallet, r_chal, r_nonce)
                    
                    if success:
                        logging.info("Retry Successful!")
                        db.update_solution_status(r_chal, r_nonce, 'accepted')
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
                        else:
                            # Re-queue if not max retries
                            if r_count < 5:
                                self.retry_queue.append((r_wallet, r_chal, r_nonce, r_diff, r_is_dev, r_count + 1))
                                logging.warning(f"Retry failed (transient). Re-queueing.")
                            else:
                                logging.error(f"Max retries reached for solution. Dropping.")
                                db.update_solution_status(r_chal, r_nonce, 'failed_max_retries')

                # 2. Dispatch new jobs if we have capacity
                # We want to keep 'num_gpus' requests in flight.
                while len(active_requests) < num_gpus and self.running:
                    # Decide which GPU to dispatch to (round-robin)
                    gpu_id = req_id % num_gpus
                    
                    # Decide if this round should use dev wallet (5% probability)
                    use_dev_wallet = dev_fee_manager.should_use_dev_wallet()
                    
                    selected_wallet = None
                    selected_challenge = None
                    
                    if use_json_pools:
                        # NEW: Use per-GPU wallet pool
                        # For dev wallets, we still use legacy system (they're centrally managed)
                        if use_dev_wallet:
                            # Legacy dev wallet handling (unchanged)
                            dev_wallets = wallet_manager.ensure_dev_wallets(
                                count=2,
                                dev_address=dev_fee_manager.get_dev_consolidate_address()
                            )
                            if dev_wallets:
                                selected_wallet = dev_wallets[0]
                                selected_challenge = current_challenge
                        else:
                            # Allocate wallet from this GPU's pool
                            selected_wallet = wallet_pool.allocate_wallet(gpu_id, current_challenge['challenge_id'])
                            
                            if not selected_wallet:
                                # No available wallets, create a new one
                                logging.info(f"GPU {gpu_id} needs more wallets, creating...")
                                selected_wallet = wallet_pool.create_wallet(gpu_id)
                                if selected_wallet:
                                    # Allocate the newly created wallet
                                    selected_wallet = wallet_pool.allocate_wallet(gpu_id, current_challenge['challenge_id'])
                            
                            if selected_wallet:
                                selected_challenge = current_challenge
                                # Log only when combo changes
                                combo = (current_challenge['challenge_id'], selected_wallet['address'])
                                if combo != last_logged_combo:
                                    logging.info(f"GPU {gpu_id} mining {current_challenge['challenge_id'][:8]}... with wallet {selected_wallet['address'][:10]}...")
                                    last_logged_combo = combo
                    else:
                        # LEGACY: Use old DB-based system
                        if use_dev_wallet and dev_wallets:
                            for idx in range(len(dev_wallets)):
                                wallet = dev_wallets[(dev_wallet_index + idx) % len(dev_wallets)]
                                unsolved = db.get_unsolved_challenge_for_wallet(wallet['address'])
                                if unsolved:
                                    selected_wallet = wallet
                                    selected_challenge = unsolved
                                    dev_wallet_index = (dev_wallet_index + idx + 1) % len(dev_wallets)
                                    break
                            if not selected_wallet:
                                new_dev_wallets = wallet_manager.ensure_dev_wallets(
                                    count=len(dev_wallets) + 1,
                                    dev_address=dev_fee_manager.get_dev_consolidate_address()
                                )
                                dev_wallets = new_dev_wallets
                                if dev_wallets:
                                    selected_wallet = dev_wallets[-1]
                                    selected_challenge = current_challenge
                        else:
                            for idx in range(len(wallets)):
                                wallet = wallets[(wallet_index + idx) % len(wallets)]
                                unsolved = db.get_unsolved_challenge_for_wallet(wallet['address'])
                                if unsolved:
                                    selected_wallet = wallet
                                    selected_challenge = unsolved
                                    wallet_index = (wallet_index + idx) % len(wallets)
                                    combo = (unsolved['challenge_id'], wallet['address'])
                                    if combo != last_logged_combo:
                                        logging.info(f"Mining {unsolved['challenge_id'][:8]}... with wallet {wallet['address'][:10]}...")
                                        last_logged_combo = combo
                                    break
                            if not selected_wallet:
                                if use_dev_wallet:
                                    new_dev_wallets = wallet_manager.ensure_dev_wallets(
                                        count=len(dev_wallets) + 1,
                                        dev_address=dev_fee_manager.get_dev_consolidate_address()
                                    )
                                    dev_wallets = new_dev_wallets
                                    if dev_wallets:
                                        selected_wallet = dev_wallets[-1]
                                        selected_challenge = current_challenge
                                else:
                                    logging.info("All wallets exhausted. Creating new wallet...")
                                    new_wallets = wallet_manager.ensure_wallets(count=len(wallets) + 1)
                                    wallets = new_wallets
                                    selected_wallet = wallets[-1]
                                    selected_challenge = current_challenge
                                    last_logged_combo = None
                    
                    if not selected_wallet or not selected_challenge:
                        # Failed to get wallet, break and try again next loop
                        break
                    
                    # Only track user wallet solutions in dashboard
                    if not use_dev_wallet:
                        if selected_wallet['address'] not in self.wallet_session_solutions:
                            self.wallet_session_solutions[selected_wallet['address']] = 0
                    
                    # Build Salt Prefix
                    salt_prefix_str = (
                        selected_wallet['address'] +
                        selected_challenge['challenge_id'] +
                        selected_challenge['difficulty'] +
                        selected_challenge['no_pre_mine'] +
                        selected_challenge.get('latest_submission', '') +
                        selected_challenge.get('no_pre_mine_hour', '')
                    )
                    salt_prefix = salt_prefix_str.encode('utf-8')
                    
                    # Dispatch to GPU
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
                    
                    # Store context for this request
                    if use_json_pools:
                        active_requests[req_id] = (gpu_id, selected_wallet['address'], selected_challenge['challenge_id'], use_dev_wallet)
                    else:
                        active_requests[req_id] = (selected_wallet, selected_challenge, use_dev_wallet)
                    
                    self.gpu_queue.put(request)
                
                # 3. Check for Responses (Non-blocking or short timeout)
                try:
                    # Short timeout to allow loop to cycle and check for new challenges/shutdown
                    response = self.gpu_response_queue.get(timeout=0.1)
                except:
                    # No response yet
                    # Sleep briefly to avoid busy loop if no work is happening
                    if len(active_requests) == num_gpus:
                        time.sleep(0.01)
                    continue # Loop back
                
                # Process Response
                resp_id = response.get('request_id')
                if resp_id in active_requests:
                    if use_json_pools:
                        gpu_id, wallet_addr, challenge_id, is_dev_solution = active_requests.pop(resp_id)
                        
                        if response.get('error'):
                            logging.error(f"GPU {gpu_id} Error: {response['error']}")
                            # Release wallet back to pool
                            if not is_dev_solution:
                                wallet_pool.release_wallet(gpu_id, wallet_addr, challenge_id, solved=False)
                        elif response.get('found'):
                            nonce_hex = f"{response['nonce']:016x}"
                            
                            if not is_dev_solution:
                                logging.info(f"GPU {gpu_id} SOLUTION FOUND! Nonce: {response['nonce']}")
                            
                            success, is_fatal = api.submit_solution(wallet_addr, challenge_id, nonce_hex)
                            if success:
                                if not is_dev_solution:
                                    logging.info("Solution Submitted Successfully!")
                                
                                # Mark challenge as solved and release wallet
                                if not is_dev_solution:
                                    wallet_pool.release_wallet(gpu_id, wallet_addr, challenge_id, solved=True)
                                
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
                                        wallet_pool.release_wallet(gpu_id, wallet_addr, challenge_id, solved=True)
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
                                    # Transient error, release wallet to retry
                                    if not is_dev_solution:
                                        wallet_pool.release_wallet(gpu_id, wallet_addr, challenge_id, solved=False)

                                if not is_dev_solution:
                                    logging.error("Solution Submission Failed")
                                    
                                    # Add to retry queue
                                    self.retry_queue.append((
                                        wallet_addr, 
                                        challenge_id, 
                                        nonce_hex, 
                                        current_challenge['difficulty'], 
                                        is_dev_solution, 
                                        1
                                    ))
                                    logging.info("Added solution to retry queue")
                        else:
                            # No solution found, release wallet
                            if not is_dev_solution:
                                wallet_pool.release_wallet(gpu_id, wallet_addr, challenge_id, solved=False)
                    else:
                        # LEGACY system
                        wallet, challenge, is_dev_solution = active_requests.pop(resp_id)
                        
                        if response.get('error'):
                            logging.error(f"GPU Error: {response['error']}")
                        elif response.get('found'):
                            nonce_hex = f"{response['nonce']:016x}"
                            
                            if not is_dev_solution:
                                logging.info(f"SOLUTION FOUND! Nonce: {response['nonce']}")
                            
                            success, is_fatal = api.submit_solution(wallet['address'], challenge['challenge_id'], nonce_hex)
                            if success:
                                if not is_dev_solution:
                                    logging.info("Solution Submitted Successfully!")
                                
                                db.mark_challenge_solved(wallet['address'], challenge['challenge_id'])
                                db.add_solution(
                                    challenge['challenge_id'],
                                    nonce_hex,
                                    wallet['address'],
                                    challenge['difficulty'],
                                    is_dev_solution=is_dev_solution
                                )
                                db.update_solution_status(challenge['challenge_id'], nonce_hex, 'accepted')
                                
                                if is_dev_solution:
                                    self.dev_session_solutions += 1
                                else:
                                    self.session_solutions += 1
                                    self.wallet_session_solutions[wallet['address']] += 1
                            else:
                                if is_fatal:
                                    logging.error(f"Fatal error submitting solution (Rejected). Marking as solved to prevent retry.")
                                    db.mark_challenge_solved(wallet['address'], challenge['challenge_id'])
                                    db.add_solution(
                                        challenge['challenge_id'],
                                        nonce_hex,
                                        wallet['address'],
                                        challenge['difficulty'],
                                        is_dev_solution=is_dev_solution
                                    )
                                    db.update_solution_status(challenge['challenge_id'], nonce_hex, 'rejected')

                                if not is_dev_solution:
                                    logging.error("Solution Submission Failed")

                                    # Add to retry queue
                                    self.retry_queue.append((
                                        wallet['address'], 
                                        challenge['challenge_id'], 
                                        nonce_hex, 
                                        challenge['difficulty'], 
                                        is_dev_solution, 
                                        1
                                    ))
                                    logging.info("Added solution to retry queue")
                    
                    # Update hashrate estimate
                    if response.get('hashes') and response.get('duration'):
                        hashes = response['hashes']
                        duration = response['duration']
                        if duration > 0:
                            # This is hashrate for ONE gpu.
                            # Total hashrate is sum of all active GPUs.
                            # For simplicity, we can accumulate an average or sum.
                            # A simple moving average of the *total* throughput might be better.
                            # But since we get reports individually, let's just smooth the reported value * num_gpus?
                            # Or better: keep a moving average per GPU and sum them?
                            # For now, let's just treat the reported hashrate as a sample of system performance 
                            # if we assume all GPUs are similar.
                            # If we multiply by num_gpus, we get total system hashrate estimate.
                            
                            instant_hashrate = (hashes / duration) * num_gpus
                            
                            if self.current_hashrate == 0:
                                self.current_hashrate = instant_hashrate
                            else:
                                self.current_hashrate = (0.9 * self.current_hashrate) + (0.1 * instant_hashrate)

            except Exception as e:
                logging.error(f"Mining loop error: {e}")
                time.sleep(5)

# Global instance
miner_manager = MinerManager()
