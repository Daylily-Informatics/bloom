"""
BLOOM LIMS Rate Limiting

Provides rate limiting middleware for API endpoints to prevent abuse
and ensure fair resource allocation.

Usage:
    from bloom_lims.api.rate_limiting import RateLimiter, rate_limit
    
    # As decorator
    @rate_limit(requests_per_minute=60)
    def my_endpoint():
        pass
    
    # As middleware
    limiter = RateLimiter(requests_per_minute=100)
    app.add_middleware(limiter.middleware)
"""

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps
from threading import Lock
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

from bloom_lims.config import get_settings

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_size: int = 10
    enabled: bool = True


@dataclass
class ClientBucket:
    """Token bucket for a single client."""
    tokens: float
    last_update: float
    requests_minute: int = 0
    requests_hour: int = 0
    minute_start: float = 0.0
    hour_start: float = 0.0


class RateLimiter:
    """
    Token bucket rate limiter with per-client tracking.
    
    Implements a sliding window rate limiting algorithm that tracks:
    - Requests per minute (short-term limit)
    - Requests per hour (long-term limit)
    - Burst capacity (allow short bursts above limit)
    """
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
        burst_size: int = 10,
        enabled: bool = True,
    ):
        """
        Initialize rate limiter.
        
        Args:
            requests_per_minute: Max requests per minute per client
            requests_per_hour: Max requests per hour per client
            burst_size: Additional burst capacity
            enabled: Whether rate limiting is active
        """
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.burst_size = burst_size
        self.enabled = enabled
        
        self._buckets: Dict[str, ClientBucket] = defaultdict(
            lambda: ClientBucket(
                tokens=burst_size,
                last_update=time.time(),
                minute_start=time.time(),
                hour_start=time.time(),
            )
        )
        self._lock = Lock()
        
        # Load from settings if available
        settings = get_settings()
        if hasattr(settings, 'api') and hasattr(settings.api, 'rate_limit_per_minute'):
            self.requests_per_minute = settings.api.rate_limit_per_minute
    
    def is_allowed(self, client_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if request from client is allowed.
        
        Args:
            client_id: Unique client identifier (e.g., IP address, user ID)
            
        Returns:
            Tuple of (allowed, info_dict)
        """
        if not self.enabled:
            return True, {"rate_limited": False}
        
        with self._lock:
            now = time.time()
            bucket = self._buckets[client_id]
            
            # Refill tokens (1 token per second up to max)
            elapsed = now - bucket.last_update
            bucket.tokens = min(
                self.burst_size,
                bucket.tokens + elapsed * (self.requests_per_minute / 60)
            )
            bucket.last_update = now
            
            # Reset counters if window expired
            if now - bucket.minute_start > 60:
                bucket.requests_minute = 0
                bucket.minute_start = now
            
            if now - bucket.hour_start > 3600:
                bucket.requests_hour = 0
                bucket.hour_start = now
            
            # Check limits
            info = {
                "rate_limited": False,
                "requests_minute": bucket.requests_minute,
                "requests_hour": bucket.requests_hour,
                "tokens_remaining": int(bucket.tokens),
                "limit_minute": self.requests_per_minute,
                "limit_hour": self.requests_per_hour,
            }
            
            # Check hourly limit
            if bucket.requests_hour >= self.requests_per_hour:
                info["rate_limited"] = True
                info["retry_after"] = int(3600 - (now - bucket.hour_start))
                info["reason"] = "hourly_limit_exceeded"
                return False, info
            
            # Check minute limit (with burst tolerance)
            if bucket.requests_minute >= self.requests_per_minute and bucket.tokens < 1:
                info["rate_limited"] = True
                info["retry_after"] = int(60 - (now - bucket.minute_start))
                info["reason"] = "minute_limit_exceeded"
                return False, info
            
            # Consume token and increment counters
            bucket.tokens -= 1
            bucket.requests_minute += 1
            bucket.requests_hour += 1

            return True, info

    def get_stats(self, client_id: Optional[str] = None) -> Dict[str, Any]:
        """Get rate limiting statistics."""
        with self._lock:
            if client_id:
                bucket = self._buckets.get(client_id)
                if bucket:
                    return {
                        "client_id": client_id,
                        "requests_minute": bucket.requests_minute,
                        "requests_hour": bucket.requests_hour,
                        "tokens_remaining": int(bucket.tokens),
                    }
                return {"client_id": client_id, "error": "not_found"}

            return {
                "total_clients": len(self._buckets),
                "enabled": self.enabled,
                "limits": {
                    "requests_per_minute": self.requests_per_minute,
                    "requests_per_hour": self.requests_per_hour,
                    "burst_size": self.burst_size,
                }
            }

    def reset(self, client_id: Optional[str] = None) -> None:
        """Reset rate limit for a client or all clients."""
        with self._lock:
            if client_id:
                if client_id in self._buckets:
                    del self._buckets[client_id]
            else:
                self._buckets.clear()


# Global rate limiter instance
_global_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the global rate limiter."""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimiter()
    return _global_limiter


def rate_limit(
    requests_per_minute: Optional[int] = None,
    client_id_func: Optional[Callable[..., str]] = None,
) -> Callable[[F], F]:
    """
    Decorator to rate limit a function.

    Args:
        requests_per_minute: Override default limit (None = use global)
        client_id_func: Function to extract client ID from args (default: first arg)

    Usage:
        @rate_limit(requests_per_minute=30)
        def api_endpoint(request):
            pass
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter = get_rate_limiter()

            # Extract client ID
            if client_id_func:
                client_id = client_id_func(*args, **kwargs)
            elif args:
                # Try to get client IP from request object
                request = args[0]
                if hasattr(request, 'client'):
                    client_id = str(getattr(request.client, 'host', 'unknown'))
                elif hasattr(request, 'remote_addr'):
                    client_id = request.remote_addr
                else:
                    client_id = "default"
            else:
                client_id = "default"

            # Check rate limit
            allowed, info = limiter.is_allowed(client_id)

            if not allowed:
                logger.warning(
                    f"Rate limit exceeded for {client_id}: {info.get('reason')}"
                )
                # Raise or return appropriate response
                from bloom_lims.core.exceptions import BloomError
                raise BloomError(
                    f"Rate limit exceeded. Retry after {info.get('retry_after', 60)} seconds",
                    error_code="RATE_LIMIT_EXCEEDED",
                )

            return func(*args, **kwargs)

        return wrapper  # type: ignore
    return decorator


class RateLimitMiddleware:
    """
    ASGI middleware for rate limiting FastAPI/Starlette applications.

    Usage:
        from bloom_lims.api.rate_limiting import RateLimitMiddleware

        app.add_middleware(RateLimitMiddleware)
    """

    def __init__(
        self,
        app,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
        exclude_paths: Optional[list] = None,
    ):
        self.app = app
        self.limiter = RateLimiter(
            requests_per_minute=requests_per_minute,
            requests_per_hour=requests_per_hour,
        )
        self.exclude_paths = exclude_paths or ["/health", "/health/live", "/health/ready"]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Skip excluded paths
        if any(path.startswith(p) for p in self.exclude_paths):
            await self.app(scope, receive, send)
            return

        # Get client IP
        client = scope.get("client", ("unknown", 0))
        client_id = client[0] if client else "unknown"

        allowed, info = self.limiter.is_allowed(client_id)

        if not allowed:
            # Return 429 Too Many Requests
            response_body = (
                f'{{"error": "rate_limit_exceeded", '
                f'"retry_after": {info.get("retry_after", 60)}}}'
            ).encode()

            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"retry-after", str(info.get("retry_after", 60)).encode()],
                ],
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
            })
            return

        await self.app(scope, receive, send)

