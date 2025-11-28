"""
Challenge Cache Module

Manages JSON-based challenge cache with 24h validity window.
Tracks all discovered challenges and provides filtering/selection logic.
"""

import json
import logging
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from filelock import FileLock

from .types import Challenge


class ChallengeCache:
    """
    Manages JSON-based challenge cache with 24h validity window.
    
    Stores all discovered challenges with timestamps and provides methods
    to filter by validity period and other criteria.
    """
    
    def __init__(self, cache_file: str = "challenges.json") -> None:
        """
        Initialize challenge cache.
        
        Args:
            cache_file: Path to JSON cache file
        """
        self.cache_file = Path(cache_file)
        self.lock_file = Path(f"{cache_file}.lock")
        self._lock = threading.Lock()
        self._file_lock = FileLock(str(self.lock_file), timeout=10)
    
    def register_challenge(self, challenge: Challenge) -> None:
        """
        Add new challenge to cache if not exists.
        
        Args:
            challenge: Challenge data dict from API
        """
        with self._lock:
            with self._file_lock:
                data = self._load()
                
                # Check if already exists
                for c in data['challenges']:
                    if c['challenge_id'] == challenge['challenge_id']:
                        return
                
                # Add with timestamp
                now = datetime.now()
                entry = {
                    'challenge_id': challenge['challenge_id'],
                    'no_pre_mine': challenge['no_pre_mine'],
                    'difficulty': challenge['difficulty'],
                    'discovered_at': now.isoformat(),
                    'expires_at': (now + timedelta(hours=24)).isoformat()
                }
                data['challenges'].append(entry)
                
                self._save(data)
                logging.info(f"Registered challenge {challenge['challenge_id'][:8]}... (difficulty: {challenge['difficulty'][:10]}...)")
    
    def get_valid_challenges(self, min_time_remaining_hours: float = 1.0) -> List[Dict[str, Any]]:
        """
        Get challenges that are still valid with enough time remaining.
        
        Args:
            min_time_remaining_hours: Minimum hours until expiry (default: 1.0)
            
        Returns:
            List of valid challenge dicts
        """
        with self._lock:
            with self._file_lock:
                data = self._load()
                now = datetime.now()
                cutoff = now + timedelta(hours=min_time_remaining_hours)
                
                valid = []
                for c in data['challenges']:
                    expires = datetime.fromisoformat(c['expires_at'])
                    if expires > cutoff:
                        valid.append(c)
                
                logging.debug(f"Found {len(valid)} valid challenges (min {min_time_remaining_hours}h remaining)")
                return valid
    
    def cleanup_expired(self) -> int:
        """
        Remove expired challenges from cache.
        
        Returns:
            Number of challenges removed
        """
        with self._lock:
            with self._file_lock:
                data = self._load()
                now = datetime.now()
                
                before_count = len(data['challenges'])
                data['challenges'] = [
                    c for c in data['challenges']
                    if datetime.fromisoformat(c['expires_at']) > now
                ]
                removed = before_count - len(data['challenges'])
                
                if removed > 0:
                    self._save(data)
                    logging.info(f"Removed {removed} expired challenges from cache")
                
                return removed
    
    def _load(self) -> Dict[str, Any]:
        """Load cache from JSON file."""
        if not self.cache_file.exists():
            return {'challenges': []}
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading challenge cache: {e}")
            return {'challenges': []}
    
    def _save(self, data: Dict[str, Any]) -> None:
        """Save cache to JSON file."""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving challenge cache: {e}")


# Global instance
challenge_cache = ChallengeCache()
