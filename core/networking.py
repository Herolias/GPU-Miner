import requests
import time
import logging
from .config import config

class APIClient:
    def __init__(self):
        self.base_url = config.get("miner.api_url")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"MidnightGPU/{config.get('miner.version')}",
            "Content-Type": "application/json"
        })

    def _request(self, method, endpoint, max_retries=3, **kwargs):
        url = f"{self.base_url}{endpoint}"
        for attempt in range(max_retries):
            try:
                response = self.session.request(method, url, timeout=10, **kwargs)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as e:
                if e.response.status_code in [400, 409]: # Client errors, don't retry
                    logging.warning(f"API Error {e.response.status_code} on {endpoint}: {e.response.text}")
                    raise
                logging.warning(f"API HTTP Error on {endpoint} (Attempt {attempt+1}/{max_retries}): {e}")
            except Exception as e:
                logging.warning(f"API Connection Error on {endpoint} (Attempt {attempt+1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt) # Exponential backoff
        
        raise Exception(f"Failed to connect to API after {max_retries} attempts")

    def get_current_challenge(self):
        try:
            data = self._request("GET", "/challenge")
            return data.get('challenge')
        except Exception:
            return None

    def register_wallet(self, address, signature, pubkey):
        endpoint = f"/register/{address}/{signature}/{pubkey}"
        try:
            self._request("POST", endpoint)
            return True
        except requests.exceptions.HTTPError as e:
            if "already" in e.response.text.lower():
                return True
            return False
        except Exception:
            return False

    def submit_solution(self, wallet_address, challenge_id, nonce):
        endpoint = f"/solution/{wallet_address}/{challenge_id}/{nonce}"
        try:
            self._request("POST", endpoint)
            return True
        except Exception as e:
            logging.error(f"Failed to submit solution: {e}")
            return False

    def consolidate_wallet(self, destination_address, original_address, signature_hex):
        """Consolidate wallet to a destination address."""
        endpoint = f"/donate_to/{destination_address}/{original_address}/{signature_hex}"
        try:
            self._request("POST", endpoint)
            return True
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 409:
                # Already consolidated to this address
                return True
            logging.warning(f"API consolidation failed: HTTP {e.response.status_code}")
            return False
        except Exception as e:
            logging.warning(f"API consolidation failed: {e}")
            return False

    def get_terms(self):
        """Gets the terms and conditions"""
        # Defensio T&C
        return "I agree to abide by the terms and conditions as described in version 1-0 of the Defensio DFO mining process: 2da58cd94d6ccf3d933c4a55ebc720ba03b829b84033b4844aafc36828477cc0"

# Global instance
api = APIClient()
