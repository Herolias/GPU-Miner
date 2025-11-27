"""
Custom Exception Classes

Defines custom exceptions for the GPU Miner application to provide
better error handling and more specific error messages.
"""


class MinerError(Exception):
    """Base exception class for all miner-related errors."""
    pass


class GPUError(MinerError):
    """Base class for GPU-related errors."""
    pass


class GPUInitializationError(GPUError):
    """Raised when GPU initialization fails."""
    
    def __init__(self, gpu_id: int, message: str = "GPU failed to initialize"):
        self.gpu_id = gpu_id
        super().__init__(f"GPU {gpu_id}: {message}")


class GPUKernelCompilationError(GPUError):
    """Raised when GPU kernel compilation fails."""
    
    def __init__(self, gpu_id: int, message: str = "Kernel compilation failed"):
        self.gpu_id = gpu_id
        super().__init__(f"GPU {gpu_id}: {message}")


class GPUNotAvailableError(GPUError):
    """Raised when GPU is required but not available."""
    
    def __init__(self, message: str = "GPU not available"):
        super().__init__(message)


class WalletError(MinerError):
    """Base class for wallet-related errors."""
    pass


class WalletGenerationError(WalletError):
    """Raised when wallet generation fails."""
    
    def __init__(self, message: str = "Failed to generate wallet"):
        super().__init__(message)


class WalletRegistrationError(WalletError):
    """Raised when wallet registration fails."""
    
    def __init__(self, address: str, message: str = "Failed to register wallet"):
        self.address = address
        super().__init__(f"{address[:10]}...: {message}")


class WalletConsolidationError(WalletError):
    """Raised when wallet consolidation fails."""
    
    def __init__(self, address: str, message: str = "Failed to consolidate wallet"):
        self.address = address
        super().__init__(f"{address[:10]}...: {message}")


class WalletPoolError(WalletError):
    """Raised for wallet pool management errors."""
    
    def __init__(self, pool_id: str | int, message: str):
        self.pool_id = pool_id
        super().__init__(f"Pool {pool_id}: {message}")


class APIError(MinerError):
    """Base class for API-related errors."""
    pass


class APIConnectionError(APIError):
    """Raised when API connection fails."""
    
    def __init__(self, endpoint: str, message: str = "Connection failed"):
        self.endpoint = endpoint
        super().__init__(f"{endpoint}: {message}")


class APITimeoutError(APIError):
    """Raised when API request times out."""
    
    def __init__(self, endpoint: str, timeout: float):
        self.endpoint = endpoint
        self.timeout = timeout
        super().__init__(f"{endpoint}: Request timed out after {timeout}s")


class APIRateLimitError(APIError):
    """Raised when API rate limit is exceeded."""
    
    def __init__(self, retry_after: float = 0):
        self.retry_after = retry_after
        msg = "API rate limit exceeded"
        if retry_after > 0:
            msg += f", retry after {retry_after}s"
        super().__init__(msg)


class APIAuthenticationError(APIError):
    """Raised when API authentication fails."""
    
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)


class APIValidationError(APIError):
    """Raised when API rejects request due to validation errors."""
    
    def __init__(self, message: str):
        super().__init__(f"Validation error: {message}")


class ConfigurationError(MinerError):
    """Raised for configuration-related errors."""
    
    def __init__(self, key: str, message: str):
        self.key = key
        super().__init__(f"Configuration error for '{key}': {message}")


class ROMError(MinerError):
    """Base class for ROM-related errors."""
    pass


class ROMBuildError(ROMError):
    """Raised when ROM building fails."""
    
    def __init__(self, rom_key: str, message: str = "Failed to build ROM"):
        self.rom_key = rom_key
        super().__init__(f"{rom_key[:10]}...: {message}")


class ROMLibraryError(ROMError):
    """Raised when ashmaize library is not available or fails to load."""
    
    def __init__(self, message: str = "ROM library not available"):
        super().__init__(message)


class WorkerError(MinerError):
    """Base class for worker-related errors."""
    pass


class WorkerCrashError(WorkerError):
    """Raised when a worker process crashes."""
    
    def __init__(self, worker_type: str, worker_id: int, message: str = "Worker crashed"):
        self.worker_type = worker_type
        self.worker_id = worker_id
        super().__init__(f"{worker_type.upper()} {worker_id}: {message}")


class WorkerTimeoutError(WorkerError):
    """Raised when a worker doesn't respond in time."""
    
    def __init__(self, worker_type: str, worker_id: int, timeout: float):
        self.worker_type = worker_type
        self.worker_id = worker_id
        self.timeout = timeout
        super().__init__(f"{worker_type.upper()} {worker_id}: Timeout after {timeout}s")


class DatabaseError(MinerError):
    """Raised for database-related errors."""
    
    def __init__(self, message: str):
        super().__init__(f"Database error: {message}")


class FileStorageError(MinerError):
    """Raised for file storage errors (JSON pool files, etc)."""
    
    def __init__(self, filepath: str, message: str):
        self.filepath = filepath
        super().__init__(f"{filepath}: {message}")
