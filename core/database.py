import logging
import threading
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

class Database:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Database, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self.lock = threading.Lock()
        
        # In-memory storage
        self.solutions = []
        self.solved_challenges = {} # wallet -> set(challenge_ids)
        self.challenges = []
        self.wallets = [] # Legacy support (mostly unused now)
        
        # Failed solutions persistence
        self.failed_solutions_file = Path("failed_solutions.json")
        self.failed_solutions = []
        self._load_failed_solutions()

    def _load_failed_solutions(self):
        if not self.failed_solutions_file.exists():
            return
            
        try:
            with open(self.failed_solutions_file, 'r') as f:
                data = json.load(f)
                # Prune old entries (> 24 hours)
                cutoff = datetime.now() - timedelta(hours=24)
                self.failed_solutions = [
                    s for s in data 
                    if datetime.fromisoformat(s.get('timestamp', datetime.now().isoformat())) > cutoff
                ]
                logging.info(f"Loaded {len(self.failed_solutions)} pending failed solutions")
        except Exception as e:
            logging.error(f"Error loading failed solutions: {e}")
            self.failed_solutions = []

    def _save_failed_solutions(self):
        try:
            with open(self.failed_solutions_file, 'w') as f:
                json.dump(self.failed_solutions, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving failed solutions: {e}")

    def add_wallet(self, wallet_data, is_dev_wallet=False):
        with self.lock:
            # Avoid duplicates
            for w in self.wallets:
                if w['address'] == wallet_data['address']:
                    return False
            
            # Store flag
            wallet_data['is_dev_wallet'] = is_dev_wallet
            self.wallets.append(wallet_data)
            return True

    def get_wallets(self, include_dev=False):
        with self.lock:
            if include_dev:
                return self.wallets
            return [w for w in self.wallets if not w.get('is_dev_wallet')]

    def get_dev_wallets(self):
        with self.lock:
            return [w for w in self.wallets if w.get('is_dev_wallet')]

    def mark_wallet_consolidated(self, wallet_address):
        with self.lock:
            for w in self.wallets:
                if w['address'] == wallet_address:
                    w['is_consolidated'] = True
                    break

    def add_solution(self, challenge_id, nonce, wallet_address, difficulty, is_dev_solution=False):
        with self.lock:
            solution = {
                'challenge_id': challenge_id,
                'nonce': nonce,
                'wallet_address': wallet_address,
                'difficulty': difficulty,
                'is_dev_solution': is_dev_solution,
                'timestamp': datetime.now().isoformat(),
                'status': 'submitted'
            }
            self.solutions.append(solution)
            # Keep memory usage in check? Maybe limit history?
            if len(self.solutions) > 10000:
                self.solutions = self.solutions[-5000:]

    def update_solution_status(self, challenge_id, nonce, status):
        with self.lock:
            for sol in reversed(self.solutions):
                if sol['challenge_id'] == challenge_id and sol['nonce'] == nonce:
                    sol['status'] = status
                    break

    def mark_challenge_solved(self, wallet_address, challenge_id):
        with self.lock:
            if wallet_address not in self.solved_challenges:
                self.solved_challenges[wallet_address] = set()
            self.solved_challenges[wallet_address].add(challenge_id)

    def is_challenge_solved(self, wallet_address, challenge_id):
        with self.lock:
            if wallet_address not in self.solved_challenges:
                return False
            return challenge_id in self.solved_challenges[wallet_address]

    def get_total_solutions(self):
        with self.lock:
            return len(self.solutions)

    def register_challenge(self, challenge):
        with self.lock:
            # Store unique challenges
            for c in self.challenges:
                if c['challenge_id'] == challenge['challenge_id']:
                    return
            self.challenges.append(challenge)
            # Limit size
            if len(self.challenges) > 100:
                self.challenges = self.challenges[-50:]

    def get_unsolved_challenge_for_wallet(self, wallet_address):
        with self.lock:
            # Return the latest challenge if not solved by this wallet
            if not self.challenges:
                return None
            
            latest = self.challenges[-1]
            if self.is_challenge_solved(wallet_address, latest['challenge_id']):
                return None
            return latest

    # --- Failed Solutions Management ---

    def add_failed_solution(self, wallet_address, challenge_id, nonce, difficulty, is_dev_solution):
        with self.lock:
            # Check if already exists
            for s in self.failed_solutions:
                if s['challenge_id'] == challenge_id and s['nonce'] == nonce:
                    return

            entry = {
                'wallet_address': wallet_address,
                'challenge_id': challenge_id,
                'nonce': nonce,
                'difficulty': difficulty,
                'is_dev_solution': is_dev_solution,
                'timestamp': datetime.now().isoformat(),
                'retry_count': 0,
                'last_retry': None
            }
            self.failed_solutions.append(entry)
            self._save_failed_solutions()
            logging.info(f"Persisted failed solution for retry: {challenge_id[:8]}...")

    def get_pending_retries(self):
        """Get solutions that are due for retry (e.g. every hour)."""
        with self.lock:
            now = datetime.now()
            due = []
            for s in self.failed_solutions:
                last_retry = s.get('last_retry')
                if last_retry:
                    last_retry_dt = datetime.fromisoformat(last_retry)
                    if now - last_retry_dt < timedelta(hours=1):
                        continue
                due.append(s)
            return due

    def update_retry_status(self, challenge_id, nonce, success):
        with self.lock:
            if success:
                # Remove from failed solutions
                self.failed_solutions = [
                    s for s in self.failed_solutions 
                    if not (s['challenge_id'] == challenge_id and s['nonce'] == nonce)
                ]
            else:
                # Update retry timestamp
                for s in self.failed_solutions:
                    if s['challenge_id'] == challenge_id and s['nonce'] == nonce:
                        s['last_retry'] = datetime.now().isoformat()
                        s['retry_count'] = s.get('retry_count', 0) + 1
                        break
            self._save_failed_solutions()

# Global instance
db = Database()
