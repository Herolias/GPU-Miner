import multiprocessing as mp
import time
import logging
import queue
import traceback
import sys
import os
from pathlib import Path

# Add parent directory to path to find modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.rom_handler import rom_handler

class CPUWorker(mp.Process):
    def __init__(self, worker_id, request_queue, response_queue):
        super().__init__()
        self.worker_id = worker_id
        self.request_queue = request_queue
        self.response_queue = response_queue
        self.shutdown_event = mp.Event()
        self.logger = None
        self.ashmaize = None

    def run(self):
        # Setup logging in this process
        logging.basicConfig(
            level=logging.INFO,
            format=f'%(asctime)s - CPU-{self.worker_id} - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(f'cpu_worker_{self.worker_id}')
        self.logger.info(f"CPU Worker {self.worker_id} started")

        try:
            # Load library
            self.ashmaize = rom_handler.ashmaize
            if not self.ashmaize:
                # Try to load it again if not present
                self.ashmaize = rom_handler._load_library()
            
            if not self.ashmaize:
                raise Exception("Failed to load ashmaize library in worker")

            self._main_loop()
        except Exception as e:
            self.logger.critical(f"CPU Worker crashed: {e}")
            traceback.print_exc()
        finally:
            self.logger.info("CPU Worker shutting down")

    def _main_loop(self):
        self.logger.info("CPU Worker main loop started")
        
        # Cache ROMs in memory for this worker
        # Key -> ROM Object (PyRom)
        rom_cache = {}

        while not self.shutdown_event.is_set():
            try:
                req = self.request_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if req.get('type') == 'shutdown':
                self.logger.info("Shutdown request received")
                self.shutdown_event.set()
                break
            
            if req.get('type') == 'mine':
                self._execute_mine(req, rom_cache)

    def _execute_mine(self, req, rom_cache):
        try:
            rom_key = req['rom_key']
            
            # 1. Load/Build ROM
            if rom_key not in rom_cache:
                self.logger.info(f"Building ROM {rom_key[:8]}...")
                # Using 1GB size as requested
                rom_obj = self.ashmaize.build_rom_twostep(rom_key, 1073741824, 16777216, 1)
                if not rom_obj:
                    raise Exception("Failed to build ROM")
                rom_cache[rom_key] = rom_obj
                self.logger.info(f"ROM built for {rom_key[:8]}")

            rom_obj = rom_cache[rom_key]

            # 2. Prepare Args
            salt_prefix = req['salt_prefix'] # bytes
            target_difficulty = req['difficulty'] # int
            start_nonce = req['start_nonce'] # int
            request_id = req['id']
            
            # hash_with_params is a method of PyRom object
            # It expects a string for the preimage (salt_prefix)
            salt_prefix_str = salt_prefix.decode('utf-8') if isinstance(salt_prefix, bytes) else salt_prefix
            
            # Mining Loop
            # We must loop in Python because hash_with_params only does one hash
            # Signature: hash_with_params(preimage, nb_loops, nb_instrs)
            # Preimage: nonce_hex + salt_prefix
            
            # Batch size for reporting/checking
            # 1000 hashes takes ~0.5s (based on 0.5ms per hash benchmark)
            loop_batch = 1000
            
            start_time = time.time()
            
            for i in range(loop_batch):
                if self.shutdown_event.is_set():
                    break
                    
                current_nonce = (start_nonce + i) & 0xFFFFFFFFFFFFFFFF
                nonce_hex = f"{current_nonce:016x}"
                
                # Construct full preimage
                preimage_str = nonce_hex + salt_prefix_str
                
                # Execute Hash
                # nb_loops=8, nb_instrs=256 (defaults from reference)
                # Returns HEX STRING, not bytes
                digest_hex = rom_obj.hash_with_params(preimage_str, 8, 256)
                
                # Check Difficulty
                # Digest is hex string. Convert to bytes or parse int directly.
                # First 4 bytes = first 8 hex chars.
                # head <= target
                
                # Optimization: Parse directly from hex
                # Parse full 256-bit digest
                digest_int = int(digest_hex, 16)
                
                # Debug logging for first few hashes to verify values
                if i < 5:
                     self.logger.info(f"Debug: Nonce={current_nonce}, Hex={digest_hex[:16]}..., Int={digest_int}, Target={target_difficulty}")

                if digest_int <= target_difficulty:
                    self.logger.info(f"CPU Found Solution! Nonce={current_nonce}, Hex={digest_hex}, Int={digest_int}, Target={target_difficulty}")
                    self.response_queue.put({
                        'request_id': request_id,
                        'found': True,
                        'nonce': current_nonce,
                        'hash': digest_hex,
                        'hashes': i + 1,
                        'duration': time.time() - start_time
                    })
                    return

            actual_hashes = loop_batch
            
            # If loop finishes without finding a solution
            self.response_queue.put({
                'request_id': request_id,
                'found': False,
                'nonce': None,
                'hash': None,
                'hashes': actual_hashes,
                'duration': time.time() - start_time
            })

        except Exception as e:
            self.logger.error(f"Mining error on CPU {self.worker_id}: {e}")
            traceback.print_exc()
            self.response_queue.put({
                'request_id': req['id'],
                'error': str(e)
            })
