import requests
import time
import logging
import threading
import queue
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

from .config import config
from .constants import (
    SOLUTION_RETRY_EXPIRY_HOURS,
    API_MAX_RETRIES,
    API_RETRY_BACKOFF_BASE,
    API_REQUEST_TIMEOUT,
    WALLET_REGISTRATION_MAX_RETRIES,
    CONSOLIDATION_MAX_RETRIES
)
from .exceptions import APIError, APITimeoutError, APIConnectionError


class SolutionSubmissionQueue:
    """
    Background queue for non-blocking solution submission with retry logic.
    
    Manages solution submissions in a background thread, automatically retrying
    failed submissions for up to SOLUTION_RETRY_EXPIRY_HOURS. Uses exponential
    backoff for transient errors and discards solutions with fatal errors.
    """
    
    def __init__(self, api_client: 'APIClient') -> None:
        """
        Initialize the submission queue.
        
        Args:
            api_client: Reference to parent APIClient instance
        """
        self.api_client: APIClient = api_client
        self.queue: queue.Queue = queue.Queue()
        self.running: bool = False
        self.thread: Optional[threading.Thread] = None
        self.retry_hours: int = config.get("api.solution_retry_hours", SOLUTION_RETRY_EXPIRY_HOURS)
        
    def start(self) -> None:
        """Start the background submission thread."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._process_queue, daemon=True)
        self.thread.start()
        logging.info("Solution submission queue started")
    
    def stop(self) -> None:
        """Stop the background submission thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logging.info("Solution submission queue stopped")
    
    def submit(self, wallet_address: str, challenge_id: str, nonce: str) -> None:
        """
        Add a solution to the submission queue.
        
        Args:
            wallet_address: Wallet that found the solution
            challenge_id: Challenge identifier
           nonce: Solution nonce as hex string
        """
        submission: Dict[str, Any] = {
            'wallet_address': wallet_address,
            'challenge_id': challenge_id,
            'nonce': nonce,
            'created_at': datetime.now(),
            'attempts': 0
        }
        self.queue.put(submission)
        logging.debug(f"Solution queued: {challenge_id[:8]}... nonce={nonce}")
    
    def _process_queue(self) -> None:
        """
        Background thread that processes solution submissions with retry logic.
        
        Continuously processes queued solutions, retrying failed submissions with
        exponential backoff. Discards solutions that are too old or have fatal errors.
        """
        retry_queue: list[Dict[str, Any]] = []
        
        while self.running:
            try:
                # Check for new submissions (non-blocking with timeout)
                try:
                    submission = self.queue.get(timeout=1)
                    retry_queue.append(submission)
                except queue.Empty:
                    pass
                
                # Process retry queue
                still_retrying: list[Dict[str, Any]] = []
                for submission in retry_queue:
                    age = datetime.now() - submission['created_at']
                    
                    # Check if solution has expired
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
    """
    API client for communicating with the mining server.
    
    Handles all HTTP requests to the mining API with automatic retry logic
    and exponential backoff. Manages solution submissions through a background
    queue for non-blocking operation.
    """
    
    def __init__(self) -> None:
        """Initialize API client with configuration and background queue."""
        self.base_url: str = config.get("miner.api_url")
        self.session: requests.Session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"MidnightGPU/{config.get('miner.version')}",
            "Content-Type": "application/json"
        })
        
        # Initialize solution submission queue
        self.solution_queue: SolutionSubmissionQueue = SolutionSubmissionQueue(self)
        self.solution_queue.start()
        
        # Retry configuration
        self.max_retries: int = config.get("api.max_retries", API_MAX_RETRIES)
        self.retry_delay_base: int = config.get("api.retry_delay_base", API_RETRY_BACKOFF_BASE)

    def _request(
        self,
        method: str,
        endpoint: str,
        max_retries: Optional[int] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Make HTTP request with retry logic and exponential backoff.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            max_retries: Number of retry attempts (defaults to configured value)
            **kwargs: Additional arguments passed to requests
            
        Returns:
            JSON response data as dictionary
            
        Raises:
            requests.exceptions.HTTPError: For 4xx client errors (except 429)
            APIError: If all retry attempts fail
        """
        if max_retries is None:
            max_retries = self.max_retries
            
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None
        
        for attempt in range(max_retries):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=API_REQUEST_TIMEOUT,
                    **kwargs
                )
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
        
        raise APIError(
            f"Failed to connect to API after {max_retries} attempts: {last_exception}"
        )

    def get_current_challenge(self) -> Optional[Dict[str, Any]]:
        """
        Get the current mining challenge from the server.
        
        Returns:
            Challenge data dictionary, or None if unavailable
        """
        try:
            data = self._request("GET", "/challenge", max_retries=3)
            challenge = data.get('challenge')
            if not challenge:
                logging.warning(f"API returned no challenge data: {data}")
            return challenge
        except Exception as e:
            logging.error(f"Failed to get current challenge: {e}")
            return None

    def register_wallet(
        self,
        address: str,
        signature: str,
        pubkey: str,
        max_retries: int = WALLET_REGISTRATION_MAX_RETRIES
    ) -> bool:
        """
        Register a wallet with the mining server.
        
        Args:
            address: Wallet address
            signature: Signature hex string
            pubkey: Public key hex string
            max_retries: Number of retry attempts
            
        Returns:
            True if registration successful or wallet already registered
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

    def submit_solution(
        self,
        wallet_address: str,
        challenge_id: str,
        nonce: str
    ) -> Tuple[bool, bool]:
        """
        Submit solution to background queue for non-blocking retry.
        
        This method immediately returns and the solution is processed in the background.
        Retries automatically for up to SOLUTION_RETRY_EXPIRY_HOURS hours until
        successful or expired.
        
        Args:
            wallet_address: Wallet address
            challenge_id: Challenge identifier
            nonce: Nonce as hex string
            
        Returns:
            Tuple of (success, is_fatal) - always (True, False) since it's queued
        """
        self.solution_queue.submit(wallet_address, challenge_id, nonce)
        return True, False
    
    def _submit_solution_direct(
        self,
        wallet_address: str,
        challenge_id: str,
        nonce: str
    ) -> Tuple[bool, bool]:
        """
        Direct solution submission (used internally by queue).
        
        Args:
            wallet_address: Wallet address
            challenge_id: Challenge identifier
            nonce: Nonce as hex string
            
        Returns:
            Tuple of (success: bool, is_fatal: bool)
            - success: True if submission successful
            - is_fatal: True if error is permanent (don't retry)
        """
        endpoint = f"/solution/{wallet_address}/{challenge_id}/{nonce}"
        try:
            response = self._request("POST", endpoint, max_retries=1)  # Single attempt
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

    def consolidate_wallet(
        self,
        destination_address: str,
        original_address: str,
        signature_hex: str,
        max_retries: int = CONSOLIDATION_MAX_RETRIES
    ) -> bool:
        """
        Consolidate wallet earnings to a destination address.
        
        Args:
            destination_address: Destination wallet address
            original_address: Original wallet address to consolidate from
            signature_hex: Signature hex string
            max_retries: Number of retry attempts
            
        Returns:
            True if consolidation successful or already consolidated
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

    def get_terms(self) -> str:
        """
        Get the terms and conditions text.
        
        Returns:
            Terms and conditions agreement string
        """
        # Defensio T&C
        return "I agree to abide by the terms and conditions as described in version 1-0 of the Defensio DFO mining process: 2da58cd94d6ccf3d933c4a55ebc720ba03b829b84033b4844aafc36828477cc0"
    
    def shutdown(self) -> None:
        """Cleanup method to stop background threads."""
        if hasattr(self, 'solution_queue'):
            self.solution_queue.stop()


# Global instance
api = APIClient()
