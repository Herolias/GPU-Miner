"""
Constants Module

Centralized location for all magic numbers and hardcoded values used throughout
the GPU Miner application. This improves maintainability and makes it easier to
tune parameters without searching through code.
"""

# ============================================================================
# Retry Configuration
# ============================================================================

# Maximum number of immediate retries for failed solution submissions
MAX_IMMEDIATE_RETRIES = 5

# Maximum number of API retries for transient failures
API_MAX_RETRIES = 3

# Maximum retries specifically for wallet registration
WALLET_REGISTRATION_MAX_RETRIES = 10

# Maximum retries for wallet consolidation
CONSOLIDATION_MAX_RETRIES = 5

# ============================================================================
# Timeout Configuration
# ============================================================================

# Timeout for GPU kernel compilation (seconds)
GPU_KERNEL_COMPILE_TIMEOUT = 600

# Delay between starting multiple GPU engines to avoid CPU spike (seconds)
GPU_KERNEL_BUILD_DELAY = 5

# API request timeout (seconds)
API_REQUEST_TIMEOUT = 30

# ============================================================================
# Solution Management
# ============================================================================

# How long to keep retrying failed solutions (hours)
SOLUTION_RETRY_EXPIRY_HOURS = 24

# Minimum time between solution retries from persistent storage (hours)
SOLUTION_RETRY_INTERVAL_HOURS = 1

# ============================================================================
# Database Configuration
# ============================================================================

# Maximum number of solutions to keep in memory
MAX_IN_MEMORY_SOLUTIONS = 10000

# Trim in-memory solutions to this count when limit is reached
TRIM_SOLUTIONS_TO = 5000

# Maximum number of challenges to keep in memory
MAX_IN_MEMORY_CHALLENGES = 100

# Trim in-memory challenges to this count when limit is reached
TRIM_CHALLENGES_TO = 50

# ============================================================================
# Wallet Configuration
# ============================================================================

# Default number of wallets to generate per GPU
DEFAULT_WALLETS_PER_GPU = 10

# Minimum number of dev wallets to maintain
DEV_WALLET_FLOOR = 2

# Developer fee percentage (0.05 = 5%)
DEV_FEE_PERCENTAGE = 0.05

# ============================================================================
# Mining Configuration
# ============================================================================

# Default batch size for GPU mining (hashes per batch)
DEFAULT_GPU_BATCH_SIZE = 1000000

# Default warmup batch size for GPU
DEFAULT_GPU_WARMUP_BATCH = 250000

# GPU Blocks per SM (0 = Auto)
GPU_BLOCKS_PER_SM = 0

# GPU Enabled by default
GPU_ENABLED = True

# Maximum number of workers
MAX_WORKERS = 1

# Miner Name
MINER_NAME = "GPU-Miner"

# Miner Version
MINER_VERSION = "0.1.1-beta"

# Wallet File (Legacy)
WALLET_FILE = "wallets.db"

# Use JSON-based per-GPU wallet pools
USE_JSON_WALLET_POOLS = True

# Batch size for CPU mining (hashes per loop)
CPU_MINING_BATCH_SIZE = 2000

# Default number of CPU workers
DEFAULT_CPU_WORKERS = 1

# ============================================================================
# Polling and Update Intervals
# ============================================================================

# Challenge polling interval (seconds)
CHALLENGE_POLL_INTERVAL = 10.0

# Dashboard update interval (seconds)
DASHBOARD_UPDATE_INTERVAL = 1.0

# Consolidation check interval (seconds)
CONSOLIDATION_CHECK_INTERVAL = 300  # 5 minutes

# How often to check periodic retries while mining (every N requests)
RETRY_CHECK_FREQUENCY = 100

# How often to refresh challenge info while mining (every N requests)
CHALLENGE_REFRESH_FREQUENCY = 10

# ============================================================================
# Sleep Durations
# ============================================================================

# Sleep when all workers are busy (seconds)
WORKER_BUSY_SLEEP = 0.01

# Sleep on error in main loops (seconds)
ERROR_SLEEP_DURATION = 5

# Sleep while waiting for challenge (seconds)
WAITING_FOR_CHALLENGE_SLEEP = 1

# Sleep on network errors (seconds)
NETWORK_ERROR_SLEEP = 5

# ============================================================================
# ROM Configuration
# ============================================================================

# Default ROM size (bytes) - 1GB
DEFAULT_ROM_SIZE = 1073741824

# Default ROM segment size (bytes) - 16MB
DEFAULT_ROM_SEGMENT_SIZE = 16777216

# Default number of threads for ROM building
DEFAULT_ROM_BUILD_THREADS = 4

# ============================================================================
# Logging Configuration
# ============================================================================

# Default log file name
DEFAULT_LOG_FILE = "miner.log"

# Maximum log file size for rotation (bytes) - 10MB
LOG_MAX_SIZE = 10 * 1024 * 1024

# Number of backup log files to keep
LOG_BACKUP_COUNT = 5

# ============================================================================
# API Configuration
# ============================================================================

# Default API base URL
DEFAULT_API_URL = "https://mine.defensio.io/api"

# API retry backoff base (seconds)
API_RETRY_BACKOFF_BASE = 1

# API retry backoff multiplier
API_RETRY_BACKOFF_MULTIPLIER = 2

# Maximum backoff time (seconds)
API_MAX_BACKOFF = 60

# ============================================================================
# Display Configuration
# ============================================================================

# Number of characters to show for truncated addresses
ADDRESS_DISPLAY_LENGTH = 10

# Number of characters to show for truncated challenge IDs
CHALLENGE_DISPLAY_LENGTH = 8

# Spinner animation frames
SPINNER_FRAMES = ['|', '/', '-', '\\']

# ============================================================================
# Hashrate Smoothing
# ============================================================================

# Exponential moving average weight for old hashrate values
HASHRATE_EMA_WEIGHT_OLD = 0.9

# Exponential moving average weight for new hashrate values
HASHRATE_EMA_WEIGHT_NEW = 0.1

# Hashrate display threshold for KH/s vs MH/s
HASHRATE_MH_THRESHOLD = 1_000_000
