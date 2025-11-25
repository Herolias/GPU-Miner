import os
import yaml
import logging

DEFAULT_CONFIG = {
    "miner": {
        "name": "MidnightGPU",
        "version": "1.0.0",
        "api_url": "https://mine.defensio.io/api",
        "max_workers": 1,
    },
    "gpu": {
        "enabled": True,
        "batch_size": 1000000, # Target hashes per batch
        "blocks_per_sm": 0,    # 0 = Auto
        "warmup_batch": 250000,
    },
    "cpu": {
        "enabled": False,
        "workers": 1,
    },
    "wallet": {
        "file": "wallets.db", # SQLite DB file
        "consolidate_address": None,
    }
}

class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance.data = DEFAULT_CONFIG.copy()
            cls._instance.load()
        return cls._instance

    def load(self, config_path="config.yaml"):
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    user_config = yaml.safe_load(f)
                    if user_config:
                        self._merge(self.data, user_config)
                logging.info(f"Loaded configuration from {config_path}")
            except Exception as e:
                logging.error(f"Failed to load config: {e}")
        else:
            logging.info("No config file found, using defaults")
            self.save(config_path)

    def save(self, config_path="config.yaml"):
        try:
            with open(config_path, 'w') as f:
                yaml.dump(self.data, f, default_flow_style=False)
            logging.info(f"Saved configuration to {config_path}")
        except Exception as e:
            logging.error(f"Failed to save config: {e}")

    def _merge(self, default, user):
        for k, v in user.items():
            if isinstance(v, dict) and k in default:
                self._merge(default[k], v)
            else:
                default[k] = v

    def get(self, path, default=None):
        """Get config value using dot notation e.g. 'miner.api_url'"""
        keys = path.split('.')
        val = self.data
        try:
            for k in keys:
                val = val[k]
            return val
        except KeyError:
            return default

# Global instance
config = Config()
