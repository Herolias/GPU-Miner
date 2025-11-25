import sys
import platform
import logging
from pathlib import Path
from typing import Optional, Any

from .constants import DEFAULT_ROM_SIZE, DEFAULT_ROM_SEGMENT_SIZE, DEFAULT_ROM_BUILD_THREADS
from .exceptions import ROMLibraryError, ROMBuildError

BASE_DIR = Path(__file__).resolve().parent.parent


class ROMHandler:
    """
    Handles loading the ashmaize_py library and building ROMs.
    
    The ashmaize library is platform-specific and must be loaded from
    the appropriate libs directory based on the current OS and architecture.
    """
    
    def __init__(self) -> None:
        """Initialize ROMHandler and load platform-specific library."""
        self.ashmaize: Optional[Any] = self._load_library()

    def _load_library(self) -> Optional[Any]:
        """
        Load the platform-specific ashmaize_py library.
        
        Returns:
            The loaded ashmaize_py module, or None if loading fails
            
        Raises:
            ROMLibraryError: If platform is unsupported or library cannot be loaded
        """
        system = platform.system().lower()
        machine = platform.machine().lower()
        
        logging.info(f"Detected platform: {system} {machine}")

        # Normalize architecture names
        if machine in ['x86_64', 'amd64', 'x64']:
            arch = 'x64'
        elif machine in ['aarch64', 'arm64', 'armv8']:
            arch = 'arm64'
        else:
            arch = machine

        platform_map = {
            ('windows', 'x64'): 'windows-x64',
            ('linux', 'x64'): 'linux-x64',
            ('linux', 'arm64'): 'linux-arm64',
            ('darwin', 'x64'): 'macos-x64',
            ('darwin', 'arm64'): 'macos-arm64',
        }

        key = (system, arch)
        if key not in platform_map:
            error_msg = f"Unsupported platform: {system} {arch}"
            logging.error(error_msg)
            logging.error(f"Supported platforms: {', '.join(f'{s}/{a}' for s, a in platform_map.keys())}")
            raise ROMLibraryError(error_msg)

        lib_dir = BASE_DIR / 'libs' / platform_map[key]
        if not lib_dir.exists():
            error_msg = f"ashmaize library directory missing: {lib_dir}"
            logging.error(error_msg)
            logging.error("Please ensure the ashmaize library is installed for your platform")
            raise ROMLibraryError(error_msg)

        lib_dir_str = str(lib_dir)
        if lib_dir_str not in sys.path:
            sys.path.insert(0, lib_dir_str)

        try:
            import ashmaize_py
            logging.info(f"Successfully loaded ashmaize_py from {lib_dir}")
            return ashmaize_py
        except ImportError as e:
            error_msg = f"Failed to import ashmaize_py: {e}"
            logging.error(error_msg)
            logging.error("Check that the library files are not corrupted")
            raise ROMLibraryError(error_msg) from e

    def build_rom(
        self,
        rom_key: str,
        size: int = DEFAULT_ROM_SIZE,
        segment_size: int = DEFAULT_ROM_SEGMENT_SIZE,
        threads: int = DEFAULT_ROM_BUILD_THREADS
    ) -> Any:
        """
        Build ROM for a given key.
        
        Args:
            rom_key: The ROM key from challenge data (challenge['no_pre_mine'])
            size: ROM size in bytes (default: 1GB)
            segment_size: ROM segment size in bytes (default: 16MB)
            threads: Number of threads to use for building (default: 4)
            
        Returns:
            Built ROM object
            
        Raises:
            ROMLibraryError: If ashmaize library is not loaded
            ROMBuildError: If ROM building fails
        """
        if not self.ashmaize:
            raise ROMLibraryError("Ashmaize library not loaded")

        try:
            logging.info(
                f"Building ROM {rom_key[:10]}... "
                f"(size={size//1024//1024}MB, segments={segment_size//1024//1024}MB, threads={threads})"
            )
            rom = self.ashmaize.build_rom_twostep(rom_key, size, segment_size, threads)
            logging.info(f"ROM {rom_key[:10]}... built successfully")
            return rom
        except Exception as e:
            error_msg = f"Error building ROM: {e}"
            logging.error(error_msg)
            raise ROMBuildError(rom_key, str(e)) from e


# Global instance
rom_handler = ROMHandler()
