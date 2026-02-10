import logging
from typing import Callable, Optional

from fastapi import Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from config import settings

logger = logging.getLogger(__name__)


def get_telegram_user_id(request: Request) -> str:
    if hasattr(request.state, 'telegram_user_id'):
        return f"telegram:{request.state.telegram_user_id}"
    return get_remote_address(request)


def get_api_key_or_ip(request: Request) -> str:
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"api_key:{api_key[:16]}"
    return get_remote_address(request)


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute", "1000/hour"],
    storage_uri="memory://",
    strategy="fixed-window",
    headers_enabled=True,
)


RATE_LIMITS = {
    "webhook": "60/minute",
    "voice_processing": "10/minute",
    "llm_generation": "20/minute",
    "dashboard_read": "60/minute",
    "dashboard_write": "30/minute",
    "auth": "5/minute",
    "health": "120/minute",
}


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    from fastapi.responses import JSONResponse
    
    retry_after = exc.detail.split("rate limit exceeded, retry in ")[-1] if exc.detail else "60 seconds"
    
    logger.warning(
        f"Rate limit exceeded for {get_remote_address(request)}: {exc.detail}"
    )
    
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Please slow down.",
            "detail": exc.detail,
            "retry_after": retry_after
        },
        headers={
            "Retry-After": "60",
            "X-RateLimit-Limit": request.headers.get("X-RateLimit-Limit", ""),
            "X-RateLimit-Remaining": "0",
        }
    )


def setup_rate_limiting(app):
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    logger.info("Rate limiting configured successfully")


def get_rate_limit_status(request: Request) -> dict:
    return {
        "limit": request.headers.get("X-RateLimit-Limit"),
        "remaining": request.headers.get("X-RateLimit-Remaining"),
        "reset": request.headers.get("X-RateLimit-Reset"),
    }
