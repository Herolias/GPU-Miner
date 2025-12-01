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

# Logos
LOGO_LEGACY = r"""
    _____  _____   _    _     __  __  _____  _   _  ______  _____  
   / ____||  __ \ | |  | |   |  \/  ||_   _|| \ | ||  ____||  __ \ 
  | |  __ | |__) || |  | |   | \  / |  | |  |  \| || |__   | |__) |
  | | |_ ||  ___/ | |  | |   | |\/| |  | |  | . ` ||  __|  |  _  / 
  | |__| || |     | |__| |   | |  | | _| |_ | |\  || |____ | | \ \ 
   \_____||_|      \____/    |_|  |_||_____||_| \_||______||_|  \_\ 
"""

LOGO_FANCY = r"""
  _____  _____   _    _     __  __  _____  _   _  ______  _____  
 / ____||  __ \ | |  | |   |  \/  ||_   _|| \ | ||  ____||  __ \ 
| |  __ | |__) || |  | |   | \  / |  | |  |  \| || |__   | |__) |
| | |_ ||  ___/ | |  | |   | |\/| |  | |  | . ` ||  __|  |  _  / 
| |__| || |     | |__| |   | |  | | _| |_ | |\  || |____ | | \ \ 
 \_____||_|      \____/    |_|  |_||_____||_| \_||______||_|  \_\ 
"""

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
                    # Suppress stderr to avoid "Access denied" leaking
                    out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=1).decode().strip()
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
        self.gpu_hashrates = {} # worker_id -> hashrate
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
            pass

    def update_stats(self, hashrate, cpu_hashrate, gpu_hashrate, gpu_hashrates, session_sol, all_time_sol, wallet_sols, active_wallets, challenge, difficulty):
        with self.lock:
            self.total_hashrate = hashrate
            self.cpu_hashrate = cpu_hashrate
            self.gpu_hashrate = gpu_hashrate
            self.gpu_hashrates = gpu_hashrates
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
        # Dispatch based on config
        if config.get('miner.legacy_dashboard', False):
            self.render_legacy()
        else:
            self.render_fancy()

    def _draw_progress_bar(self, percent, width=10):
        """Draw a progress bar like [|||||.....]"""
        fill = int(width * percent / 100)
        fill = max(0, min(width, fill))
        empty = width - fill
        
        # Color based on load (High load is GOOD for mining)
        color = RED
        if percent > 50: color = YELLOW
        if percent > 90: color = GREEN
        
        bar = "|" * fill + "." * empty
        return f"[{color}{bar}{RESET}]"

    def _print_box_line(self, buffer, left_text, right_text, width):
        """Helper to print a box line with two columns."""
        # Calculate available width for columns
        # Structure: │ left │ right │
        # Borders: 3 chars (│, │, │)
        # Padding: 4 spaces ( one after/before each border)
        # Total overhead: 7 chars? No.
        # │ left │ right │
        # 0 1... L L+1... R R+1
        
        # Let's define fixed widths
        # Total Width = width
        # Left Column Width = 28 (including padding)
        # Right Column Width = Remaining
        
        # │<--28-->│<--Rest-->│
        
        # Left content max width = 26 (28 - 2 padding)
        # Right content max width = width - 2 - 28 - 2 - 1 = width - 33
        
        LEFT_COL_WIDTH = 28
        RIGHT_COL_WIDTH = width - 2 - LEFT_COL_WIDTH - 1 # -2 outer borders, -1 middle border
        
        # Pad left
        left_padded = self._pad_ansi(left_text, LEFT_COL_WIDTH - 2) # -2 for spaces
        
        # Pad right
        right_padded = self._pad_ansi(right_text, RIGHT_COL_WIDTH - 2) # -2 for spaces
        
        buffer.append(f"{CYAN}│{RESET} {left_padded} {CYAN}│{RESET} {right_padded} {CYAN}│{RESET}")

    def render_fancy(self):
        """New 'Fancy' Dashboard with Boxed Layout"""
        # 1. Loading Screen (Reused logic)
        if not self._check_startup():
            self.render_legacy()
            return

        self.sys_mon.update()
        
        # Layout Constants
        WIDTH = 74 # Total width including borders
        
        with self.lock:
            buffer = []
            buffer.append('\033[H\033[J') # Clear screen

            # Top Border
            buffer.append(f"{CYAN}┌{'─'*(WIDTH-2)}┐{RESET}")
            
            # Logo (Centered in box)
            for line in LOGO_FANCY.strip('\n').split('\n'):
                # Center the logo
                padding = (WIDTH - 2 - len(line)) // 2
                logo_line = " " * padding + f"{BOLD}{CYAN}{line}{RESET}" + " " * (WIDTH - 2 - len(line) - padding)
                buffer.append(f"{CYAN}│{RESET}{logo_line}{CYAN}│{RESET}")
            
            buffer.append(f"{CYAN}├{'─'*(WIDTH-2)}┤{RESET}")
            
            # Info Bar
            uptime = self._get_uptime()
            version = MINER_VERSION
            info_line = f" {BOLD}GPU MINER v{version}{RESET}"
            uptime_str = f"{BOLD}Uptime: {uptime}{RESET} "
            
            # Calculate spacing
            # Length without ANSI
            info_len = len(f" GPU MINER v{version}")
            uptime_len = len(f"Uptime: {uptime} ")
            space = WIDTH - 2 - info_len - uptime_len
            
            buffer.append(f"{CYAN}│{RESET}{info_line}{' '*space}{uptime_str}{CYAN}│{RESET}")
            buffer.append(f"{CYAN}├{'─'*28}┬{'─'*(WIDTH-31)}┤{RESET}")
            
            # Content Columns
            # Left: System (28 chars wide approx)
            # Right: Metrics (Rest)
            
            metrics = []
            
            # Challenge
            chal_id = self.current_challenge.get('challenge_id', 'Waiting...') if isinstance(self.current_challenge, dict) else self.current_challenge
            if chal_id and len(chal_id) > 8 and chal_id != "Waiting...":
                chal_display = chal_id[:8] + "..."
            else:
                chal_display = chal_id
                
            metrics.append(f"{BOLD}Newest Challenge:{RESET}  {GREEN}{chal_display}{RESET}")
            
            # Difficulty
            diff_display = self.difficulty[:12] + "" if self.difficulty else "N/A"
            metrics.append(f"{BOLD}Difficulty:{RESET} {YELLOW}{diff_display}{RESET}")
            metrics.append("")
            
            # Performance
            metrics.append(f"{BOLD}PERFORMANCE{RESET}")
            metrics.append(f"Session Sol: {GREEN}{self.session_solutions}{RESET}")
            metrics.append(f"Total Sol:   {GREEN}{self.all_time_solutions}{RESET}")
            
            # Efficiency
            elapsed_min = (datetime.now() - self.start_time).total_seconds() / 60.0
            if elapsed_min > 0:
                rate = self.session_solutions / elapsed_min
                metrics.append(f"Rate:        {rate:.2f} Sol/m")
            else:
                metrics.append(f"Rate:        0.00 Sol/m")

            # Left Column (System)
            system = []
            
            # CPU
            cpu_enabled = config.get('cpu.enabled', False)
            if cpu_enabled:
                bar = self._draw_progress_bar(self.sys_mon.cpu_load)
                if self.cpu_hashrate < 1_000_000:
                    cpu_hr = f"{self.cpu_hashrate / 1_000:.1f} KH/s"
                else:
                    cpu_hr = f"{self.cpu_hashrate / 1_000_000:.1f} MH/s"
                
                temp_str = ""
                if self.sys_mon.cpu_temp > 0:
                    temp_str = f"{self.sys_mon.cpu_temp:.0f}°C"
                
                system.append(f"CPU: {bar} {self.sys_mon.cpu_load:>3.0f}%")
                system.append(f"     {cpu_hr} {temp_str}")
            else:
                system.append(f"CPU: {YELLOW}Disabled{RESET}")
                system.append("")

            # GPUs
            if self.sys_mon.gpus:
                for gpu in self.sys_mon.gpus:
                    gid = gpu['id']
                    bar = self._draw_progress_bar(gpu['load'])
                    
                    ghr = self.gpu_hashrates.get(gid, 0.0)
                    if ghr < 1_000_000:
                        ghr_str = f"{ghr / 1_000:.1f} KH/s"
                    else:
                        ghr_str = f"{ghr / 1_000_000:.1f} MH/s"
                    
                    temp_str = ""
                    if gpu['temp'] > 0:
                        temp_str = f"{gpu['temp']:.0f}°C"
                        
                    system.append(f"GPU{gid}:{bar} {gpu['load']:>3.0f}%")
                    system.append(f"     {ghr_str} {temp_str}")
            else:
                system.append("GPU: N/A")

            # Render Columns
            max_rows = max(len(system), len(metrics))
            
            for i in range(max_rows):
                left = system[i] if i < len(system) else ""
                right = metrics[i] if i < len(metrics) else ""
                self._print_box_line(buffer, left, right, WIDTH)

            buffer.append(f"{CYAN}├{'─'*(WIDTH-2)}┤{RESET}")
            
            # Total Hashrate (Prominent)
            if self.total_hashrate < 1_000_000:
                total_hr_str = f"{self.total_hashrate / 1_000:.2f} KH/s"
            else:
                total_hr_str = f"{self.total_hashrate / 1_000_000:.2f} MH/s"
                
            # Center the hashrate
            hr_line = f"{BOLD}TOTAL HASHRATE: {CYAN}{total_hr_str}{RESET}"
            buffer.append(f"{CYAN}│{RESET} {self._pad_ansi(hr_line, WIDTH-4)} {CYAN}│{RESET}")
            
            buffer.append(f"{CYAN}├{'─'*(WIDTH-2)}┤{RESET}")
            
            # Status Area
            msg = f"{BOLD}STATUS:{RESET}"
            buffer.append(f"{CYAN}│{RESET} {self._pad_ansi(msg, WIDTH-4)} {CYAN}│{RESET}")
            
            # Consolidation Warning
            consolidation_addr = config.get("wallet.consolidate_address")
            if not consolidation_addr:
                 msg = f"{YELLOW}[WARNING] No consolidation address set!{RESET}"
                 buffer.append(f"{CYAN}│{RESET} {self._pad_ansi(msg, WIDTH-4)} {CYAN}│{RESET}")
            
            # Last Log/Solution
            show_issues = config.get("miner.verbose", False)
            last_msg = ""
            
            if self.last_error and show_issues:
                ts, msg, level = self.last_error
                color = RED if level >= logging.ERROR else YELLOW
                last_msg = f"{color}[{ts}] {msg}{RESET}"
            elif self.last_solution:
                ts, challenge_id = self.last_solution
                last_msg = f"{GREEN}[{ts}] Found solution for {challenge_id[:8]}...{RESET}"
            else:
                last_msg = f"{GREEN}Running...{RESET}"
                
            # Truncate/Pad
            buffer.append(f"{CYAN}│{RESET} {self._pad_ansi(last_msg, WIDTH-4)} {CYAN}│{RESET}")
            
            buffer.append(f"{CYAN}└{'─'*(WIDTH-2)}┘{RESET}")
            
            sys.stdout.write('\n'.join(buffer))
            sys.stdout.flush()

    def _pad_ansi(self, text, width):
        """Pad text to width, ignoring ANSI codes."""
        # Remove ANSI to get visible length
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        visible = ansi_escape.sub('', text)
        visible_len = len(visible)
        
        padding = width - visible_len
        if padding > 0:
            return text + " " * padding
        return text

    def _check_startup(self):
        """Check if startup is complete (helper for both renderers)."""
        if not self.startup_complete:
            # Failsafe logic (already implemented in render_legacy, moved here?)
            # Actually, let's duplicate the check or move it to a shared method
            # For now, I'll rely on the check inside render_legacy/fancy or move it to update()
            
            # Re-implement failsafe here to be safe
            startup_timeout = config.get('miner.startup_timeout', 300)
            if (datetime.now() - self.start_time).total_seconds() > startup_timeout:
                self.startup_complete = True
                self.register_error(
                    datetime.now().strftime("%H:%M:%S"), 
                    "Startup timed out - Forced dashboard load", 
                    logging.WARNING
                )
            
            cpu_enabled = config.get('cpu.enabled', False)
            cpu_ready = (not cpu_enabled) or (self.cpu_hashrate > 0)
            gpu_ready = self.gpu_hashrate > 0
            
            if cpu_ready and gpu_ready:
                self.startup_complete = True
                
        return self.startup_complete

    def _render_loading(self, buffer):
        """Render loading screen (shared)."""
        # ... (Reuse the logic from render_legacy, but we can't easily share code without refactoring)
        # For now, I'll just copy the loading logic into render_fancy or call render_legacy for loading
        # Calling render_legacy for loading is easiest!
        self.render_legacy() 
        return

    def render_legacy(self):
        # Update system stats (non-blocking check inside)
        self.sys_mon.update()
        
        with self.lock:
            # Build the entire output string first to avoid flicker
            buffer = []
            
            # Clear screen ANSI code at the start
            buffer.append('\033[H\033[J')

            # Check startup completion
            if not self._check_startup():
                # Failsafe logic is in _check_startup now
                pass
            
            # Show loading screen if not complete
            if not self.startup_complete:
                spinner = self._spinner_frames[self._spinner_index % len(self._spinner_frames)]
                self._spinner_index += 1
                
                buffer.append(f"{CYAN}{BOLD}")
                buffer.append(LOGO_LEGACY)
                buffer.append(f"{RESET}")
                
                # Loading Box
                buffer.append(f"{CYAN}┌" + "─"*58 + "┐" + f"{RESET}")
                
                msg = self.loading_message or "Initializing..."
                buffer.append(f"{CYAN}│{RESET} {BOLD}{spinner} Status:{RESET} {msg:<46} {CYAN}│{RESET}")
                
                # System Detection Status
                gpu_count = len(self.sys_mon.gpus) if self.sys_mon.gpus else 0
                cpu_enabled = config.get('cpu.enabled', False)
                
                status_line = f"GPUs Detected: {gpu_count}"
                if cpu_enabled:
                    status_line += " | CPU Mining: Enabled"
                
                buffer.append(f"{CYAN}│{RESET} {status_line:<56} {CYAN}│{RESET}")
                
                # Waiting for...
                wait_msg = ""
                if self.gpu_hashrate == 0:
                    wait_msg = "Waiting for GPU hashrate..."
                elif cpu_enabled and self.cpu_hashrate == 0:
                    wait_msg = "Waiting for CPU hashrate..."
                
                if wait_msg:
                     buffer.append(f"{CYAN}│{RESET} {YELLOW}{wait_msg:<56}{RESET} {CYAN}│{RESET}")

                buffer.append(f"{CYAN}└" + "─"*58 + "┘" + f"{RESET}")

                # Show errors if any (CRITICAL FIX: Show errors even during loading)
                if self.last_error:
                    ts, err_msg, level = self.last_error
                    color = RED if level >= logging.ERROR else YELLOW
                    buffer.append(f"\n{color}{BOLD}Latest Issue:{RESET} [{ts}] {err_msg}")
                
                # Print everything at once
                sys.stdout.write('\n'.join(buffer))
                sys.stdout.flush()
                return

            # Header
            buffer.append(f"{CYAN}{BOLD}")
            buffer.append(LOGO_LEGACY)
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
            if isinstance(challenge_display, dict):
                challenge_display = challenge_display.get('challenge_id', 'Waiting...')
                
            if len(challenge_display) > 16:
                challenge_display = challenge_display[:16] + "..."
            buffer.append(f"  Newest Challenge: {GREEN}{challenge_display}{RESET}")
            
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
