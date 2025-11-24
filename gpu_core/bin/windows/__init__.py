"""
Windows-specific compiled GPU engine modules.

The compiled `.pyd` files live alongside this module so we can import
them via `gpu_core.bin.windows.engine`.
"""

__all__ = ["engine", "kernels"]

