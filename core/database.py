import sqlite3
import threading
import logging
import json
from datetime import datetime, timezone

class Database:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path="miner_state.db"):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Database, cls).__new__(cls)
                    cls._instance.db_path = db_path
                    cls._instance.local = threading.local()
                    cls._instance._init_db()
        return cls._instance

    def _get_conn(self):
        """Get thread-local connection"""
        if not hasattr(self.local, 'conn'):
            self.local.conn = sqlite3.connect(self.db_path)
            self.local.conn.row_factory = sqlite3.Row
        return self.local.conn

    def _init_db(self):
        """Initialize database schema"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Wallets Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wallets (
                    address TEXT PRIMARY KEY,
                    pubkey TEXT,
                    signing_key TEXT,
                    signature TEXT,
                    created_at TIMESTAMP,
                    is_consolidated BOOLEAN DEFAULT 0,
                    balance_approx REAL DEFAULT 0,
                    is_dev_wallet BOOLEAN DEFAULT 0
                )
            ''')

            # Solutions Table (Found nonces)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS solutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    challenge_id TEXT,
                    nonce TEXT,
                    address TEXT,
                    difficulty TEXT,
                    found_at TIMESTAMP,
                    status TEXT DEFAULT 'pending', -- pending, accepted, rejected
                    is_dev_solution BOOLEAN DEFAULT 0,
                    FOREIGN KEY(address) REFERENCES wallets(address)
                )
            ''')

            # Challenges Table (Track seen challenges)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS challenges (
                    challenge_id TEXT PRIMARY KEY,
                    difficulty TEXT,
                    no_pre_mine TEXT,
                    no_pre_mine_hour TEXT,
                    latest_submission TIMESTAMP,
                    first_seen_at TIMESTAMP
                )
            ''')
            
            # Wallet-Challenge tracking (prevent duplicate work)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wallet_challenges (
                    wallet_address TEXT,
                    challenge_id TEXT,
                    solved_at TIMESTAMP,
                    PRIMARY KEY (wallet_address, challenge_id),
                    FOREIGN KEY(wallet_address) REFERENCES wallets(address),
                    FOREIGN KEY(challenge_id) REFERENCES challenges(challenge_id)
                )
            ''')
            
            # Migrate existing tables to add new columns if they don't exist
            try:
                cursor.execute('ALTER TABLE wallets ADD COLUMN is_dev_wallet BOOLEAN DEFAULT 0')
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            try:
                cursor.execute('ALTER TABLE solutions ADD COLUMN is_dev_solution BOOLEAN DEFAULT 0')
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute('ALTER TABLE challenges ADD COLUMN no_pre_mine_hour TEXT')
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            conn.commit()
            conn.close()
            logging.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logging.critical(f"Failed to initialize database: {e}")
            raise

    def add_wallet(self, wallet_data, is_dev_wallet=False):
        conn = self._get_conn()
        try:
            conn.execute('''
                INSERT OR IGNORE INTO wallets (address, pubkey, signing_key, signature, created_at, is_dev_wallet)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                wallet_data['address'],
                wallet_data['pubkey'],
                wallet_data['signing_key'],
                wallet_data['signature'],
                wallet_data.get('created_at', datetime.now().isoformat()),
                1 if is_dev_wallet else 0
            ))
            conn.commit()
            return True
        except Exception as e:
            logging.error(f"DB Error adding wallet: {e}")
            return False

    def get_wallets(self, include_dev=False):
        """Get wallets. By default, excludes dev wallets from the list."""
        conn = self._get_conn()
        if include_dev:
            cursor = conn.execute('SELECT * FROM wallets')
        else:
            cursor = conn.execute('SELECT * FROM wallets WHERE is_dev_wallet = 0')
        return [dict(row) for row in cursor.fetchall()]
    
    def get_dev_wallets(self):
        """Get only dev wallets."""
        conn = self._get_conn()
        cursor = conn.execute('SELECT * FROM wallets WHERE is_dev_wallet = 1')
        return [dict(row) for row in cursor.fetchall()]

    def mark_wallet_consolidated(self, wallet_address):
        """Mark a wallet as consolidated."""
        conn = self._get_conn()
        try:
            conn.execute('''
                UPDATE wallets SET is_consolidated = 1 WHERE address = ?
            ''', (wallet_address,))
            conn.commit()
        except Exception as e:
            logging.error(f"DB Error marking wallet consolidated: {e}")

    def add_solution(self, challenge_id, nonce, address, difficulty, is_dev_solution=False):
        conn = self._get_conn()
        try:
            conn.execute('''
                INSERT INTO solutions (challenge_id, nonce, address, difficulty, found_at, is_dev_solution)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (challenge_id, nonce, address, difficulty, datetime.now().isoformat(), 1 if is_dev_solution else 0))
            conn.commit()
        except Exception as e:
            logging.error(f"DB Error adding solution: {e}")

    def update_solution_status(self, challenge_id, nonce, status):
        conn = self._get_conn()
        try:
            conn.execute('''
                UPDATE solutions SET status = ? WHERE challenge_id = ? AND nonce = ?
            ''', (status, challenge_id, nonce))
            conn.commit()
        except Exception as e:
            logging.error(f"DB Error updating solution: {e}")

    def get_total_solutions(self, include_dev=False):
        """Get total number of accepted solutions. By default, excludes dev solutions."""
        conn = self._get_conn()
        try:
            if include_dev:
                cursor = conn.execute("SELECT COUNT(*) FROM solutions WHERE status = 'accepted'")
            else:
                cursor = conn.execute("SELECT COUNT(*) FROM solutions WHERE status = 'accepted' AND is_dev_solution = 0")
            return cursor.fetchone()[0]
        except Exception as e:
            logging.error(f"DB Error counting solutions: {e}")
            return 0

    def mark_challenge_solved(self, wallet_address, challenge_id):
        """Mark a challenge as solved by a wallet."""
        conn = self._get_conn()
        try:
            conn.execute('''
                INSERT OR IGNORE INTO wallet_challenges (wallet_address, challenge_id, solved_at)
                VALUES (?, ?, ?)
            ''', (wallet_address, challenge_id, datetime.now().isoformat()))
            conn.commit()
        except Exception as e:
            logging.error(f"DB Error marking challenge solved: {e}")

    def is_challenge_solved(self, wallet_address, challenge_id):
        """Check if a wallet has already solved a challenge."""
        conn = self._get_conn()
        try:
            cursor = conn.execute('''
                SELECT 1 FROM wallet_challenges 
                WHERE wallet_address = ? AND challenge_id = ?
            ''', (wallet_address, challenge_id))
            return cursor.fetchone() is not None
        except Exception as e:
            logging.error(f"DB Error checking challenge: {e}")
            return False

    def get_unsolved_challenges_for_wallet(self, wallet_address, all_challenge_ids):
        """Get list of unsolved challenges for a wallet from a given set."""
        conn = self._get_conn()
        try:
            if not all_challenge_ids:
                return []
            placeholders = ','.join('?' * len(all_challenge_ids))
            cursor = conn.execute(f'''
                SELECT challenge_id FROM 
                ({' UNION ALL '.join(['SELECT ? AS challenge_id'] * len(all_challenge_ids))})
                WHERE challenge_id NOT IN (
                    SELECT challenge_id FROM wallet_challenges WHERE wallet_address = ?
                )
            ''', (*all_challenge_ids, wallet_address))
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logging.error(f"DB Error getting unsolved challenges: {e}")
            return all_challenge_ids  # Return all on error

    def register_challenge(self, challenge):
        """Register a challenge in the database."""
        conn = self._get_conn()
        try:
            conn.execute('''
                INSERT OR REPLACE INTO challenges 
                (challenge_id, difficulty, no_pre_mine, no_pre_mine_hour, latest_submission, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                challenge['challenge_id'],
                challenge['difficulty'],
                challenge['no_pre_mine'],
                challenge.get('no_pre_mine_hour', ''),
                challenge.get('latest_submission'),
                datetime.now().isoformat()
            ))
            conn.commit()
        except Exception as e:
            logging.error(f"DB Error registering challenge: {e}")

    def get_unsolved_challenge_for_wallet(self, wallet_address):
        """
        Get the best challenge for a wallet:
        - Not solved by this wallet
        - >120s remaining until latest_submission
        - Easiest (lowest difficulty value) first
        """
        conn = self._get_conn()
        try:
            now = datetime.now(timezone.utc)
            cursor = conn.execute('''
                SELECT challenge_id, difficulty, no_pre_mine, no_pre_mine_hour, latest_submission
                FROM challenges
                WHERE challenge_id NOT IN (
                    SELECT challenge_id FROM wallet_challenges WHERE wallet_address = ?
                )
            ''', (wallet_address,))
            
            best = None
            best_diff = None
            best_deadline = None
            
            for row in cursor.fetchall():
                challenge_id, difficulty, no_pre_mine, no_pre_mine_hour, latest_submission = row
                
                # Parse deadline
                if not latest_submission:
                    continue
                try:
                    deadline = datetime.fromisoformat(latest_submission.replace('Z', '+00:00'))
                except:
                    continue
                
                # Check time left
                time_left = (deadline - now).total_seconds()
                if time_left <= 120:
                    continue
                
                # Parse difficulty
                try:
                    difficulty_val = int(difficulty[:8], 16)
                except:
                    continue
                
                # Select easiest
                if best is None or difficulty_val < best_diff:
                    best = {
                        'challenge_id': challenge_id,
                        'difficulty': difficulty,
                        'no_pre_mine': no_pre_mine,
                        'latest_submission': latest_submission,
                        'no_pre_mine_hour': no_pre_mine_hour if no_pre_mine_hour else ''
                    }
                    best_diff = difficulty_val
                    best_deadline = deadline
                elif difficulty_val == best_diff and deadline < best_deadline:
                    best = {
                        'challenge_id': challenge_id,
                        'difficulty': difficulty,
                        'no_pre_mine': no_pre_mine,
                        'latest_submission': latest_submission,
                        'no_pre_mine_hour': no_pre_mine_hour if no_pre_mine_hour else ''
                    }
                    best_deadline = deadline
            
            return best
        except Exception as e:
            logging.error(f"DB Error getting unsolved challenge: {e}")
            return None

    def close(self):
        if hasattr(self.local, 'conn'):
            self.local.conn.close()
            del self.local.conn

db = Database()
