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
        print("")
        print("=" * 60)
        print("ERROR: GPU Module Failed to Load")
        print("=" * 60)
        print(f"Platform: {_platform_dir}")
        print(f"Reason: {reason}")
        print("")
        print("Troubleshooting:")
        print("  1. Ensure you're running from the GPUMiner directory:")
        print("     cd GPUMiner")
        print("     python main.py")
        print("")
        print("  2. If you downloaded as ZIP, rename folder to 'GPUMiner':")
        print("     GPU-Miner-main → GPUMiner")
        print("")
        print("  3. Re-download from GitHub:")
        print("     git clone https://github.com/Herolias/GPU-Miner.git")
        print("")
        print("  4. Verify binary files exist:")
        print(f"     {_bin_dir}/")
        print("     Should contain .pyd (Windows) or .so (Linux) files")
        print("")
        print("The miner cannot run without GPU binaries.")
        print("=" * 60)

__all__ = ["GPUEngine", "CUDA_SOURCE", "GPU_AVAILABLE"]
