"""
Type Definitions Module

Centralized type definitions for the GPU Miner application.
Uses TypedDict for runtime type checking and better IDE support.
"""

from typing import TypedDict, Union, Optional, Literal


# ============================================================================
# Challenge Types
# ============================================================================

class Challenge(TypedDict):
    """Mining challenge from the API."""
    challenge_id: str
    difficulty: str
    no_pre_mine: str
    latest_submission: str
    no_pre_mine_hour: str


class ChallengeOptional(TypedDict, total=False):
    """Challenge with optional fields."""
    challenge_id: str
    difficulty: str
    no_pre_mine: str
    latest_submission: str
    no_pre_mine_hour: str


# ============================================================================
# Wallet Types
# ============================================================================

class Wallet(TypedDict):
    """Wallet data structure."""
    address: str
    signing_key: str
    verification_key: str
    is_consolidated: bool
    is_dev_wallet: bool


class WalletOptional(TypedDict, total=False):
    """Wallet with optional fields for flexibility."""
    address: str
    signing_key: str
    verification_key: str
    is_consolidated: bool
    is_dev_wallet: bool
    pubkey: str
    signature: str


class WalletPoolData(TypedDict):
    """Structure of JSON wallet pool files."""
    wallets: list[WalletOptional]
    allocated: dict[str, str]  # wallet_address -> challenge_id
    solved: dict[str, list[str]]  # wallet_address -> [challenge_ids]


# ============================================================================
# Mining Request/Response Types
# ============================================================================

class MineRequest(TypedDict):
    """Request sent to GPU/CPU workers."""
    id: int
    type: Literal["mine", "shutdown"]
    rom_key: str
    salt_prefix: bytes
    difficulty: int
    start_nonce: int


class MineResponse(TypedDict, total=False):
    """Response from GPU/CPU workers."""
    request_id: int
    found: bool
    nonce: Optional[int]
    hash: Optional[str]
    hashes: int
    duration: float
    error: Optional[str]


class ActiveGPURequest(TypedDict):
    """Active GPU mining request tracking."""
    type: Literal["gpu"]
    worker_id: int
    wallet_address: str
    challenge_id: str
    is_dev_solution: bool


class ActiveCPURequest(TypedDict):
    """Active CPU mining request tracking."""
    type: Literal["cpu"]
    worker_id: int
    wallet_address: str
    challenge_id: str
    is_dev_solution: bool


ActiveRequest = Union[ActiveGPURequest, ActiveCPURequest]


# ============================================================================
# Solution Types
# ============================================================================

class Solution(TypedDict):
    """Solution data structure."""
    challenge_id: str
    nonce: str
    wallet_address: str
    difficulty: str
    is_dev_solution: bool
    timestamp: str
    status: Literal["submitted", "accepted", "rejected", "failed_max_retries"]


class FailedSolution(TypedDict):
    """Failed solution for retry tracking."""
    wallet_address: str
    challenge_id: str
    nonce: str
    difficulty: str
    is_dev_solution: bool
    timestamp: str
    retry_count: int
    last_retry: Optional[str]


class RetryQueueItem(TypedDict):
    """Item in the immediate retry queue."""
    wallet_address: str
    challenge_id: str
    nonce: str
    difficulty: str
    is_dev_solution: bool
    retry_count: int


# ============================================================================
# API Response Types
# ============================================================================

class APIError(TypedDict):
    """API error response structure."""
    error: str
    message: str


class SubmissionResult(TypedDict):
    """Result of solution submission."""
    success: bool
    is_fatal: bool


# ============================================================================
# Statistics Types
# ============================================================================

class PoolStats(TypedDict):
    """Statistics for a wallet pool."""
    total: int
    available: int
    allocated: int
    solved: int


class DashboardStats(TypedDict):
    """Statistics for dashboard display."""
    hashrate: float
    cpu_hashrate: float
    gpu_hashrate: float
    session_sol: int
    all_time_sol: int
    wallet_sols: dict[str, int]
    active_wallets: int
    challenge: str
    difficulty: str


# ============================================================================
# Configuration Types
# ============================================================================

class GPUConfig(TypedDict, total=False):
    """GPU configuration section."""
    enabled: bool
    batch_size: int
    blocks_per_sm: int
    warmup_batch: int
    cuda_toolkit_path: Optional[str]
    kernel_build_delay: int


class CPUConfig(TypedDict, total=False):
    """CPU configuration section."""
    enabled: bool
    workers: int


class MinerConfig(TypedDict, total=False):
    """Miner configuration section."""
    name: str
    version: str
    api_url: str
    max_workers: int


class WalletConfig(TypedDict, total=False):
    """Wallet configuration section."""
    file: str
    consolidate_address: Optional[str]
    use_json_pools: bool
    wallets_per_gpu: int


class Config(TypedDict, total=False):
    """Complete configuration structure."""
    miner: MinerConfig
    gpu: GPUConfig
    cpu: CPUConfig
    wallet: WalletConfig


# ============================================================================
# Worker Type
# ============================================================================

WorkerType = Literal["gpu", "cpu"]
PoolId = Union[int, str]  # GPU IDs are int, CPU IDs are "cpu_N"
