import os
import sys
import time
import threading
from datetime import datetime, timedelta
from .config import config
from .constants import MINER_VERSION

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
        self.gpus = [] # List of dicts: [{'id': 0, 'load': 0.0, 'temp': 0.0}, ...]
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
            temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
            
            # Check common Linux sensor names
            sensor_names = ['coretemp', 'k10temp', 'zenpower', 'cpu_thermal']
            found_temp = False
            
            for name in sensor_names:
                if name in temps and temps[name]:
                    self.cpu_temp = temps[name][0].current
                    found_temp = True
                    break
            
            if not found_temp:
                # Try wmic as fallback for Windows
                try:
                    # Kelvin * 10
                    cmd = ["wmic", "/namespace:\\\\root\\wmi", "PATH", "MSAcpi_ThermalZoneTemperature", "get", "CurrentTemperature"]
                    # output like:
                    # CurrentTemperature
                    # 3010
                    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=1).decode().strip()
                    lines = out.split('\n')
                    for line in lines:
                        if line.strip().isdigit():
                            kelvin_x10 = float(line.strip())
                            self.cpu_temp = (kelvin_x10 / 10.0) - 273.15
                            break
                except:
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
            
            new_gpus = []
            if output:
                lines = output.split('\n')
                for i, line in enumerate(lines):
                    try:
                        l, t = line.split(',')
                        new_gpus.append({
                            'id': i,
                            'load': float(l.strip()),
                            'temp': float(t.strip())
                        })
                    except:
                        pass
            
            self.gpus = new_gpus
            
        except Exception:
            self.gpus = []

import logging

class DashboardLogHandler(logging.Handler):
    def __init__(self, dashboard_instance):
        super().__init__()
        self.dashboard = dashboard_instance
        self.setLevel(logging.WARNING) # Only capture WARNING and ERROR

    def emit(self, record):
        try:
            msg = self.format(record)
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.dashboard.register_error(timestamp, msg, record.levelno)
        except Exception:
            self.handleError(record)

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
        
        # Status Tracking
        self.last_error = None # (timestamp, message, level)
        self.last_solution = None # (timestamp, challenge_id)
        
        # System Monitor
        self.sys_mon = SystemMonitor()
        
        # Startup State
        self.startup_complete = False

        # Console setup
        os.system('color') # Enable ANSI on Windows

    def register_error(self, timestamp, message, level):
        with self.lock:
            self.last_error = (timestamp, message, level)

    def register_solution(self, challenge_id):
        with self.lock:
            self.last_solution = (datetime.now().strftime("%H:%M:%S"), challenge_id)
            # Clear error if we found a solution? Maybe not, user wants to see last error.
            # But if the error was transient and we are mining now, maybe we should?
            # User request: "If there never was an error or warning, show when the last solution was found"
            # This implies priority: Error > Solution.
            pass

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

    def render(self):
        # Update system stats (non-blocking check inside)
        self.sys_mon.update()
        
        with self.lock:
            # Build the entire output string first to avoid flicker
            buffer = []
            
            # Clear screen ANSI code at the start
            buffer.append('\033[H\033[J')

            # Check startup completion
            if not self.startup_complete:
                cpu_enabled = config.get('cpu.enabled', False)
                # We assume GPU is always enabled for this miner
                
                cpu_ready = (not cpu_enabled) or (self.cpu_hashrate > 0)
                gpu_ready = self.gpu_hashrate > 0
                
                if cpu_ready and gpu_ready:
                    self.startup_complete = True
            
            # Show loading screen if not complete
            if not self.startup_complete:
                spinner = self._spinner_frames[self._spinner_index % len(self._spinner_frames)]
                self._spinner_index += 1
                
                buffer.append(f"{CYAN}{BOLD}")
                buffer.append(r"""
    _____  _____   _    _     __  __  _____  _   _  ______  _____  
   / ____||  __ \ | |  | |   |  \/  ||_   _|| \ | ||  ____||  __ \ 
  | |  __ | |__) || |  | |   | \  / |  | |  |  \| || |__   | |__) |
  | | |_ ||  ___/ | |  | |   | |\/| |  | |  | . ` ||  __|  |  _  / 
  | |__| || |     | |__| |   | |  | | _| |_ | |\  || |____ | | \ \ 
   \_____||_|      \____/    |_|  |_||_____||_| \_||______||_|  \_\                                                                                                                               
""")
                buffer.append(f"{RESET}")
                
                msg = self.loading_message or "Initializing..."
                buffer.append(f"{BOLD}{spinner} {msg}{RESET}")
                
                # Add context based on what we are waiting for
                if self.gpu_hashrate == 0:
                    buffer.append(f"\n{YELLOW}Waiting for GPU hashrate...{RESET}")
                if cpu_enabled and self.cpu_hashrate == 0:
                    buffer.append(f"{YELLOW}Waiting for CPU hashrate...{RESET}")
                
                # Print everything at once
                sys.stdout.write('\n'.join(buffer))
                sys.stdout.flush()
                return

            # Header
            buffer.append(f"{CYAN}{BOLD}")
            buffer.append(r"""
    _____  _____   _    _     __  __  _____  _   _  ______  _____  
  / ____||  __ \ | |  | |   |  \/  ||_   _|| \ | ||  ____||  __ \ 
 | |  __ | |__) || |  | |   | \  / |  | |  |  \| || |__   | |__) |
 | | |_ ||  ___/ | |  | |   | |\/| |  | |  | . ` ||  __|  |  _  / 
 | |__| || |     | |__| |   | |  | | _| |_ | |\  || |____ | | \ \ 
  \_____||_|      \____/    |_|  |_||_____||_| \_||______||_|  \_\                                                                
                                                       """)
            buffer.append(f"{RESET}")
            
            version = MINER_VERSION
            uptime = self._get_uptime()
            
            buffer.append(f"{BOLD}Version:{RESET} {version} | {BOLD}Uptime:{RESET} {uptime}")
            buffer.append(f"{CYAN}" + "="*60 + f"{RESET}")
            
            # System Stats
            system_items = []
            
            # CPU
            cpu_enabled = config.get('cpu.enabled', False)
            if cpu_enabled:
                cpu_str = f"CPU: {self.sys_mon.cpu_load:>4.1f}%"
                if self.sys_mon.cpu_temp > 0:
                    cpu_str += f" ({self.sys_mon.cpu_temp:.0f}°C)"
                system_items.append(cpu_str)
            
            # GPUs
            if self.sys_mon.gpus:
                for gpu in self.sys_mon.gpus:
                    g_str = f"GPU{gpu['id']}: {gpu['load']:>3.0f}%"
                    if gpu['temp'] > 0:
                        g_str += f" ({gpu['temp']:.0f}°C)"
                    system_items.append(g_str)
            else:
                system_items.append("GPU: N/A")

            # Render in chunks of 3
            ELEMENTS_PER_LINE = 3
            chunks = [system_items[i:i + ELEMENTS_PER_LINE] for i in range(0, len(system_items), ELEMENTS_PER_LINE)]
            
            if chunks:
                # First line
                buffer.append(f"{BOLD}System:{RESET} {' | '.join(chunks[0])}")
                
                # Subsequent lines
                for chunk in chunks[1:]:
                    buffer.append(f"        {' | '.join(chunk)}") # Align with where stats start
            else:
                buffer.append(f"{BOLD}System:{RESET} N/A")
                
            buffer.append(f"{CYAN}" + "-"*60 + f"{RESET}")

            # Main Stats
            buffer.append(f"{BOLD}Mining Status:{RESET}")
            
            challenge_display = self.current_challenge if self.current_challenge else "Waiting..."
            if len(challenge_display) > 16:
                challenge_display = challenge_display[:16] + "..."
            buffer.append(f"  Current Challenge: {GREEN}{challenge_display}{RESET}")
            
            difficulty_display = self.difficulty if self.difficulty else "N/A"
            buffer.append(f"  Difficulty:        {YELLOW}{difficulty_display}{RESET}")
            
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

            if cpu_enabled:
                buffer.append(f"  Total Hashrate:    {CYAN}{hr_str}{RESET} (CPU: {cpu_hr_str} | GPU: {gpu_hr_str})")
            else:
                buffer.append(f"  Total Hashrate:    {CYAN}{hr_str}{RESET}")
            
            # Solutions
            buffer.append(f"\n{BOLD}Solutions:{RESET}")
            buffer.append(f"  Session Found:     {GREEN}{self.session_solutions}{RESET}")
            buffer.append(f"  All-Time Found:    {GREEN}{self.all_time_solutions}{RESET}")
            
            # Consolidation
            consolidation_addr = config.get("wallet.consolidate_address")
            buffer.append(f"\n{CYAN}" + "="*60 + f"{RESET}")
            if consolidation_addr:
                buffer.append(f"{BOLD}Consolidation:{RESET} {consolidation_addr[:10]}...{consolidation_addr[-4:]}")
            else:
                buffer.append(f"{YELLOW}{BOLD}NOTE:{RESET} No consolidation address set. Edit config.yaml to set one.")
            
            # Status Section
            buffer.append(f"{CYAN}" + "="*60 + f"{RESET}")
            
            # Only show Last Issue if verbose is enabled
            show_issues = config.get("miner.verbose", False)
            
            if self.last_error and show_issues:
                ts, msg, level = self.last_error
                color = RED if level >= logging.ERROR else YELLOW
                # Truncate message if too long
                if len(msg) > 50:
                    msg = msg[:47] + "..."
                buffer.append(f"{color}{BOLD}Last Issue:{RESET} [{ts}] {msg}")
            elif self.last_solution:
                ts, challenge_id = self.last_solution
                buffer.append(f"{GREEN}{BOLD}Last Solution:{RESET} [{ts}] for Challenge {challenge_id}")
            elif show_issues:
                buffer.append(f"{GREEN}Status: Running{RESET}")
            
            buffer.append(f"{CYAN}" + "="*60 + f"{RESET}")
            buffer.append("\nPress Ctrl+C to stop.")
            
            # Print everything at once
            sys.stdout.write('\n'.join(buffer))
            sys.stdout.flush()

# Global instance
dashboard = Dashboard()
