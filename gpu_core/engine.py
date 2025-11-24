import multiprocessing as mp
import time
import logging
import sys
import os
import numpy as np
from pathlib import Path
import queue
import traceback

# Import kernels
from .kernels import CUDA_SOURCE
from core.rom_handler import rom_handler

# Define cache dir
KERNEL_CACHE_DIR = Path(__file__).parent / ".cuda_cache"
KERNEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

class GPUEngine(mp.Process):
    def __init__(self, request_queue, response_queue):
        super().__init__()
        self.request_queue = request_queue
        self.response_queue = response_queue
        self.shutdown_event = mp.Event()
        self.logger = None

    def run(self):
        # Setup logging in this process
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - GPU - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger('gpu_engine')
        self.logger.info("GPU Engine started")

        try:
            self._init_cuda()
            self._main_loop()
        except Exception as e:
            self.logger.critical(f"GPU Engine crashed: {e}")
            traceback.print_exc()
        finally:
            self.logger.info("GPU Engine shutting down")

    def _find_cl_path(self):
        import shutil
        cl_path = shutil.which('cl.exe')
        if cl_path:
            return os.path.dirname(cl_path)
        
        possible_paths = [
            r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC",
            r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Tools\MSVC",
            r"C:\Program Files (x86)\Microsoft Visual Studio\2017\Community\VC\Tools\MSVC"
        ]
        
        for base in possible_paths:
            if os.path.exists(base):
                versions = sorted(os.listdir(base), reverse=True)
                if versions:
                    bin_path = os.path.join(base, versions[0], "bin", "Hostx64", "x64")
                    if os.path.exists(os.path.join(bin_path, "cl.exe")):
                        return bin_path
        return None

    def _init_cuda(self):
        if sys.platform == 'win32':
            cl_path = self._find_cl_path()
            if cl_path and cl_path not in os.environ['PATH']:
                self.logger.info(f"Adding MSVC compiler to PATH: {cl_path}")
                os.environ['PATH'] += os.pathsep + cl_path

        import pycuda.autoinit
        from pycuda.compiler import SourceModule
        import pycuda.driver as cuda
        
        self.cuda = cuda
        self.dev = pycuda.autoinit.device
        self.ctx = pycuda.autoinit.context

        # Set stack size
        try:
            self.ctx.set_limit(cuda.limit.STACK_SIZE, 4096)
        except Exception as e:
            self.logger.warning(f"Failed to set stack size: {e}")

        self.logger.info("Compiling CUDA kernels...")
        self.mod = SourceModule(
            CUDA_SOURCE,
            options=['--use_fast_math', '-Xcompiler', '/wd 4819'],
            no_extern_c=True,
            cache_dir=str(KERNEL_CACHE_DIR)
        )
        self.mine_kernel = self.mod.get_function("mine_kernel_v2")
        
        # Allocations
        self.h_found_nonce = cuda.pagelocked_empty(1, dtype=np.uint64)
        self.h_found_flag = cuda.pagelocked_empty(1, dtype=np.int32)
        self.d_found_nonce = cuda.mem_alloc(self.h_found_nonce.nbytes)
        self.d_found_flag = cuda.mem_alloc(self.h_found_flag.nbytes)
        
        self.rom_cache = {} # key -> {ptr, digest_ptr, len}

    def _load_rom(self, rom_key, rom_data, rom_digest):
        if rom_key in self.rom_cache:
            return self.rom_cache[rom_key]
            
        rom_np = np.frombuffer(rom_data, dtype=np.uint8)
        rom_ptr = self.cuda.mem_alloc(rom_np.nbytes)
        self.cuda.memcpy_htod(rom_ptr, rom_np)
        
        rom_digest_np = np.frombuffer(rom_digest, dtype=np.uint8)
        rom_digest_ptr = self.cuda.mem_alloc(rom_digest_np.nbytes)
        self.cuda.memcpy_htod(rom_digest_ptr, rom_digest_np)
        
        entry = {
            'ptr': rom_ptr,
            'digest_ptr': rom_digest_ptr,
            'len': rom_np.nbytes
        }
        self.rom_cache[rom_key] = entry
        self.logger.info(f"Loaded ROM {rom_key} to GPU")
        return entry

    def _main_loop(self):
        self.logger.info("GPU Engine main loop started")
        
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
                self._execute_mine(req)

    def _execute_mine(self, req):
        try:
            rom_key = req['rom_key']
            
            # 1. Load/Build ROM
            if rom_key not in self.rom_cache:
                rom_obj = rom_handler.build_rom(rom_key)
                if not rom_obj:
                    raise Exception("Failed to build ROM")
                
                self._load_rom(rom_key, rom_obj.data, rom_obj.digest)

            rom_entry = self.rom_cache[rom_key]

            # 2. Prepare Args
            salt_prefix = req['salt_prefix']
            target_difficulty = req['difficulty']
            start_nonce = req['start_nonce']
            
            # Ensure salt buffer
            salt_len = len(salt_prefix)
            if not hasattr(self, 'd_salt_prefix') or self.d_salt_prefix_capacity < salt_len:
                if hasattr(self, 'd_salt_prefix'):
                    self.d_salt_prefix.free()
                alloc_size = max(salt_len, 1024) 
                self.d_salt_prefix = self.cuda.mem_alloc(alloc_size)
                self.d_salt_prefix_capacity = alloc_size
                
            self.cuda.memcpy_htod(self.d_salt_prefix, np.frombuffer(salt_prefix, dtype=np.uint8))

            # Ensure nonce/difficulty buffers (pointers expected by kernel)
            if not hasattr(self, 'd_start_nonce'):
                self.d_start_nonce = self.cuda.mem_alloc(8)
                self.d_difficulty = self.cuda.mem_alloc(8)

            self.cuda.memcpy_htod(self.d_start_nonce, np.array([start_nonce], dtype=np.uint64))
            self.cuda.memcpy_htod(self.d_difficulty, np.array([target_difficulty], dtype=np.uint64))

            # 3. Execute Kernel
            # Grid/Block sizing
            block_size = 256
            grid_size = 256 # TODO: Make dynamic/configurable
            
            self.cuda.memset_d32(self.d_found_flag, 0, 1)
            
            start_time = time.perf_counter()
            
            self.mine_kernel(
                rom_entry['ptr'],
                np.int32(rom_entry['len']),
                rom_entry['digest_ptr'],
                self.d_salt_prefix,
                np.int32(salt_len),
                self.d_start_nonce,        # Pass pointer
                self.d_difficulty,         # Pass pointer
                self.d_found_nonce,
                self.d_found_flag,
                block=(block_size, 1, 1),
                grid=(grid_size, 1)
            )
            
            self.ctx.synchronize()
            end_time = time.perf_counter()
            duration = end_time - start_time
            
            # 4. Check Results
            self.cuda.memcpy_dtoh(self.h_found_flag, self.d_found_flag)
            
            found = False
            nonce = None
            
            if self.h_found_flag[0] == 1:
                self.cuda.memcpy_dtoh(self.h_found_nonce, self.d_found_nonce)
                nonce = int(self.h_found_nonce[0])
                found = True
                self.logger.info(f"SOLUTION FOUND! Nonce: {nonce}")

            self.response_queue.put({
                'request_id': req['id'],
                'status': 'completed',
                'found': found,
                'nonce': nonce,
                'hashes': block_size * grid_size,
                'duration': duration
            })
            
        except Exception as e:
            self.logger.error(f"Mining error: {e}")
            traceback.print_exc()
            self.response_queue.put({
                'request_id': req['id'],
                'error': str(e)
            })

