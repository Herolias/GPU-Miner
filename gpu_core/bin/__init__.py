"""
Platform-specific binary modules for gpu_core.

This package exists so we can import compiled extensions using regular
package paths like `gpu_core.bin.windows.engine`.
"""

__all__ = ["windows", "linux", "macos"]

