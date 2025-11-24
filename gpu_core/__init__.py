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
                f"Warning: Failed to load GPU binaries ({_platform_dir}): {_binary_error}. "
                "Falling back to PyCUDA implementation."
            )
    except ImportError as exc:
        GPUEngine = None
        CUDA_SOURCE = None
        GPU_AVAILABLE = False
        reason = _binary_error or exc
        print(f"Warning: Could not load GPU module for {_platform_dir}: {reason}")
        print("GPU acceleration not available. Falling back to CPU mode.")

__all__ = ["GPUEngine", "CUDA_SOURCE", "GPU_AVAILABLE"]
