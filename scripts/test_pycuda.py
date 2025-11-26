import sys
import os
import ctypes

print(f"Python: {sys.version}")
print(f"Platform: {sys.platform}")

print("\nChecking DLLs...")
try:
    path = r"C:\Windows\System32\nvcuda.dll"
    print(f"Loading from {path}...")
    nvcuda = ctypes.windll.LoadLibrary(path)
    print("SUCCESS: Loaded nvcuda.dll from absolute path")
except Exception as e:
    print(f"FAILURE: Could not load nvcuda.dll from absolute path: {e}")

print("\nChecking for curand64_*.dll in PATH...")
found_curand = False
for path in os.environ["PATH"].split(os.pathsep):
    if os.path.exists(path):
        try:
            for file in os.listdir(path):
                if file.startswith("curand64_") and file.endswith(".dll"):
                    print(f"Found {file} in {path}")
                    found_curand = True
        except:
            pass
if not found_curand:
    print("WARNING: No curand64_*.dll found in PATH!")

print("\nImporting pycuda...")
try:
    import pycuda
    print(f"PyCUDA file: {pycuda.__file__}")
    import pycuda.driver as cuda
    print("SUCCESS: Imported pycuda.driver")
    cuda.init()
    print(f"CUDA Driver Version: {cuda.get_driver_version()}")
except ImportError as e:
    print(f"FAILURE: ImportError: {e}")
except Exception as e:
    print(f"FAILURE: Exception: {e}")
