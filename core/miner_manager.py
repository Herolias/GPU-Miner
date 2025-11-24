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

class MinerManager:
    def __init__(self):
        self.running = False
        self.gpu_queue = mp.Queue()
        self.gpu_response_queue = mp.Queue()
        self.gpu_process = None
        self.workers = []

    def start(self):
        self.running = True
        logging.info("Starting Miner Manager...")
        
        # Start GPU Engine
        if config.get("gpu.enabled"):
            self.gpu_process = GPUEngine(self.gpu_queue, self.gpu_response_queue)
            self.gpu_process.start()
            logging.info("GPU Engine process started")

        self.manager_thread = threading.Thread(target=self._manage_mining)
        self.manager_thread.start()
        
        # Start Dashboard Thread
        self.dashboard_thread = threading.Thread(target=self._update_dashboard_loop)
        self.dashboard_thread.start()

    def stop(self):
        self.running = False
        if self.gpu_process:
            self.gpu_queue.put({'type': 'shutdown'})
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

    def _manage_mining(self):
        # Ensure wallets exist
        max_workers = config.get("miner.max_workers", 1)
        # Start with 5 wallets
        wallets = wallet_manager.ensure_wallets(count=5) 
        
        current_challenge = None
        self.current_challenge_id = None
        self.current_difficulty = None
        self.session_solutions = 0
        self.wallet_session_solutions = {}
        self.current_hashrate = 0
        
        req_id = 0
        wallet_index = 0
        
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
                selected_wallet = None
                selected_challenge = None
                
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
                        # Log once when we select a new challenge/wallet combo
                        logging.info(f"Mining {unsolved['challenge_id'][:8]}... with wallet {wallet['address'][:10]}...")
                        break
                
                # 3. If no unsolved challenges found, create a new wallet
                if not selected_wallet:
                    logging.info("All wallets exhausted. Creating new wallet...")
                    new_wallets = wallet_manager.ensure_wallets(count=len(wallets) + 1)
                    wallets = new_wallets
                    selected_wallet = wallets[-1]
                    selected_challenge = current_challenge
                
                # 4. Update tracking variables
                self.current_challenge_id = selected_challenge['challenge_id']
                self.current_difficulty = selected_challenge['difficulty']
                
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
                
                # 7. Wait for Response
                response = self.gpu_response_queue.get()
                
                if response.get('error'):
                    logging.error(f"GPU Error: {response['error']}")
                    time.sleep(1)
                elif response.get('found'):
                    logging.info(f"SOLUTION FOUND! Nonce: {response['nonce']}")
                    nonce_hex = f"{response['nonce']:016x}"
                    
                    if api.submit_solution(selected_wallet['address'], self.current_challenge_id, nonce_hex):
                        logging.info("Solution Submitted Successfully!")
                        # Mark challenge as solved
                        db.mark_challenge_solved(selected_wallet['address'], self.current_challenge_id)
                        # Add to DB
                        db.add_solution(self.current_challenge_id, nonce_hex, selected_wallet['address'], self.current_difficulty)
                        db.update_solution_status(self.current_challenge_id, nonce_hex, 'accepted')
                        
                        self.session_solutions += 1
                        self.wallet_session_solutions[selected_wallet['address']] += 1
                    else:
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
