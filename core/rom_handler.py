import sys
import os
import platform
import logging

class ROMHandler:
    def __init__(self):
        self.ashmaize = self._load_library()

    def _load_library(self):
        """Loads the platform-specific ashmaize_py library."""
        system = platform.system().lower()
        machine = platform.machine().lower()

        if machine in ['x86_64', 'amd64', 'x64']:
            arch = 'x64'
        elif machine in ['aarch64', 'arm64', 'armv8']:
            arch = 'arm64'
        else:
            arch = machine

        platform_map = {
            ('windows', 'x64'): 'windows-x64',
            ('linux', 'x64'): 'linux-x64',
        }

        key = (system, arch)
        if key not in platform_map:
            logging.error(f"Unsupported platform: {system} {arch}")
            return None

        lib_dir = os.path.join(os.getcwd(), 'libs', platform_map[key])
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)

        try:
            import ashmaize_py
            logging.info(f"Loaded ashmaize_py from {lib_dir}")
            return ashmaize_py
        except ImportError as e:
            logging.error(f"Failed to load ashmaize_py: {e}")
            return None

    def build_rom(self, rom_key):
        """Builds the ROM for a given key (challenge['no_pre_mine'])."""
        if not self.ashmaize:
            logging.error("Ashmaize library not loaded")
            return None

        try:
            # Constants from reference implementation
            # Size: 1GB (1073741824)
            # Segment: 16MB (16777216)
            # Threads: 4
            logging.info(f"Building ROM {rom_key[:10]}... (this may take a few seconds)")
            rom = self.ashmaize.build_rom_twostep(rom_key, 1073741824, 16777216, 4)
            return rom
        except Exception as e:
            logging.error(f"Error building ROM: {e}")
            return None

# Global instance
rom_handler = ROMHandler()
