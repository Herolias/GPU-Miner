"""
GPU Core Module Loader

Automatically loads the correct pre-compiled binary for your platform.
Falls back to the pure Python implementation when binaries are missing.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

GPU_AVAILABLE = False
GPUEngine = None
CUDA_SOURCE = None

if sys.platform == "win32":
    _platform_dir = "windows"
elif sys.platform.startswith("linux"):
    _platform_dir = "linux"
elif sys.platform == "darwin":
    _platform_dir = "macos"
else:
    raise RuntimeError(f"Unsupported platform: {sys.platform}")

_bin_dir = Path(__file__).parent / "bin" / _platform_dir
_binary_error: Exception | None = None

def _register_module(name: str, module) -> None:
    """Expose binary submodules via the canonical gpu_core.* paths."""
    sys.modules[f"{__name__}.{name}"] = module

if _bin_dir.exists():
    try:
        engine_module = importlib.import_module(f"{__name__}.bin.{_platform_dir}.engine")
        kernels_module = importlib.import_module(f"{__name__}.bin.{_platform_dir}.kernels")
        _register_module("engine", engine_module)
        _register_module("kernels", kernels_module)
        GPUEngine = getattr(engine_module, "GPUEngine", None)
        CUDA_SOURCE = getattr(kernels_module, "CUDA_SOURCE", None)
        GPU_AVAILABLE = GPUEngine is not None and CUDA_SOURCE is not None
    except ImportError as exc:
        _binary_error = exc
    except Exception as exc:
        _binary_error = exc
else:
    _binary_error = FileNotFoundError(f"Expected binaries in {_bin_dir}")

# Fallback to Python implementation when binaries are missing
if not GPU_AVAILABLE:
    try:
        engine_module = importlib.import_module(f"{__name__}.engine")
        kernels_module = importlib.import_module(f"{__name__}.kernels")
        _register_module("engine", engine_module)
        _register_module("kernels", kernels_module)
        GPUEngine = getattr(engine_module, "GPUEngine", None)
        CUDA_SOURCE = getattr(kernels_module, "CUDA_SOURCE", None)
        GPU_AVAILABLE = GPUEngine is not None and CUDA_SOURCE is not None
        if _binary_error and GPU_AVAILABLE:
            print(
                f"Warning: Failed to load precompiled GPU binaries ({_platform_dir}): {_binary_error}. "
                "Attempting Python fallback..."
            )
    except ImportError as exc:
        GPUEngine = None
        CUDA_SOURCE = None
        GPU_AVAILABLE = False
        reason = _binary_error or exc
        
        # Detailed error output
        print("")
        print("=" * 70)
        print("ERROR: GPU Module Failed to Load")
        print("=" * 70)
        print(f"Platform: {_platform_dir}")
        print(f"Python Version: {sys.version}")
        print(f"Binary Directory: {_bin_dir}")
        print(f"Binary Directory Exists: {_bin_dir.exists()}")
        
        if _bin_dir.exists():
            # List files in binary directory
            try:
                files = list(_bin_dir.glob("*"))
                print(f"Files in binary directory:")
                for f in files:
                    if f.is_file():
                        print(f"  - {f.name} ({f.stat().st_size} bytes)")
            except Exception as e:
                print(f"Could not list files: {e}")
        
        print(f"\nImport Error: {reason}")
        print(f"Error Type: {type(reason).__name__}")
        
        # Check Python version compatibility
        py_version = sys.version_info
        if py_version.major != 3 or py_version.minor != 12:
            print("")
            print("=" * 70)
            print("WARNING: Python Version Mismatch!")
            print("=" * 70)
            print(f"  Current Python: {py_version.major}.{py_version.minor}.{py_version.micro}")
            print(f"  Required: Python 3.12")
            print("")
            print("The GPU binaries are compiled for Python 3.12 only.")
            print("Please install Python 3.12 and try again.")
            print("=" * 70)
        
        print("")
        print("Troubleshooting:")
        print("  1. Verify Python version:")
        print("     python --version")
        print("     Must be Python 3.12.x")
        print("")
        print("  2. Ensure you're running from the project directory:")
        print("     cd GPU-Miner")
        print("     python main.py")
        print("")
        print("  3. Re-download from GitHub (don't use ZIP):")
        print("     git clone https://github.com/Herolias/GPU-Miner.git")
        print("")
        print("  4. Check git isn't corrupting binary files:")
        print("     git config core.autocrlf false")
        print("     git pull --force")
        print("")
        print("The miner cannot run without GPU binaries.")
        print("=" * 70)

__all__ = ["GPUEngine", "CUDA_SOURCE", "GPU_AVAILABLE"]
