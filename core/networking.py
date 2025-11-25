import requests
import time
import logging
import threading
import queue
from datetime import datetime, timedelta
from .config import config


class SolutionSubmissionQueue:
    """Background queue for non-blocking solution submission with retry logic."""
    
    def __init__(self, api_client):
        self.api_client = api_client
        self.queue = queue.Queue()
        self.running = False
        self.thread = None
        self.retry_hours = config.get("api.solution_retry_hours", 24)
        
    def start(self):
        """Start the background submission thread."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._process_queue, daemon=True)
        self.thread.start()
        logging.info("Solution submission queue started")
    
    def stop(self):
        """Stop the background submission thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logging.info("Solution submission queue stopped")
    
    def submit(self, wallet_address, challenge_id, nonce):
        """Add a solution to the submission queue."""
        submission = {
            'wallet_address': wallet_address,
            'challenge_id': challenge_id,
            'nonce': nonce,
            'created_at': datetime.now(),
            'attempts': 0
        }
        self.queue.put(submission)
        logging.debug(f"Solution queued: {challenge_id[:8]}... nonce={nonce}")
    
    def _process_queue(self):
        """Background thread that processes solution submissions with retry logic."""
        retry_queue = []
        
        while self.running:
            try:
                # Check for new submissions (non-blocking with timeout)
                try:
                    submission = self.queue.get(timeout=1)
                    retry_queue.append(submission)
                except queue.Empty:
                    pass
                
                # Process retry queue
                still_retrying = []
                for submission in retry_queue:
                    age = datetime.now() - submission['created_at']
                    
                    # Check if solution has expired (older than retry_hours)
                    if age > timedelta(hours=self.retry_hours):
                        logging.warning(
                            f"Solution expired after {self.retry_hours}h, discarding: "
                            f"{submission['challenge_id'][:8]}... nonce={submission['nonce']}"
                        )
                        continue
                    
                    # Attempt submission
                    submission['attempts'] += 1
                    success, is_fatal = self.api_client._submit_solution_direct(
                        submission['wallet_address'],
                        submission['challenge_id'],
                        submission['nonce']
                    )
                    
                    if success:
                        logging.info(
                            f"Solution submitted successfully (attempt {submission['attempts']}): "
                            f"{submission['challenge_id'][:8]}... nonce={submission['nonce']}"
                        )
                    elif is_fatal:
                        logging.error(
                            f"Solution rejected (fatal): {submission['challenge_id'][:8]}... "
                            f"nonce={submission['nonce']}"
                        )
                    else:
                        # Transient error, retry later with fixed 5-minute interval
                        retry_delay = 300  # 5 minutes
                        logging.debug(
                            f"Solution submission failed (attempt {submission['attempts']}), "
                            f"will retry in {retry_delay}s"
                        )
                        # Add wait time to creation time to delay next attempt
                        submission['created_at'] = datetime.now() - age + timedelta(seconds=retry_delay)
                        still_retrying.append(submission)
                
                retry_queue = still_retrying
                
                # Brief sleep to prevent tight loop
                time.sleep(0.1)
                
            except Exception as e:
                logging.error(f"Error in solution submission queue: {e}")
                time.sleep(1)


class APIClient:
    def __init__(self):
        self.base_url = config.get("miner.api_url")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"MidnightGPU/{config.get('miner.version')}",
            "Content-Type": "application/json"
        })
        
        # Initialize solution submission queue
        self.solution_queue = SolutionSubmissionQueue(self)
        self.solution_queue.start()
        
        # Retry configuration
        self.max_retries = config.get("api.max_retries", 5)
        self.retry_delay_base = config.get("api.retry_delay_base", 2)

    def _request(self, method, endpoint, max_retries=None, **kwargs):
        """
        Make HTTP request with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint
            max_retries: Number of retry attempts (defaults to configured value)
            **kwargs: Additional arguments passed to requests
            
        Returns:
            JSON response data
            
        Raises:
            Exception: If all retry attempts fail
        """
        if max_retries is None:
            max_retries = self.max_retries
            
        url = f"{self.base_url}{endpoint}"
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                response = self.session.request(method, url, timeout=15, **kwargs)
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.HTTPError as e:
                last_exception = e
                # Client errors (4xx) - don't retry except 429 (rate limit)
                if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                    logging.warning(
                        f"API Client Error {e.response.status_code} on {endpoint}: "
                        f"{e.response.text}"
                    )
                    raise
                
                # Server errors (5xx) or rate limit - retry with backoff
                logging.warning(
                    f"API Error {e.response.status_code} on {endpoint} "
                    f"(Attempt {attempt+1}/{max_retries}): {e}"
                )
                
            except requests.exceptions.Timeout as e:
                last_exception = e
                logging.warning(
                    f"API Timeout on {endpoint} (Attempt {attempt+1}/{max_retries}): {e}"
                )
                
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                logging.warning(
                    f"API Connection Error on {endpoint} (Attempt {attempt+1}/{max_retries}): {e}"
                )
                
            except Exception as e:
                last_exception = e
                logging.warning(
                    f"API Unexpected Error on {endpoint} (Attempt {attempt+1}/{max_retries}): {e}"
                )
            
            # Exponential backoff before retry
            if attempt < max_retries - 1:
                delay = self.retry_delay_base ** attempt
                logging.debug(f"Retrying in {delay}s...")
                time.sleep(delay)
        
        raise Exception(
            f"Failed to connect to API after {max_retries} attempts: {last_exception}"
        )

    def get_current_challenge(self):
        """Get the current mining challenge."""
        try:
            data = self._request("GET", "/challenge", max_retries=3)
            challenge = data.get('challenge')
            if not challenge:
                logging.warning(f"API returned no challenge data: {data}")
            return challenge
        except Exception as e:
            logging.error(f"Failed to get current challenge: {e}")
            return None

    def register_wallet(self, address, signature, pubkey, max_retries=10):
        """
        Register a wallet with retry logic.
        
        Args:
            address: Wallet address
            signature: Signature hex
            pubkey: Public key hex
            max_retries: Number of retry attempts (default: 10)
            
        Returns:
            bool: True if registration successful or wallet already registered
        """
        endpoint = f"/register/{address}/{signature}/{pubkey}"
        try:
            self._request("POST", endpoint, max_retries=max_retries)
            logging.info(f"Wallet registered successfully: {address[:20]}...")
            return True
        except requests.exceptions.HTTPError as e:
            # Check if wallet already registered
            if "already" in e.response.text.lower():
                logging.debug(f"Wallet already registered: {address[:20]}...")
                return True
            logging.error(f"Failed to register wallet: {e}")
            return False
        except Exception as e:
            logging.error(f"Failed to register wallet after {max_retries} attempts: {e}")
            return False

    def submit_solution(self, wallet_address, challenge_id, nonce):
        """
        Submit solution to background queue for non-blocking retry.
        
        This method immediately returns and the solution is processed in the background.
        Retries automatically for up to 24 hours until successful or expired.
        
        Args:
            wallet_address: Wallet address
            challenge_id: Challenge ID
            nonce: Nonce hex string
            
        Returns:
            tuple: (True, False) - Always returns success since it's queued
        """
        self.solution_queue.submit(wallet_address, challenge_id, nonce)
        return True, False
    
    def _submit_solution_direct(self, wallet_address, challenge_id, nonce):
        """
        Direct solution submission (used internally by queue).
        
        Returns:
            tuple: (success: bool, is_fatal: bool)
        """
        endpoint = f"/solution/{wallet_address}/{challenge_id}/{nonce}"
        try:
            response = self._request("POST", endpoint, max_retries=1)  # Single attempt, queue handles retries
            # Log response for debugging
            logging.info(f"Submission Response: {response}")
            return True, False
        except requests.exceptions.HTTPError as e:
            # 400 Bad Request and 409 Conflict are fatal (invalid solution)
            if e.response.status_code in [400, 409]:
                logging.debug(f"Solution rejected (HTTP {e.response.status_code})")
                return False, True
            # Other errors are transient
            return False, False
        except Exception as e:
            logging.debug(f"Solution submission error: {e}")
            return False, False

    def consolidate_wallet(self, destination_address, original_address, signature_hex, max_retries=5):
        """
        Consolidate wallet to a destination address with retry logic.
        
        Args:
            destination_address: Destination wallet address
            original_address: Original wallet address
            signature_hex: Signature hex
            max_retries: Number of retry attempts (default: 5)
            
        Returns:
            bool: True if consolidation successful or already consolidated
        """
        endpoint = f"/donate_to/{destination_address}/{original_address}/{signature_hex}"
        try:
            self._request("POST", endpoint, max_retries=max_retries)
            logging.info(
                f"Wallet consolidated: {original_address[:10]}... → {destination_address[:10]}..."
            )
            return True
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 409:
                # Already consolidated to this address
                logging.debug(f"Wallet already consolidated: {original_address[:10]}...")
                return True
            logging.error(
                f"Failed to consolidate wallet (HTTP {e.response.status_code}): {e.response.text}"
            )
            return False
        except Exception as e:
            logging.error(f"Failed to consolidate wallet after {max_retries} attempts: {e}")
            return False

    def get_terms(self):
        """Gets the terms and conditions"""
        # Defensio T&C
        return "I agree to abide by the terms and conditions as described in version 1-0 of the Defensio DFO mining process: 2da58cd94d6ccf3d933c4a55ebc720ba03b829b84033b4844aafc36828477cc0"
    
    def shutdown(self):
        """Cleanup method to stop background threads."""
        if hasattr(self, 'solution_queue'):
            self.solution_queue.stop()


# Global instance
api = APIClient()

