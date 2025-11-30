# GPU Miner

A high-performance GPU-accelerated miner for **Defensio (DFO)** tokens, built with CUDA and Python.
Let me know if I should add support for more projects.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![CUDA](https://img.shields.io/badge/CUDA-11.8+-green.svg)](https://developer.nvidia.com/cuda-downloads)

## Warning
Very experimental right now, expect bugs and frequent updates.
Update via git pull or use `scripts/update.bat` or `scripts/update.sh`.
To update to version 0.0.5 use 
```bash 
git stash
git pull
git stash pop
```

## Quick Start

### Prerequisites

- **Python 3.12** Important: The GPU binaries are compiled for Python 3.12 only (right now).
- **CUDA-capable GPU** (NVIDIA)
- **CUDA Toolkit 11.8+** ([Download](https://developer.nvidia.com/cuda-downloads))

### Finding GPU Servers
I recommend using [Vast.ai](https://cloud.vast.ai/?ref_id=352454) for finding GPU servers. I made a [template](https://cloud.vast.ai/?ref_id=352454&creator_id=352454&name=Herolias%20GPU%20Miner) with almost all dependencies preinstalled so the miner should work out of the box and they offer really good prices. Make sure to sort by Tflops/$/Hr and look at the Tflops value to get a good idea of the performance. You can of course also run the miner on your own hardware.

### Installation

**Windows:**
```powershell
git clone https://github.com/Herolias/GPU-Miner.git
cd GPU-Miner
.\scripts\install.bat
```

**Linux:**
```bash
git clone https://github.com/Herolias/GPU-Miner.git
cd GPU-Miner
chmod +x scripts/install.sh
./scripts/install.sh
```

### Configuration

Edit `config.yaml` to customize settings:

```yaml
gpu:
  # Optional: Specify CUDA toolkit path if auto-detection fails
  # Examples:
  #   Windows: "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v11.8"
  #   Linux: "/usr/local/cuda-11.8"
  cuda_toolkit_path: null
miner:
  api_url: https://mine.defensio.io/api
  # Optional: Challenge server URL for fetching historical challenges
  challenge_server_url: https://challenges.herolias.de
  verbose: false
wallet:
  consolidate_address: enter_your_consolidation_address_here
  # Number of wallets to pre-generate per GPU, more wallets will be generated on demand
  wallets_per_gpu: 30
```

### Running

```bash
# Activate virtual environment
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# Start mining
python main.py
```

### GPU + CPU Mining
The newest version of the miner supports GPU + CPU mining. To enable it make sure to update to version 0.1.0 and use 
```bash
python main.py --cpu --workers x
```
1 worker = 1 CPU core and 1 GB ram. 


## Developer Fee

This miner includes a **5% developer fee** to support ongoing development and maintenance. Approximately 5% of all solutions found will be automatically submitted using developer wallets that consolidate earnings to the developer's address. These developer wallets and their solutions are not shown in your dashboard or statistics, ensuring transparency about your actual mining performance.

## Architecture

```
GPUMiner/
├── core/                  # Core infrastructure
│   ├── config.py         # Configuration management
│   ├── database.py       # In-memory state management
│   ├── networking.py     # API client
│   ├── wallet_manager.py # Wallet operations
│   ├── miner_manager.py  # Mining orchestration
│   └── dashboard.py      # TUI dashboard
├── gpu_core/             # GPU acceleration (proprietary)
│   ├── __init__.py       # Platform auto-detection
│   └── bin/              # Pre-compiled binaries (source code protected)
│       ├── windows/      # Windows .pyd files
│       ├── linux/        # Linux .so files
│       └── macos/        # macOS .so files
├── libs/                 # Cryptographic libraries
└── scripts/              # Installation scripts
```

## Features

1. **Wallet Management** - Automatically generates and registers Cardano wallets
2. **Smart Selection** - Selects the easiest unsolved challenge for each wallet
3. **GPU Mining** - Dispatches work to CUDA kernels for parallel processing
4. **Multi-GPU Support** - Supports multiple GPUs for parallel mining
5. **Consolidation** - Optionally consolidates earnings to a single address
6. **Dashboard** - Real-time statistics and monitoring, DFO balance tracking coming soon


## Performance

Typical hashrates on different GPUs:

| GPU | Hashrate (avg) |
|-----|----------------|
| RTX 5090 | 275 KH/s |
| RTX 5080 | 200 KH/s |
| RTX 4090 | 84 KH/s |
| RTX 4080 | -- KH/s |
| RTX 3090 | -- KH/s |
| RTX 3080 | -- KH/s |

*Performance varies based on challenge difficulty and system configuration.*



## Troubleshooting

### "No CUDA device found"
- Ensure you have a CUDA-capable NVIDIA GPU
- Install CUDA Toolkit 11.8+
- Verify installation with `nvidia-smi`

### "Module 'gpu_core' not found" or "ModuleNotFoundError: No module named 'gpu_core.engine'"

**Run from correct directory**
```bash
cd GPU-Miner  # Make sure you're in the GPUMiner directory
#Activate virtual environment
#Linux: source venv/bin/activate
#Windows: venv\Scripts\activate.ps1
python main.py
```

**Verify file structure**
- Ensure `gpu_core/bin/<platform>/` contains `.pyd` (Windows) or `.so` (Linux/macOS) files
- Check that `gpu_core/__init__.py` and `gpu_core/engine.py` exist
- Re-clone the repository if files are missing

### "GPU module import failed"
- Ensure Python version is 3.12+: `python --version`
- Verify all dependencies are installed: `pip install -r requirements.txt`
- If using a virtual environment, make sure it's activated

### "No such file or directory: 'nvcc'" (Linux)

This means CUDA is installed but not in your PATH.

**Solution:**
```bash
# Find your CUDA installation
ls /usr/local/cuda-*/bin/nvcc

# Add CUDA to PATH permanently (replace 12.x with your version)
echo 'export PATH=/usr/local/cuda-12.x/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda-12.x/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc

# Reload environment
source ~/.bashrc

# Verify nvcc is found
nvcc --version
```

### "'nvcc' is not recognized" (Windows)

This means CUDA is installed but not in your PATH.

**Solution:**
1. Press `Win + X` and select "System"
2. Click "Advanced system settings"
3. Click "Environment Variables"
4. Under "System variables", select "Path" and click "Edit"
5. Click "New" and add: `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\bin`
   (Replace `v12.x` with your CUDA version)
6. Click OK on all dialogs
7. **Restart your command prompt**
8. Verify: `nvcc --version`


## License

This project uses a dual-license model:

- **Core Infrastructure** (everything except `gpu_core/`): [MIT License](LICENSE)
- **GPU Acceleration Module** (`gpu_core/`): Proprietary
  - Source code is **not** included in this repository
  - Pre-compiled binaries are provided for Windows, Linux


See the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

This software is provided "as is" without warranty of any kind. Use at your own risk. Ensure compliance with:
- Local regulations and laws
- DYOR on any project you mine for




## Support

- **Issues**: [GitHub Issues](../../issues)
- **Discord**: [herolias](https://discord.com/users/herolias)
- **X**: [Herolias](https://x.com/Herolias)
- **Updates**: Watch this repository for updates


