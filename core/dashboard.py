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

class Dashboard:
    def __init__(self):
        self.start_time = datetime.now()
        self.lock = threading.Lock()

        # Stats
        self.total_hashrate = 0.0
        self.session_solutions = 0
        self.all_time_solutions = 0
        self.wallet_solutions = {} # wallet -> count
        self.active_wallets = 0
        self.current_challenge = "Waiting..."
        self.difficulty = "N/A"
        self.loading_message = None
        self._spinner_frames = ['|', '/', '-', '\\']
        self._spinner_index = 0

        # Console setup
        os.system('color') # Enable ANSI on Windows

    def update_stats(self, hashrate, session_sol, all_time_sol, wallet_sols, active_wallets, challenge, difficulty):
        with self.lock:
            self.total_hashrate = hashrate
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
        os.system('cls' if os.name == 'nt' else 'clear')

    def _render_loading(self):
        spinner = self._spinner_frames[self._spinner_index % len(self._spinner_frames)]
        self._spinner_index += 1

        print(f"{CYAN}{BOLD}")
        print(r"""
   ______  ____  __  __      __  __  _                     
  / ____/ / __ \/ / / /     /  |/  /(_)___  ___  _____     
 / / __  / /_/ / / / /     / /|_/ // / __ \/ _ \/ ___/     
/ /_/ / / ____/ /_/ /     / /  / // / / / /  __/ /         
\____/ /_/    \____/     /_/  /_//_/_/ /_/\___/_/          
""")
        print(f"{RESET}")
        print(f"{BOLD}{spinner} {self.loading_message or 'Loading...'}{RESET}")
        print("\nPlease wait while the CUDA kernels are being built...")

    def render(self):
        with self.lock:
            self._clear_screen()

            if self.loading_message:
                self._render_loading()
                return

            # Header
            print(f"{CYAN}{BOLD}")
            print(r"""
   ______  ____  __  __      __  __  _                     
  / ____/ / __ \/ / / /     /  |/  /(_)___  ___  _____     
 / / __  / /_/ / / / /     / /|_/ // / __ \/ _ \/ ___/     
/ /_/ / / ____/ /_/ /     / /  / // / / / /  __/ /         
\____/ /_/    \____/     /_/  /_//_/_/ /_/\___/_/          
                                                       """)
            print(f"{RESET}")
            
            version = config.get("miner.version", "1.0.0")
            uptime = self._get_uptime()
            
            print(f"{BOLD}Version:{RESET} {version} | {BOLD}Uptime:{RESET} {uptime}")
            print(f"{CYAN}" + "="*60 + f"{RESET}")
            
            # Main Stats
            print(f"\n{BOLD}Mining Status:{RESET}")
            print(f"  Active Wallets:    {self.active_wallets}")
            
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
            print(f"  Total Hashrate:    {CYAN}{hr_str}{RESET}")
            
            # Solutions
            print(f"\n{BOLD}Solutions:{RESET}")
            print(f"  Session Found:     {GREEN}{self.session_solutions}{RESET}")
            print(f"  All-Time Found:    {GREEN}{self.all_time_solutions}{RESET}")
            
            # Wallet Stats
            if self.wallet_solutions:
                print(f"\n{BOLD}Wallet Performance (Session):{RESET}")
                for wallet, count in self.wallet_solutions.items():
                    short_addr = f"{wallet[:10]}...{wallet[-4:]}"
                    print(f"  {short_addr}: {count} solutions")
            
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
