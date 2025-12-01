import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional
from colorama import Fore, Style, init

from .constants import LOG_MAX_SIZE, LOG_BACKUP_COUNT, DEFAULT_LOG_FILE

# Initialize colorama
init(autoreset=True)

class StreamToLogger:
    """
    Fake file-like stream object that redirects writes to a logger instance.
    """
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.level, line.rstrip())

    def flush(self):
        pass

class ColoredFormatter(logging.Formatter):
    """Custom formatter for colored console logs."""
    
    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with appropriate color."""
        color = self.COLORS.get(record.levelno, Fore.WHITE)
        message = super().format(record)
        return f"{color}{message}{Style.RESET_ALL}"


def setup_logging(
    log_file: str = DEFAULT_LOG_FILE,
    level: int = logging.INFO,
    console_level: Optional[int] = None,
    enable_file_logging: bool = True,
    max_bytes: int = LOG_MAX_SIZE,
    backup_count: int = LOG_BACKUP_COUNT,
    enable_console_logging: bool = True
) -> None:
    """
    Configure the logging system for the application.
    
    Args:
        log_file: Path to log file
        level: Base logging level for file handler
        console_level: Console logging level (defaults to WARNING if None)
        enable_file_logging: Whether to enable file logging
        max_bytes: Maximum log file size before rotation
        backup_count: Number of backup log files to keep
        enable_console_logging: Whether to enable console logging
        
    Example:
        >>> setup_logging(log_file="miner.log", level=logging.INFO, console_level=logging.WARNING)
    """
    
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Clear existing handlers to avoid duplication
    root_logger.handlers = []

    # Console Handler - only show warnings/errors by default
    if enable_console_logging:
        if console_level is None:
            console_level = logging.WARNING
            
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_formatter = ColoredFormatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

    # File Handler with rotation
    if enable_file_logging:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    logging.info("Logging initialized")
