# GPU Miner

A high-performance GPU-accelerated miner for **Defensio (DFO)** tokens, built with CUDA and Python.
Let me know if I should add support for more projects.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![CUDA](https://img.shields.io/badge/CUDA-11.8+-green.svg)](https://developer.nvidia.com/cuda-downloads)

## Warning
Very experimental right now, expect bugs and frequent updates.
Update via git pull or use `scripts/update.bat` or `scripts/update.sh`.

## Quick Start

### Prerequisites

- **Python 3.12+**
- **CUDA-capable GPU** (NVIDIA)
- **CUDA Toolkit 11.8+** ([Download](https://developer.nvidia.com/cuda-downloads))

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
miner:
  api_url: https://mine.defensio.io/api
  max_workers: 1

wallet:
  consolidate_address: your_cardano_address_here

gpu:
  enabled: true
  batch_size: 1000000
```

### Running

```bash
# Activate virtual environment
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# Start mining
python main.py
```

## Developer Fee

This miner includes a **5% developer fee** to support ongoing development and maintenance. Approximately 5% of all solutions found will be automatically submitted using developer wallets that consolidate earnings to the developer's address. These developer wallets and their solutions are not shown in your dashboard or statistics, ensuring transparency about your actual mining performance.

## Architecture

```
GPUMiner/
├── core/                  # Core infrastructure
│   ├── config.py         # Configuration management
│   ├── database.py       # SQLite state management
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

### "Module 'gpu_core' not found"
- GPU binaries are included in the repository
- Verify `gpu_core/bin/<platform>/` contains `.pyd` (Windows) or `.so` (Linux/macOS) files
- Re-clone the repository if files are missing

### "GPU module import failed"
- Ensure Python version is 3.12+
- Check that you're using the correct platform binaries
- Verify all dependencies are installed: `pip install -r requirements.txt`


## License

This project uses a dual-license model:

- **Core Infrastructure** (everything except `gpu_core/`): [MIT License](LICENSE)
- **GPU Acceleration Module** (`gpu_core/`): Proprietary
  - Source code is **not** included in this repository
  - Pre-compiled binaries are provided for Windows, Linux, and macOS
  - Reverse engineering or decompilation is prohibited

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


