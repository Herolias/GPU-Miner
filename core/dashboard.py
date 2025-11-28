import os
import sys
import time
import threading
from datetime import datetime, timedelta
from .config import config

# ANSI Colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

import subprocess
import psutil

class SystemMonitor:
    def __init__(self):
        self.cpu_load = 0.0
        self.cpu_temp = 0.0
        self.gpu_load = 0.0
        self.gpu_temp = 0.0
        self.last_update = 0
        self.update_interval = 2.0  # Update every 2 seconds

    def update(self):
        now = time.time()
        if now - self.last_update < self.update_interval:
            return

        self.last_update = now
        
        # CPU Stats
        try:
            self.cpu_load = psutil.cpu_percent(interval=None)
            # CPU Temp (Linux specific usually, but try psutil sensors)
            # Windows usually doesn't expose CPU temp via psutil easily without admin or specific hardware support
            # We'll skip CPU temp for Windows for now or try a generic approach if available
            temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
            if 'coretemp' in temps:
                self.cpu_temp = temps['coretemp'][0].current
            else:
                self.cpu_temp = 0.0 # Not available
        except:
            self.cpu_load = 0.0
            self.cpu_temp = 0.0

        # GPU Stats (nvidia-smi)
        try:
            # Run nvidia-smi to get load and temp
            # Format: utilization.gpu, temperature.gpu
            cmd = ['nvidia-smi', '--query-gpu=utilization.gpu,temperature.gpu', '--format=csv,noheader,nounits']
            # Use specific encoding and error handling
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=1).decode('utf-8').strip()
            if output:
                # Handle multiple GPUs - just take average or first?
                # Let's show the first one or average. For dashboard simplicity, let's show Max or Avg.
                # If multiple lines, parse them.
                lines = output.split('\n')
                loads = []
                temps = []
                for line in lines:
                    try:
                        l, t = line.split(',')
                        loads.append(float(l.strip()))
                        temps.append(float(t.strip()))
                    except:
                        pass
                
                if loads:
                    self.gpu_load = sum(loads) / len(loads)
                    self.gpu_temp = max(temps) # Show max temp for safety
        except Exception:
            self.gpu_load = 0.0
            self.gpu_temp = 0.0

class Dashboard:
    def __init__(self):
        self.start_time = datetime.now()
        self.lock = threading.Lock()

        # Stats
        self.total_hashrate = 0.0
        self.cpu_hashrate = 0.0
        self.gpu_hashrate = 0.0
        self.session_solutions = 0
        self.all_time_solutions = 0
        self.wallet_solutions = {} # wallet -> count
        self.active_wallets = 0
        self.current_challenge = "Waiting..."
        self.difficulty = "N/A"
        self.loading_message = None
        self._spinner_frames = ['|', '/', '-', '\\']
        self._spinner_index = 0
        
        # System Monitor
        self.sys_mon = SystemMonitor()

        # Console setup
        os.system('color') # Enable ANSI on Windows

    def update_stats(self, hashrate, cpu_hashrate, gpu_hashrate, session_sol, all_time_sol, wallet_sols, active_wallets, challenge, difficulty):
        with self.lock:
            self.total_hashrate = hashrate
            self.cpu_hashrate = cpu_hashrate
            self.gpu_hashrate = gpu_hashrate
            self.session_solutions = session_sol
            self.all_time_solutions = all_time_sol
            self.wallet_solutions = wallet_sols
            self.active_wallets = active_wallets
            self.current_challenge = challenge
            self.difficulty = difficulty

    def set_loading(self, message):
        """Set or clear a loading message shown instead of the dashboard."""
        with self.lock:
            self.loading_message = message
            self._spinner_index = 0

    def _get_uptime(self):
        delta = datetime.now() - self.start_time
        return str(delta).split('.')[0] # Remove microseconds

    def _clear_screen(self):
        # Use ANSI escape codes to reset cursor and clear from cursor to end
        # This reduces flicker compared to clearing the entire screen
        print('\033[H\033[J', end='')

    def _render_loading(self):
        spinner = self._spinner_frames[self._spinner_index % len(self._spinner_frames)]
        self._spinner_index += 1

        print(f"{CYAN}{BOLD}")
        print(r"""
   _____  _____   _    _     __  __  _____  _   _  ______  _____  
  / ____||  __ \ | |  | |   |  \/  ||_   _|| \ | ||  ____||  __ \ 
 | |  __ | |__) || |  | |   | \  / |  | |  |  \| || |__   | |__) |
 | | |_ ||  ___/ | |  | |   | |\/| |  | |  | . ` ||  __|  |  _  / 
 | |__| || |     | |__| |   | |  | | _| |_ | |\  || |____ | | \ \ 
  \_____||_|      \____/    |_|  |_||_____||_| \_||______||_|  \_\                                                                                                                               
""")
        print(f"{RESET}")
        print(f"{BOLD}{spinner} {self.loading_message or 'Loading...'}{RESET}")
        print("\nPlease wait while the CUDA kernels are being built...")

    def render(self):
        # Update system stats (non-blocking check inside)
        self.sys_mon.update()
        
        with self.lock:
            self._clear_screen()

            if self.loading_message:
                self._render_loading()
                return

            # Header
            print(f"{CYAN}{BOLD}")
            print(r"""
    _____  _____   _    _     __  __  _____  _   _  ______  _____  
  / ____||  __ \ | |  | |   |  \/  ||_   _|| \ | ||  ____||  __ \ 
 | |  __ | |__) || |  | |   | \  / |  | |  |  \| || |__   | |__) |
 | | |_ ||  ___/ | |  | |   | |\/| |  | |  | . ` ||  __|  |  _  / 
 | |__| || |     | |__| |   | |  | | _| |_ | |\  || |____ | | \ \ 
  \_____||_|      \____/    |_|  |_||_____||_| \_||______||_|  \_\                                                                
                                                       """)
            print(f"{RESET}")
            
            version = config.get("miner.version", "1.0.0")
            uptime = self._get_uptime()
            
            print(f"{BOLD}Version:{RESET} {version} | {BOLD}Uptime:{RESET} {uptime}")
            print(f"{CYAN}" + "="*60 + f"{RESET}")
            
            # System Stats
            cpu_str = f"CPU: {self.sys_mon.cpu_load:>4.1f}%"
            if self.sys_mon.cpu_temp > 0:
                cpu_str += f" ({self.sys_mon.cpu_temp:.0f}°C)"
            
            gpu_str = f"GPU: {self.sys_mon.gpu_load:>4.1f}%"
            if self.sys_mon.gpu_temp > 0:
                gpu_str += f" ({self.sys_mon.gpu_temp:.0f}°C)"
                
            print(f"{BOLD}System:{RESET} {cpu_str} | {gpu_str}")
            print(f"{CYAN}" + "-"*60 + f"{RESET}")

            # Main Stats
            print(f"{BOLD}Mining Status:{RESET}")
            # print(f"  Active Wallets:    {self.active_wallets}")  # Debug only
            
            challenge_display = self.current_challenge if self.current_challenge else "Waiting..."
            if len(challenge_display) > 16:
                challenge_display = challenge_display[:16] + "..."
            print(f"  Current Challenge: {GREEN}{challenge_display}{RESET}")
            
            difficulty_display = self.difficulty if self.difficulty else "N/A"
            print(f"  Difficulty:        {YELLOW}{difficulty_display}{RESET}")
            
            if self.total_hashrate < 1_000_000:
                hr_str = f"{self.total_hashrate / 1_000:.2f} KH/s"
            else:
                hr_str = f"{self.total_hashrate / 1_000_000:.2f} MH/s"
                
            # CPU/GPU Breakdown
            if self.cpu_hashrate < 1_000_000:
                cpu_hr_str = f"{self.cpu_hashrate / 1_000:.2f} KH/s"
            else:
                cpu_hr_str = f"{self.cpu_hashrate / 1_000_000:.2f} MH/s"
                
            if self.gpu_hashrate < 1_000_000:
                gpu_hr_str = f"{self.gpu_hashrate / 1_000:.2f} KH/s"
            else:
                gpu_hr_str = f"{self.gpu_hashrate / 1_000_000:.2f} MH/s"

            print(f"  Total Hashrate:    {CYAN}{hr_str}{RESET} (CPU: {cpu_hr_str} | GPU: {gpu_hr_str})")
            
            # Solutions
            print(f"\n{BOLD}Solutions:{RESET}")
            print(f"  Session Found:     {GREEN}{self.session_solutions}{RESET}")
            print(f"  All-Time Found:    {GREEN}{self.all_time_solutions}{RESET}")
            
            # Wallet Stats (Debug only)
            # if self.wallet_solutions:
            #     print(f"\n{BOLD}Wallet Performance (Session):{RESET}")
            #     for wallet, count in self.wallet_solutions.items():
            #         short_addr = f"{wallet[:10]}...{wallet[-4:]}"
            #         print(f"  {short_addr}: {count} solutions")
            
            # Consolidation
            consolidation_addr = config.get("wallet.consolidate_address")
            print(f"\n{CYAN}" + "="*60 + f"{RESET}")
            if consolidation_addr:
                print(f"{BOLD}Consolidation:{RESET} {consolidation_addr[:10]}...{consolidation_addr[-4:]}")
            else:
                print(f"{YELLOW}{BOLD}NOTE:{RESET} No consolidation address set. Edit config.yaml to set one.")
            
            print(f"{CYAN}" + "="*60 + f"{RESET}")
            print("\nPress Ctrl+C to stop.")

# Global instance
dashboard = Dashboard()
