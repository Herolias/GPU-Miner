import sys
import os
import time

# Add project root to path
sys.path.append(os.getcwd())

try:
    from core.dashboard import dashboard
    print("Dashboard imported successfully.")
    
    print("Testing SystemMonitor...")
    dashboard.sys_mon.update()
    print(f"CPU Load: {dashboard.sys_mon.cpu_load}%")
    print(f"CPU Temp: {dashboard.sys_mon.cpu_temp}")
    print(f"GPU Load: {dashboard.sys_mon.gpu_load}%")
    print(f"GPU Temp: {dashboard.sys_mon.gpu_temp}")
    
    print("\nSimulating render...")
    # We won't call render() directly as it clears screen, but we can check if it throws
    try:
        dashboard.render()
        print("Render called successfully (screen cleared above)")
    except Exception as e:
        print(f"Render failed: {e}")

except ImportError as e:
    print(f"Import failed: {e}")
except Exception as e:
    print(f"Test failed: {e}")
