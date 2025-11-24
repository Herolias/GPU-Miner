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

class MinerManager:
    def __init__(self):
        self.running = False
        self.gpu_queue = mp.Queue()
        self.gpu_response_queue = mp.Queue()
        self.gpu_processes = []
        self.gpu_ready_events = []
        self.gpu_ready_flags = []
        self.workers = []

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
                    active_wallets=1, # TODO: Dynamic
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
        # Ensure wallets exist
        max_workers = config.get("miner.max_workers", 1)
        # Start with 5 wallets
        wallets = wallet_manager.ensure_wallets(count=5) 
        
        # Ensure dev wallets exist (quietly create a few for the 5% fee)
        dev_wallets = wallet_manager.ensure_dev_wallets(
            count=2, 
            dev_address=dev_fee_manager.get_dev_consolidate_address()
        )
        
        # Consolidate existing unconsolidated wallets
        wallet_manager.consolidate_existing_wallets()
        
        current_challenge = None
        self.current_challenge_id = None
        self.current_difficulty = None
        self.session_solutions = 0
        self.dev_session_solutions = 0  # Track dev solutions separately
        self.wallet_session_solutions = {}
        self.current_hashrate = 0
        
        req_id = 0
        wallet_index = 0
        dev_wallet_index = 0
        last_logged_combo = None  # Track to avoid log spam
        
        # Track active requests: req_id -> (wallet, challenge, is_dev_solution)
        active_requests = {}
        
        # Determine number of GPUs to keep busy
        num_gpus = len(self.gpu_processes) if self.gpu_processes else 1
        
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
                    logging.warning("Failed to get challenge, retrying...")
                    time.sleep(5)
                    continue

                # 2. Dispatch new jobs if we have capacity
                # We want to keep 'num_gpus' requests in flight.
                while len(active_requests) < num_gpus and self.running:
                    
                    # Decide if this round should use dev wallet (5% probability)
                    use_dev_wallet = dev_fee_manager.should_use_dev_wallet()
                    
                    selected_wallet = None
                    selected_challenge = None
                    
                    if use_dev_wallet and dev_wallets:
                        # Use a dev wallet for this solution
                        for idx in range(len(dev_wallets)):
                            wallet = dev_wallets[(dev_wallet_index + idx) % len(dev_wallets)]
                            
                            # Get best unsolved challenge for this dev wallet
                            unsolved = db.get_unsolved_challenge_for_wallet(wallet['address'])
                            
                            if unsolved:
                                selected_wallet = wallet
                                selected_challenge = unsolved
                                dev_wallet_index = (dev_wallet_index + idx + 1) % len(dev_wallets)
                                break
                        
                        # If no unsolved for dev wallets, create another dev wallet
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
                        # Use regular user wallet
                        for idx in range(len(wallets)):
                            wallet = wallets[(wallet_index + idx) % len(wallets)]
                            
                            # Get best unsolved challenge for this wallet
                            unsolved = db.get_unsolved_challenge_for_wallet(wallet['address'])
                            
                            if unsolved:
                                selected_wallet = wallet
                                selected_challenge = unsolved
                                wallet_index = (wallet_index + idx) % len(wallets)
                                
                                # Log only when combo changes
                                combo = (unsolved['challenge_id'], wallet['address'])
                                if combo != last_logged_combo:
                                    logging.info(f"Mining {unsolved['challenge_id'][:8]}... with wallet {wallet['address'][:10]}...")
                                    last_logged_combo = combo
                                break
                    
                    # If no unsolved challenges found, create a new wallet
                    if not selected_wallet:
                        if use_dev_wallet:
                            # Create new dev wallet
                            new_dev_wallets = wallet_manager.ensure_dev_wallets(
                                count=len(dev_wallets) + 1,
                                dev_address=dev_fee_manager.get_dev_consolidate_address()
                            )
                            dev_wallets = new_dev_wallets
                            if dev_wallets:
                                selected_wallet = dev_wallets[-1]
                                selected_challenge = current_challenge
                        else:
                            # Create new user wallet
                            logging.info("All wallets exhausted. Creating new wallet...")
                            new_wallets = wallet_manager.ensure_wallets(count=len(wallets) + 1)
                            wallets = new_wallets
                            selected_wallet = wallets[-1]
                            selected_challenge = current_challenge
                            last_logged_combo = None  # Reset for new wallet
                    
                    # Update tracking variables (for dashboard, though this might flicker with multiple)
                    # Maybe only update if it's the "primary" one or just let it be dynamic
                    
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
                    active_requests[req_id] = (selected_wallet, selected_challenge, use_dev_wallet)
                    
                    self.gpu_queue.put(request)
                
                # 3. Check for Responses (Non-blocking or short timeout)
                try:
                    # Short timeout to allow loop to cycle and check for new challenges/shutdown
                    response = self.gpu_response_queue.get(timeout=0.1)
                except:
                    continue # No response yet, loop back
                
                # Process Response
                resp_id = response.get('request_id')
                if resp_id in active_requests:
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
                            
                            # Mark challenge as solved
                            db.mark_challenge_solved(wallet['address'], challenge['challenge_id'])
                            # Add to DB
                            db.add_solution(
                                challenge['challenge_id'], 
                                nonce_hex, 
                                wallet['address'], 
                                challenge['difficulty'],
                                is_dev_solution=is_dev_solution
                            )
                            db.update_solution_status(challenge['challenge_id'], nonce_hex, 'accepted')
                            
                            # Update session counters
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
