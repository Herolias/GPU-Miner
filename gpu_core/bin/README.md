# GPU Module Binaries

This directory contains pre-compiled GPU acceleration modules for the GPU Miner.

## Platform-Specific Binaries

- **windows/** - Windows binaries (`.pyd` files)
- **linux/** - Linux binaries (`.so` files)
- **macos/** - macOS binaries (`.so` files)

## What's Protected

The source code for these modules is proprietary and not included in this repository:
- `gpu_core/engine.py` - GPU mining engine implementation
- `gpu_core/kernels.py` - CUDA kernel implementations

## Auto-Loading

The `gpu_core/__init__.py` module automatically detects your platform and loads the appropriate pre-compiled binary. No manual configuration is needed.

## Compatibility

These binaries are compiled for:
- **Python Version:** 3.12
- **Architecture:** x86_64 / AMD64
- **CUDA:** 11.8+ (for NVIDIA GPUs)

## Verification

To verify the GPU modules are loaded correctly:

```python
from gpu_core import GPU_AVAILABLE, GPUEngine
print(f"GPU Available: {GPU_AVAILABLE}")
print(f"GPUEngine: {GPUEngine}")
```

## Rebuild Information

These binaries are automatically built by GitHub Actions when the source code changes. Each build is tested to ensure compatibility with the target platform.

**Build Workflow:** [.github/workflows/build-gpu-modules.yml](../../.github/workflows/build-gpu-modules.yml)

## License

The GPU acceleration modules are proprietary software. The binaries are provided for use with the GPU Miner application only. Reverse engineering, decompilation, or modification of these binaries is prohibited.

For the rest of the codebase, see the [LICENSE](../../LICENSE) file.
