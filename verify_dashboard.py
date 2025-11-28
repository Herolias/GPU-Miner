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
    
    print(f"GPUs Detected: {len(dashboard.sys_mon.gpus)}")
    for gpu in dashboard.sys_mon.gpus:
        print(f"  GPU {gpu['id']}: Load {gpu['load']}% | Temp {gpu['temp']}C")
    
    print("\nTesting Status Section...")
    # Test Solution
    print("Registering solution...")
    dashboard.register_solution("D01C01")
    if dashboard.last_solution and dashboard.last_solution[1] == "D01C01":
        print("SUCCESS: Solution registered.")
    else:
        print("FAIL: Solution not registered.")
        
    # Test Error
    print("Registering error...")
    dashboard.register_error("12:00:00", "Test Error Message", 40) # 40 = ERROR
    if dashboard.last_error and dashboard.last_error[1] == "Test Error Message":
        print("SUCCESS: Error registered.")
    else:
        print("FAIL: Error not registered.")

    print("\nSimulating High GPU Count (8 GPUs)...")
    dashboard.sys_mon.gpus = []
    for i in range(8):
        dashboard.sys_mon.gpus.append({
            'id': i,
            'load': 100.0,
            'temp': 65.0 + i
        })
    
    print("Rendering Dashboard (Buffer Check)...")
    try:
        # We can't easily capture sys.stdout.write in this simple script without redirecting stdout
        # But we can just run it and see if it crashes, and visually check the output
        dashboard.render()
        print("\nRender completed successfully.")
    except Exception as e:
        print(f"Render failed: {e}")

except ImportError as e:
    print(f"Import failed: {e}")
except Exception as e:
    print(f"Test failed: {e}")
