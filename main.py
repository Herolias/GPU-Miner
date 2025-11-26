#!/usr/bin/env python3
"""GPU Miner - Main Entry Point"""

import sys
import os
from pathlib import Path

# Ensure the script directory is in Python's module search path
# This allows imports to work regardless of where the script is run from
script_dir = Path(__file__).parent.resolve()
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

import time
import signal
import logging
from core.logger import setup_logging
from core.config import config
from core.miner_manager import MinerManager

def _init_multiprocessing():
    """Initialize multiprocessing with appropriate settings."""
    import multiprocessing as mp
    # Explicitly set spawn mode for consistency across platforms
    # This is the default on Windows but not on Linux/Mac
    try:
        mp.set_start_method('spawn', force=False)
    except RuntimeError:
        # Already set, ignore
        pass

def main():
    # Configure multiprocessing first
    _init_multiprocessing()
    
    # Initialize logging
    setup_logging(level=logging.INFO)
    
    # Parse CLI arguments
    import argparse
    parser = argparse.ArgumentParser(description="Midnight/Defensio Miner")
    parser.add_argument("--cpu", action="store_true", help="Enable CPU mining")
    parser.add_argument("--workers", type=int, default=1, help="Number of CPU workers (default: 1)")
    args = parser.parse_args()
    
    # Update config with CLI args
    if args.cpu:
        config.data['cpu'] = config.data.get('cpu', {})
        config.data['cpu']['enabled'] = True
        config.data['cpu']['workers'] = args.workers
        logging.info(f"CPU Mining Enabled: {args.workers} workers")

    logging.info("=== GPU Miner Starting ===")
    logging.info(f"API Base: {config.get('api_base')}")
    
    # Create and start miner
    manager = MinerManager()
    
    # Setup signal handler for clean shutdown
    def signal_handler(sig, frame):
        logging.info("\\nShutdown requested by user")
        manager.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        manager.start()
        # Keep main thread alive
        while manager.running:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("\\nShutdown requested by user")
    finally:
        logging.info("Shutting down...")
        manager.stop()

if __name__ == "__main__":
    main()
