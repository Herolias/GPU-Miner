import os
from typing import Any, Optional, Dict
import yaml
import logging
from .exceptions import ConfigurationError

DEFAULT_CONFIG: Dict[str, Any] = {
    "miner": {
        "name": "MidnightGPU",
        "version": "1.0.0",
        "api_url": "https://mine.defensio.io/api",
        "max_workers": 1,
    },
    "gpu": {
        "enabled": True,
        "batch_size": 1000000,  # Target hashes per batch
        "blocks_per_sm": 0,     # 0 = Auto
        "warmup_batch": 250000,
    },
    "cpu": {
        "enabled": False,
        "workers": 1,
    },
    "wallet": {
        "file": "wallets.db",  # SQLite DB file
        "consolidate_address": None,
    }
}


class Config:
    """
    Application configuration manager with singleton pattern.
    
    Loads configuration from YAML file and provides dot-notation access
    to nested configuration values. Merges user configuration with defaults.
    
    Example:
        >>> config = Config()
        >>> api_url = config.get('miner.api_url')
        >>> gpu_enabled = config.get('gpu.enabled', default=False)
    """
    
    _instance: Optional['Config'] = None

    def __new__(cls) -> 'Config':
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance.data = DEFAULT_CONFIG.copy()
            cls._instance.load()
        return cls._instance

    def load(self, config_path: str = "config.yaml") -> None:
        """
        Load configuration from YAML file, merging with defaults.
        
        Args:
            config_path: Path to YAML configuration file
            
        Raises:
            ConfigurationError: If config file is malformed
        """
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    user_config = yaml.safe_load(f)
                    if user_config:
                        if not isinstance(user_config, dict):
                            raise ConfigurationError(
                                config_path,
                                "Configuration file must contain a dictionary"
                            )
                        self._merge(self.data, user_config)
                logging.info(f"Loaded configuration from {config_path}")
            except yaml.YAMLError as e:
                raise ConfigurationError(config_path, f"Invalid YAML: {e}")
            except Exception as e:
                logging.error(f"Failed to load config: {e}")
                raise
        else:
            logging.info("No config file found, using defaults")
            self.save(config_path)

    def save(self, config_path: str = "config.yaml") -> None:
        """
        Save current configuration to YAML file.
        
        Args:
            config_path: Path where configuration should be saved
            
        Raises:
            ConfigurationError: If unable to write configuration file
        """
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.data, f, default_flow_style=False)
            logging.info(f"Saved configuration to {config_path}")
        except Exception as e:
            raise ConfigurationError(config_path, f"Failed to save: {e}")

    def _merge(self, default: Dict[str, Any], user: Dict[str, Any]) -> None:
        """
        Recursively merge user configuration into default configuration.
        
        Args:
            default: Default configuration dictionary (modified in place)
            user: User configuration to merge
        """
        for k, v in user.items():
            if isinstance(v, dict) and k in default and isinstance(default[k], dict):
                self._merge(default[k], v)
            else:
                default[k] = v

    def get(self, path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.
        
        Args:
            path: Dot-separated path to configuration value (e.g., 'miner.api_url')
            default: Default value if path not found
            
        Returns:
            Configuration value at path, or default if not found
            
        Example:
            >>> config.get('gpu.batch_size', default=1000000)
            1000000
        """
        keys = path.split('.')
        val = self.data
        try:
            for k in keys:
                val = val[k]
            return val
        except (KeyError, TypeError):
            return default


# Global instance
config = Config()
