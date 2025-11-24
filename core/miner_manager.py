import threading
import time
import logging
import multiprocessing as mp
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
        self.gpu_process = None
        self.gpu_ready_event = None
        self.gpu_ready_flag = None
        self.workers = []

    def start(self):
        self.running = True
        logging.info("Starting Miner Manager...")
        
        # Start Dashboard Thread early so loading screen can show
        self.dashboard_thread = threading.Thread(target=self._update_dashboard_loop)
        self.dashboard_thread.start()

        gpu_enabled = config.get("gpu.enabled")
        supports_loading = False

        # Start GPU Engine
        if gpu_enabled:
            self.gpu_ready_event = mp.Event()
            self.gpu_ready_flag = mp.Value('i', 0)
            self.gpu_process = GPUEngine(self.gpu_queue, self.gpu_response_queue)

            if hasattr(self.gpu_process, "set_ready_notifier"):
                self.gpu_process.set_ready_notifier(self.gpu_ready_event, self.gpu_ready_flag)
                supports_loading = True
                dashboard.set_loading("Building CUDA kernels...")

            self.gpu_process.start()
            logging.info("GPU Engine process started")

            if supports_loading:
                if self._wait_for_gpu_ready():
                    logging.info("GPU kernels built successfully")
                else:
                    logging.error("GPU initialization failed or timed out")
                dashboard.set_loading(None)

        self.manager_thread = threading.Thread(target=self._manage_mining)
        self.manager_thread.start()

    def stop(self):
        self.running = False
        logging.info("Stopping Miner Manager...")
        
        if self.gpu_process and self.gpu_process.is_alive():
            # Send shutdown request
            try:
                self.gpu_queue.put({'type': 'shutdown'}, timeout=1)
            except:
                pass
            
            # Wait up to 3 seconds for clean shutdown
            self.gpu_process.join(timeout=3)
            
            # Force terminate if still running
            if self.gpu_process.is_alive():
                logging.warning("GPU process didn't stop cleanly, terminating...")
                self.gpu_process.terminate()
                self.gpu_process.join(timeout=1)
                
                # Kill if still alive
                if self.gpu_process.is_alive():
                    self.gpu_process.kill()
                    self.gpu_process.join()
        
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
        if not self.gpu_ready_event:
            return True

        if not self.gpu_ready_event.wait(timeout):
            logging.error("Timeout while waiting for GPU kernels to build")
            return False

        status = self.gpu_ready_flag.value if self.gpu_ready_flag is not None else 1
        if status == 1:
            return True

        logging.error("GPU engine reported a failure during initialization")
        return False

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
        
        while self.running:
            try:
                # 1. Fetch and Register Current Challenge
                current_challenge = api.get_current_challenge()
                
                if not current_challenge:
                    logging.warning("Failed to get challenge, retrying...")
                    time.sleep(5)
                    continue
                
                # Register the challenge in DB (so we track all challenges we've seen)
                db.register_challenge(current_challenge)
                
                # 2. Find best unsolved challenge for each wallet
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
                            # Need to add no_pre_mine_hour from current challenge
                            if current_challenge['challenge_id'] == unsolved['challenge_id']:
                                selected_challenge['no_pre_mine_hour'] = current_challenge.get('no_pre_mine_hour', '')
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
                            # Need to add no_pre_mine_hour from current challenge
                            if current_challenge['challenge_id'] == unsolved['challenge_id']:
                                selected_challenge['no_pre_mine_hour'] = current_challenge.get('no_pre_mine_hour', '')
                            
                            # Log only when combo changes
                            combo = (unsolved['challenge_id'], wallet['address'])
                            if combo != last_logged_combo:
                                logging.info(f"Mining {unsolved['challenge_id'][:8]}... with wallet {wallet['address'][:10]}...")
                                last_logged_combo = combo
                            break
                
                # 3. If no unsolved challenges found, create a new wallet
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
                
                # 4. Update tracking variables
                self.current_challenge_id = selected_challenge['challenge_id']
                self.current_difficulty = selected_challenge['difficulty']
                
                # Only track user wallet solutions in dashboard
                if not use_dev_wallet:
                    if selected_wallet['address'] not in self.wallet_session_solutions:
                        self.wallet_session_solutions[selected_wallet['address']] = 0
                
                # 5. Build Salt Prefix
                salt_prefix_str = (
                    selected_wallet['address'] + 
                    selected_challenge['challenge_id'] +
                    selected_challenge['difficulty'] + 
                    selected_challenge['no_pre_mine'] +
                    selected_challenge.get('latest_submission', '') + 
                    selected_challenge.get('no_pre_mine_hour', '')
                )
                salt_prefix = salt_prefix_str.encode('utf-8')
                
                # 6. Dispatch to GPU
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
                
                self.gpu_queue.put(request)
                
                # 7. Wait for Response (with timeout to allow Ctrl+C)
                while self.running:
                    try:
                        response = self.gpu_response_queue.get(timeout=1.0)
                        break
                    except:
                        continue
                
                if not self.running:
                    break
                
                if response.get('error'):
                    logging.error(f"GPU Error: {response['error']}")
                    time.sleep(1)
                elif response.get('found'):
                    nonce_hex = f"{response['nonce']:016x}"
                    
                    # Determine if this is a dev solution
                    is_dev_solution = use_dev_wallet
                    
                    if not is_dev_solution:
                        # Only log user solutions
                        logging.info(f"SOLUTION FOUND! Nonce: {response['nonce']}")
                    
                    success, is_fatal = api.submit_solution(selected_wallet['address'], self.current_challenge_id, nonce_hex)
                    if success:
                        if not is_dev_solution:
                            logging.info("Solution Submitted Successfully!")
                        
                        # Mark challenge as solved
                        db.mark_challenge_solved(selected_wallet['address'], self.current_challenge_id)
                        # Add to DB
                        db.add_solution(
                            self.current_challenge_id, 
                            nonce_hex, 
                            selected_wallet['address'], 
                            self.current_difficulty,
                            is_dev_solution=is_dev_solution
                        )
                        db.update_solution_status(self.current_challenge_id, nonce_hex, 'accepted')
                        
                        # Update session counters (only count user solutions in dashboard)
                        if is_dev_solution:
                            self.dev_session_solutions += 1
                        else:
                            self.session_solutions += 1
                            self.wallet_session_solutions[selected_wallet['address']] += 1
                    else:
                        if is_fatal:
                            logging.error(f"Fatal error submitting solution (Rejected). Marking as solved to prevent retry.")
                            # Mark challenge as solved so we don't pick it up again
                            db.mark_challenge_solved(selected_wallet['address'], self.current_challenge_id)
                            # Add to DB as rejected
                            db.add_solution(
                                self.current_challenge_id, 
                                nonce_hex, 
                                selected_wallet['address'], 
                                self.current_difficulty,
                                is_dev_solution=is_dev_solution
                            )
                            db.update_solution_status(self.current_challenge_id, nonce_hex, 'rejected')

                        if not is_dev_solution:
                            logging.error("Solution Submission Failed")
                else:
                    # Not found, continue
                    pass

                # Update hashrate estimate
                if response.get('hashes') and response.get('duration'):
                    hashes = response['hashes']
                    duration = response['duration']
                    if duration > 0:
                        instant_hashrate = hashes / duration
                        if self.current_hashrate == 0:
                            self.current_hashrate = instant_hashrate
                        else:
                            self.current_hashrate = (0.9 * self.current_hashrate) + (0.1 * instant_hashrate)
                    
            except Exception as e:
                logging.error(f"Mining loop error: {e}")
                time.sleep(5)

# Global instance
miner_manager = MinerManager()
