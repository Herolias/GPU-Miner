import os
from typing import Any, Optional, Dict
import yaml
import logging
import re
import shutil
from .exceptions import ConfigurationError

DEFAULT_CONFIG: Dict[str, Any] = {
    "miner": {
        "api_url": "https://mine.defensio.io/api",
        "verbose": False,
        "challenge_server_url": "https://challenges.herolias.de",
    },
    "gpu": {
        "cuda_toolkit_path": None,
        # "enabled": True,  # Now a constant
        # "batch_size": 1000000,  # Now a constant
        # "blocks_per_sm": 0,     # Now a constant
        # "warmup_batch": 250000, # Now a constant
    },
    "cpu": {
        "enabled": False,
        "workers": 1,
    },
    "wallet": {
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
                logging.warning(f"Config file corrupted (likely git conflict): {e}")
                self._recover_from_text(config_path)
            except Exception as e:
                logging.error(f"Failed to load config: {e}")
                raise
        else:
            logging.info("No config file found, using defaults")
            self.save(config_path)
            
        # Always sanitize and migrate after loading (or recovering)
        self._sanitize_and_migrate(config_path)

    def _recover_from_text(self, config_path: str) -> None:
        """
        Attempt to recover critical settings from a corrupted config file (e.g. git merge conflict).
        Parses the file as text and extracts known keys using regex.
        """
        logging.info("Attempting to recover configuration from corrupted file...")
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Backup the broken file
            broken_path = config_path + ".broken"
            shutil.copy2(config_path, broken_path)
            logging.info(f"Backed up corrupted config to {broken_path}")
            
            # Reset to defaults
            self.data = DEFAULT_CONFIG.copy()
            
            # Regex patterns for critical settings
            patterns = {
                ('miner', 'api_url'): r'api_url:\s*(https?://[^\s]+)',
                ('wallet', 'consolidate_address'): r'consolidate_address:\s*([a-zA-Z0-9_]+)',
                ('wallet', 'wallets_per_gpu'): r'wallets_per_gpu:\s*(\d+)',
                ('gpu', 'cuda_toolkit_path'): r'cuda_toolkit_path:\s*"?([^"\n]+)"?',
                ('cpu', 'enabled'): r'enabled:\s*(true|false|True|False)', # Be careful with ambiguity between sections
                ('cpu', 'workers'): r'workers:\s*(\d+)'
            }
            
            # Note: Regex for 'enabled' and 'workers' is risky because keys might be duplicated in different sections.
            # However, in our config structure:
            # - 'enabled' is in 'cpu' (and formerly 'gpu')
            # - 'workers' is in 'cpu' (and formerly 'miner.max_workers')
            # We will try to be smart or just accept best effort.
            
            # Let's try to extract section blocks first if possible, but simple regex is often robust enough for simple configs.
            # For 'enabled', if we see 'cpu:' followed by 'enabled: true', that's better.
            
            # Improved extraction:
            # Helper to pick best match
            def get_best_match(pattern, content, default_val=None):
                matches = re.findall(pattern, content)
                if not matches:
                    return None
                # Prefer the last match (likely user's stashed change in a conflict)
                # But for API URL, specifically avoid the default if possible
                if default_val and len(matches) > 1:
                    non_defaults = [m for m in matches if m.strip() != default_val]
                    if non_defaults:
                        return non_defaults[-1]
                return matches[-1]

            # 1. Miner API
            api_url = get_best_match(r'api_url:\s*(https?://[^\s]+)', content, "https://mine.defensio.io/api")
            if api_url:
                self.data['miner']['api_url'] = api_url.strip()
                logging.info(f"Recovered miner.api_url: {self.data['miner']['api_url']}")

            # 1b. Verbose
            verbose_match = re.search(r'verbose:\s*(true|false|True|False)', content, re.IGNORECASE)
            if verbose_match:
                val = verbose_match.group(1).lower() == 'true'
                self.data['miner']['verbose'] = val
                logging.info(f"Recovered miner.verbose: {val}")

            # 1c. Challenge Server URL
            cs_url = get_best_match(r'challenge_server_url:\s*(https?://[^\s]+)', content, "https://challenges.herolias.de")
            if cs_url:
                val = cs_url.strip()
                if val.lower() != 'null':
                    self.data['miner']['challenge_server_url'] = val
                    logging.info(f"Recovered miner.challenge_server_url: {val}")

            # 2. Wallet Address
            addr = get_best_match(r'consolidate_address:\s*([a-zA-Z0-9_]+)', content)
            if addr:
                val = addr.strip()
                if val.lower() != 'null':
                    self.data['wallet']['consolidate_address'] = val
                    logging.info(f"Recovered wallet.consolidate_address: {val}")

            # 3. Wallets per GPU
            wpg = get_best_match(r'wallets_per_gpu:\s*(\d+)', content)
            if wpg:
                self.data['wallet']['wallets_per_gpu'] = int(wpg)
                logging.info(f"Recovered wallet.wallets_per_gpu: {self.data['wallet']['wallets_per_gpu']}")

            # 4. CUDA Path
            cuda = get_best_match(r'cuda_toolkit_path:\s*"?([^"\n]+)"?', content)
            if cuda:
                val = cuda.strip()
                if val.lower() != 'null':
                    self.data['gpu']['cuda_toolkit_path'] = val
                    logging.info(f"Recovered gpu.cuda_toolkit_path: {val}")
                    
            # 5. CPU Settings (look for cpu block)
            # For CPU, it's harder to use findall on blocks.
            # We will try to find the last 'cpu:' occurrence and parse from there.
            cpu_starts = [m.start() for m in re.finditer(r'cpu:', content)]
            if cpu_starts:
                last_cpu_start = cpu_starts[-1]
                cpu_block = content[last_cpu_start:]
                # Truncate at next section if any
                next_section = re.search(r'(?:gpu:|miner:|wallet:)', cpu_block)
                if next_section:
                    cpu_block = cpu_block[:next_section.start()]
                
                enabled_matches = re.findall(r'enabled:\s*(true|false|True|False)', cpu_block, re.IGNORECASE)
                if enabled_matches:
                    val = enabled_matches[-1].lower() == 'true'
                    self.data['cpu']['enabled'] = val
                    logging.info(f"Recovered cpu.enabled: {val}")
                    
                workers_matches = re.findall(r'workers:\s*(\d+)', cpu_block)
                if workers_matches:
                    self.data['cpu']['workers'] = int(workers_matches[-1])
                    logging.info(f"Recovered cpu.workers: {self.data['cpu']['workers']}")

            # Save the recovered config
            self.save(config_path)
            logging.info("Successfully recovered and saved configuration.")
            
        except Exception as e:
            logging.error(f"Failed to recover config: {e}")
            # Fallback to defaults is already set in self.data

    def _sanitize_and_migrate(self, config_path: str) -> None:
        """
        Remove deprecated keys and ensure config structure is clean.
        """
        changed = False
        
        # List of deprecated keys to remove
        # Format: (section, key)
        deprecated = [
            ('gpu', 'batch_size'),
            ('gpu', 'enabled'),
            ('gpu', 'blocks_per_sm'),
            ('gpu', 'warmup_batch'),
            ('miner', 'max_workers'),
            ('miner', 'name'),
            ('miner', 'version'),
            ('wallet', 'file'),
            ('wallet', 'use_json_pools')
        ]
        
        for section, key in deprecated:
            if section in self.data and key in self.data[section]:
                del self.data[section][key]
                changed = True
                # logging.debug(f"Removed deprecated key: {section}.{key}")
        
        # Also check for empty sections if we want to clean them up? 
        # No, empty sections like 'gpu' are valid (if they have no user settings).
        
        if changed:
            logging.info("Migrated configuration: Removed deprecated keys.")
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
