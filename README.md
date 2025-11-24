# GPU Miner for Midnight/Defensio

A high-performance, open-source GPU miner for Midnight and Defensio tokens.

## Features

- **GPU Acceleration**: Optimized CUDA kernels for maximum hashrate.
- **Robustness**: SQLite state management to prevent data corruption.
- **Ease of Use**: Simple installation and update scripts.
- **Automatic Wallet Management**: Automatically creates and registers wallets.
- **Defensio Support**: Pre-configured for Defensio API.

## Installation

### Windows

1.  Run `scripts\install.bat`.
2.  This will create a virtual environment and install all dependencies.

### Linux

1.  Run `chmod +x scripts/install.sh`.
2.  Run `./scripts/install.sh`.

## Usage

To start the miner:

```bash
# Windows
venv\Scripts\python main.py

# Linux
source venv/bin/activate
python main.py
```

## Configuration

The miner creates a `config.yaml` file on the first run. You can modify this file to change settings:

```yaml
miner:
  max_workers: 1          # Number of concurrent workers (keep at 1 for single GPU)
  donation_enabled: true  # Support the developers
  api_url: https://mine.defensio.io/api

gpu:
  enabled: true
  batch_size: 1000000     # Target hashes per batch
```

## Updating

To update to the latest version, run:

-   **Windows**: `scripts\update.bat`
-   **Linux**: `./scripts/update.sh`

## Troubleshooting

-   **"No wallets found"**: The miner will automatically create a wallet. If it fails, check your internet connection.
-   **"Illegal memory access"**: Ensure your GPU drivers are up to date.
