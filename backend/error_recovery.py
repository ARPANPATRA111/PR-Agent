import asyncio
import logging
import functools
from typing import Callable, Optional, Tuple, Type, Any
from datetime import datetime

import httpx
from groq import (
    APIError,
    RateLimitError,
    APIConnectionError,
    APITimeoutError,
)

from config import settings

logger = logging.getLogger(__name__)


class RetryConfig:
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions or (Exception,)


RETRY_CONFIGS = {
    "llm": RetryConfig(
        max_retries=3,
        base_delay=2.0,
        max_delay=30.0,
        retryable_exceptions=(
            RateLimitError,
            APIConnectionError,
            APITimeoutError,
            httpx.TimeoutException,
            httpx.NetworkError,
        ),
    ),
    "whisper": RetryConfig(
        max_retries=2,
        base_delay=1.0,
        max_delay=10.0,
        retryable_exceptions=(
            OSError,
            RuntimeError,
        ),
    ),
    "telegram": RetryConfig(
        max_retries=5,
        base_delay=1.0,
        max_delay=60.0,
        retryable_exceptions=(
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.HTTPStatusError,
        ),
    ),
    "database": RetryConfig(
        max_retries=3,
        base_delay=0.5,
        max_delay=5.0,
        retryable_exceptions=(
            Exception,
        ),
    ),
}


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    import random
    
    delay = config.base_delay * (config.exponential_base ** attempt)
    delay = min(delay, config.max_delay)
    
    if config.jitter:
        jitter_factor = 1 + (random.random() - 0.5) * 0.5
        delay *= jitter_factor
    
    return delay


def with_retry(config_name: str = "llm", on_retry: Optional[Callable] = None):
    config = RETRY_CONFIGS.get(config_name, RETRY_CONFIGS["llm"])
    
    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except config.retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt < config.max_retries:
                        delay = calculate_delay(attempt, config)
                        
                        logger.warning(
                            f"Retry {attempt + 1}/{config.max_retries} for {func.__name__}: "
                            f"{type(e).__name__}: {e}. Waiting {delay:.1f}s..."
                        )
                        
                        if on_retry:
                            on_retry(attempt + 1, e, delay)
                        
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All {config.max_retries} retries failed for {func.__name__}: "
                            f"{type(e).__name__}: {e}"
                        )
                        
                except Exception as e:
                    logger.error(f"Non-retryable error in {func.__name__}: {e}")
                    raise
            
            raise last_exception
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            import time
            last_exception = None
            
            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                    
                except config.retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt < config.max_retries:
                        delay = calculate_delay(attempt, config)
                        
                        logger.warning(
                            f"Retry {attempt + 1}/{config.max_retries} for {func.__name__}: "
                            f"{type(e).__name__}: {e}. Waiting {delay:.1f}s..."
                        )
                        
                        if on_retry:
                            on_retry(attempt + 1, e, delay)
                        
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"All {config.max_retries} retries failed for {func.__name__}: "
                            f"{type(e).__name__}: {e}"
                        )
                        
                except Exception as e:
                    logger.error(f"Non-retryable error in {func.__name__}: {e}")
                    raise
            
            raise last_exception
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


class ErrorRecovery:
    
    def __init__(
        self,
        default: Any = None,
        log_errors: bool = True,
        reraise: bool = False,
        operation_name: str = "operation",
    ):
        self.default = default
        self.log_errors = log_errors
        self.reraise = reraise
        self.operation_name = operation_name
        
        self.result = None
        self.error = None
        self.success = False
    
    @property
    def value(self) -> Any:
        return self.result if self.success else self.default
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.success = True
            return True
        
        self.error = exc_val
        
        if self.log_errors:
            logger.error(
                f"Error in {self.operation_name}: {type(exc_val).__name__}: {exc_val}"
            )
        
        if self.reraise:
            return False
        
        return True
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.success = True
            return True
        
        self.error = exc_val
        
        if self.log_errors:
            logger.error(
                f"Error in {self.operation_name}: {type(exc_val).__name__}: {exc_val}"
            )
        
        if self.reraise:
            return False
        
        return True


class CircuitBreaker:
    
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "circuit",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.success_count = 0
    
    def can_execute(self) -> bool:
        if self.state == self.CLOSED:
            return True
        
        if self.state == self.OPEN:
            if self.last_failure_time:
                elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout:
                    logger.info(f"Circuit {self.name}: Transitioning to HALF_OPEN")
                    self.state = self.HALF_OPEN
                    return True
            return False
        
        return True
    
    def record_success(self):
        if self.state == self.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= 2:
                logger.info(f"Circuit {self.name}: Closing circuit (recovered)")
                self.state = self.CLOSED
                self.failure_count = 0
                self.success_count = 0
        else:
            self.failure_count = 0
    
    def record_failure(self, error: Exception):
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.state == self.HALF_OPEN:
            logger.warning(f"Circuit {self.name}: Opening circuit (test failed)")
            self.state = self.OPEN
            self.success_count = 0
        
        elif self.failure_count >= self.failure_threshold:
            logger.warning(
                f"Circuit {self.name}: Opening circuit "
                f"({self.failure_count} failures)"
            )
            self.state = self.OPEN
    
    def get_status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None,
        }


circuit_breakers = {
    "groq": CircuitBreaker(name="groq", failure_threshold=5, recovery_timeout=30),
    "telegram": CircuitBreaker(name="telegram", failure_threshold=10, recovery_timeout=60),
    "whisper": CircuitBreaker(name="whisper", failure_threshold=3, recovery_timeout=15),
}


def get_circuit_breaker(name: str) -> CircuitBreaker:
    return circuit_breakers.get(name, CircuitBreaker(name=name))


class ErrorStatsCollector:
    
    def __init__(self):
        self.errors: dict = {}
        self.total_errors = 0
        self.total_successes = 0
    
    def record_error(self, operation: str, error: Exception):
        error_type = type(error).__name__
        key = f"{operation}:{error_type}"
        
        if key not in self.errors:
            self.errors[key] = {
                "operation": operation,
                "error_type": error_type,
                "count": 0,
                "last_occurrence": None,
                "sample_message": str(error)[:200],
            }
        
        self.errors[key]["count"] += 1
        self.errors[key]["last_occurrence"] = datetime.utcnow().isoformat()
        self.total_errors += 1
    
    def record_success(self, operation: str):
        self.total_successes += 1
    
    def get_stats(self) -> dict:
        success_rate = 0
        if self.total_successes + self.total_errors > 0:
            success_rate = self.total_successes / (self.total_successes + self.total_errors)
        
        return {
            "total_errors": self.total_errors,
            "total_successes": self.total_successes,
            "success_rate": f"{success_rate:.2%}",
            "error_breakdown": list(self.errors.values()),
        }
    
    def reset(self):
        self.errors = {}
        self.total_errors = 0
        self.total_successes = 0


error_stats = ErrorStatsCollector()
