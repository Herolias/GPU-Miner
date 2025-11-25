import logging
import threading
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set, Any

from .constants import (
    MAX_IN_MEMORY_SOLUTIONS,
    TRIM_SOLUTIONS_TO,
    MAX_IN_MEMORY_CHALLENGES,
    TRIM_CHALLENGES_TO,
    SOLUTION_RETRY_EXPIRY_HOURS,
    SOLUTION_RETRY_INTERVAL_HOURS
)
from .types import Solution, Challenge, FailedSolution, WalletOptional
from .exceptions import DatabaseError


class Database:
    """
    In-memory database for tracking mining state.
    
    Implements singleton pattern with thread-safe operations. Stores solutions,
    challenges, and wallet information in memory with automatic size limits.
    Failed solutions are persisted to disk for retry across restarts.
    
    Thread Safety:
        All public methods are thread-safe using a global lock.
    """
    
    _instance: Optional['Database'] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> 'Database':
        """Create or return singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Database, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize database with in-memory storage and load persisted data."""
        if self._initialized:
            return
            
        self._initialized: bool = True
        self.lock: threading.Lock = threading.Lock()
        
        # In-memory storage
        self.solutions: List[Solution] = []
        self.solved_challenges: Dict[str, Set[str]] = {}  # wallet -> set(challenge_ids)
        self.challenges: List[Challenge] = []
        self.wallets: List[WalletOptional] = []  # Legacy support (mostly unused now)
        
        # Failed solutions persistence
        self.failed_solutions_file: Path = Path("failed_solutions.json")
        self.failed_solutions: List[FailedSolution] = []
        self._load_failed_solutions()

    def _load_failed_solutions(self) -> None:
        """
        Load failed solutions from disk and prune expired entries.
        
        Loads solutions from failed_solutions.json and removes any that are
        older than SOLUTION_RETRY_EXPIRY_HOURS.
        """
        if not self.failed_solutions_file.exists():
            return
            
        try:
            with open(self.failed_solutions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Prune old entries
                cutoff = datetime.now() - timedelta(hours=SOLUTION_RETRY_EXPIRY_HOURS)
                self.failed_solutions = [
                    s for s in data 
                    if datetime.fromisoformat(s.get('timestamp', datetime.now().isoformat())) > cutoff
                ]
                logging.info(f"Loaded {len(self.failed_solutions)} pending failed solutions")
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON in failed solutions file: {e}")
            self.failed_solutions = []
        except Exception as e:
            logging.error(f"Error loading failed solutions: {e}")
            self.failed_solutions = []

    def _save_failed_solutions(self) -> None:
        """Save failed solutions to disk for persistence across restarts."""
        try:
            with open(self.failed_solutions_file, 'w', encoding='utf-8') as f:
                json.dump(self.failed_solutions, f, indent=2)
        except Exception as e:
            raise DatabaseError(f"Failed to save failed solutions: {e}")

    def add_wallet(self, wallet_data: WalletOptional, is_dev_wallet: bool = False) -> bool:
        """
        Add a wallet to the database.
        
        Args:
            wallet_data: Wallet information dict
            is_dev_wallet: Whether this is a dev wallet
            
        Returns:
            True if wallet was added, False if it already exists
        """
        with self.lock:
            # Avoid duplicates
            address = wallet_data.get('address', '')
            for w in self.wallets:
                if w.get('address') == address:
                    return False
            
            # Store flag
            wallet_data['is_dev_wallet'] = is_dev_wallet
            self.wallets.append(wallet_data)
            return True

    def get_wallets(self, include_dev: bool = False) -> List[WalletOptional]:
        """
        Get all wallets, optionally including dev wallets.
        
        Args:
            include_dev: If True, include dev wallets in results
            
        Returns:
            List of wallet dicts
        """
        with self.lock:
            if include_dev:
                return self.wallets.copy()
            return [w for w in self.wallets if not w.get('is_dev_wallet')]

    def get_dev_wallets(self) -> List[WalletOptional]:
        """
        Get all dev wallets.
        
        Returns:
            List of dev wallet dicts
        """
        with self.lock:
            return [w for w in self.wallets if w.get('is_dev_wallet')]

    def mark_wallet_consolidated(self, wallet_address: str) -> None:
        """
        Mark a wallet as consolidated.
        
        Args:
            wallet_address: Address of wallet to mark
        """
        with self.lock:
            for w in self.wallets:
                if w.get('address') == wallet_address:
                    w['is_consolidated'] = True
                    break

    def add_solution(
        self,
        challenge_id: str,
        nonce: str,
        wallet_address: str,
        difficulty: str,
        is_dev_solution: bool = False
    ) -> None:
        """
        Add a solution to the database.
        
        Automatically trims solution history when limit is reached.
        
        Args:
            challenge_id: Challenge identifier
            nonce: Solution nonce
            wallet_address: Wallet that found the solution
            difficulty: Challenge difficulty
            is_dev_solution: Whether this is a dev solution
        """
        with self.lock:
            solution: Solution = {
                'challenge_id': challenge_id,
                'nonce': nonce,
                'wallet_address': wallet_address,
                'difficulty': difficulty,
                'is_dev_solution': is_dev_solution,
                'timestamp': datetime.now().isoformat(),
                'status': 'submitted'
            }
            self.solutions.append(solution)
            
            # Keep memory usage in check
            if len(self.solutions) > MAX_IN_MEMORY_SOLUTIONS:
                self.solutions = self.solutions[-TRIM_SOLUTIONS_TO:]
                logging.debug(f"Trimmed solutions to {TRIM_SOLUTIONS_TO} entries")

    def update_solution_status(self, challenge_id: str, nonce: str, status: str) -> None:
        """
        Update the status of a solution.
        
        Args:
            challenge_id: Challenge identifier
            nonce: Solution nonce
            status: New status ('submitted', 'accepted', 'rejected', etc.)
        """
        with self.lock:
            for sol in reversed(self.solutions):
                if sol['challenge_id'] == challenge_id and sol['nonce'] == nonce:
                    sol['status'] = status  # type: ignore
                    break

    def mark_challenge_solved(self, wallet_address: str, challenge_id: str) -> None:
        """
        Mark a challenge as solved by a wallet.
        
        Args:
            wallet_address: Wallet that solved the challenge
            challenge_id: Challenge identifier
        """
        with self.lock:
            if wallet_address not in self.solved_challenges:
                self.solved_challenges[wallet_address] = set()
            self.solved_challenges[wallet_address].add(challenge_id)

    def is_challenge_solved(self, wallet_address: str, challenge_id: str) -> bool:
        """
        Check if a wallet has solved a challenge.
        
        Args:
            wallet_address: Wallet to check
            challenge_id: Challenge to check
            
        Returns:
            True if wallet has solved this challenge
        """
        with self.lock:
            if wallet_address not in self.solved_challenges:
                return False
            return challenge_id in self.solved_challenges[wallet_address]

    def get_total_solutions(self) -> int:
        """
        Get total number of solutions in memory.
        
        Returns:
            Count of solutions
        """
        with self.lock:
            return len(self.solutions)

    def register_challenge(self, challenge: Challenge) -> None:
        """
        Register a new challenge.
        
        Automatically trims challenge history when limit is reached.
        Avoids duplicate challenges.
        
        Args:
            challenge: Challenge data dict
        """
        with self.lock:
            # Store unique challenges
            for c in self.challenges:
                if c['challenge_id'] == challenge['challenge_id']:
                    return
                    
            self.challenges.append(challenge)
            
            # Limit size
            if len(self.challenges) > MAX_IN_MEMORY_CHALLENGES:
                self.challenges = self.challenges[-TRIM_CHALLENGES_TO:]
                logging.debug(f"Trimmed challenges to {TRIM_CHALLENGES_TO} entries")

    def get_unsolved_challenge_for_wallet(self, wallet_address: str) -> Optional[Challenge]:
        """
        Get the latest unsolved challenge for a wallet.
        
        Args:
            wallet_address: Wallet to check
            
        Returns:
            Latest challenge if unsolved, None otherwise
        """
        with self.lock:
            # Return the latest challenge if not solved by this wallet
            if not self.challenges:
                return None
            
            latest = self.challenges[-1]
            if self.is_challenge_solved(wallet_address, latest['challenge_id']):
                return None
            return latest

    # --- Failed Solutions Management ---

    def add_failed_solution(
        self,
        wallet_address: str,
        challenge_id: str,
        nonce: str,
        difficulty: str,
        is_dev_solution: bool
    ) -> None:
        """
        Add a failed solution to persistent retry queue.
        
        Args:
            wallet_address: Wallet that submitted the solution
            challenge_id: Challenge identifier
            nonce: Solution nonce
            difficulty: Challenge difficulty
            is_dev_solution: Whether this is a dev solution
        """
        with self.lock:
            # Check if already exists
            for s in self.failed_solutions:
                if s['challenge_id'] == challenge_id and s['nonce'] == nonce:
                    return

            entry: FailedSolution = {
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

    def get_pending_retries(self) -> List[FailedSolution]:
        """
        Get solutions that are due for retry.
        
        Returns solutions that either haven't been retried yet, or where
        enough time has passed since the last retry (SOLUTION_RETRY_INTERVAL_HOURS).
        
        Returns:
            List of failed solutions ready for retry
        """
        with self.lock:
            now = datetime.now()
            due: List[FailedSolution] = []
            
            for s in self.failed_solutions:
                last_retry = s.get('last_retry')
                if last_retry:
                    last_retry_dt = datetime.fromisoformat(last_retry)
                    if now - last_retry_dt < timedelta(hours=SOLUTION_RETRY_INTERVAL_HOURS):
                        continue
                due.append(s)
            return due

    def update_retry_status(self, challenge_id: str, nonce: str, success: bool) -> None:
        """
        Update retry status for a failed solution.
        
        Args:
            challenge_id: Challenge identifier
            nonce: Solution nonce
            success: True if retry succeeded, False otherwise
        """
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
