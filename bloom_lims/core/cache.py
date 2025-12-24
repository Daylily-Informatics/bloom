"""
BLOOM LIMS Caching Layer

Provides caching utilities for frequently accessed data.

Usage:
    from bloom_lims.core.cache import cached, cache_invalidate
    
    @cached(ttl=300)  # Cache for 5 minutes
    def get_template(euid: str):
        return db.query(Template).filter_by(euid=euid).first()
    
    # Invalidate specific cache entry
    cache_invalidate("get_template", euid="WF_ABC123_X")
    
    # Invalidate all entries for a function
    cache_invalidate("get_template")

Features:
    - TTL-based expiration
    - LRU eviction when max size reached
    - Thread-safe operations
    - Cache statistics
    - Selective invalidation
"""

import time
import logging
import threading
import hashlib
import json
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar, ParamSpec
from collections import OrderedDict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


@dataclass
class CacheEntry:
    """A single cache entry with value and metadata."""
    value: Any
    created_at: float
    ttl: float
    hits: int = 0
    
    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl <= 0:
            return False  # No expiration
        return time.time() - self.created_at > self.ttl


@dataclass
class CacheStats:
    """Statistics for a cache."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    invalidations: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class LRUCache:
    """
    Thread-safe LRU cache with TTL support.
    
    Attributes:
        max_size: Maximum number of entries
        default_ttl: Default TTL in seconds (0 = no expiration)
    """
    
    def __init__(self, max_size: int = 1000, default_ttl: float = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = CacheStats()
    
    def _make_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """Generate a cache key from function name and arguments."""
        # Create a hashable representation of args and kwargs
        key_parts = [func_name]
        
        for arg in args:
            try:
                key_parts.append(json.dumps(arg, sort_keys=True, default=str))
            except (TypeError, ValueError):
                key_parts.append(str(arg))
        
        for k, v in sorted(kwargs.items()):
            try:
                key_parts.append(f"{k}={json.dumps(v, sort_keys=True, default=str)}")
            except (TypeError, ValueError):
                key_parts.append(f"{k}={str(v)}")
        
        key_str = "|".join(key_parts)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._stats.misses += 1
                return None
            
            if entry.is_expired:
                del self._cache[key]
                self._stats.misses += 1
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.hits += 1
            self._stats.hits += 1
            return entry.value
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set a value in cache."""
        with self._lock:
            # Evict if at capacity
            while len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
                self._stats.evictions += 1
            
            self._cache[key] = CacheEntry(
                value=value,
                created_at=time.time(),
                ttl=ttl if ttl is not None else self.default_ttl
            )
    
    def invalidate(self, key: str) -> bool:
        """Invalidate a specific cache entry."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._stats.invalidations += 1
                return True
            return False
    
    def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all entries with keys starting with prefix."""
        with self._lock:
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(prefix)]
            for key in keys_to_remove:
                del self._cache[key]
            self._stats.invalidations += len(keys_to_remove)
            return len(keys_to_remove)
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._stats.invalidations += count
    
    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats

    def __len__(self) -> int:
        return len(self._cache)


# Global cache instance
_global_cache = LRUCache(max_size=5000, default_ttl=300)

# Registry of cached functions for invalidation
_cached_functions: Dict[str, Callable] = {}


def cached(
    ttl: Optional[float] = None,
    cache: Optional[LRUCache] = None,
    key_prefix: Optional[str] = None
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator to cache function results.

    Args:
        ttl: Time-to-live in seconds (None = use cache default)
        cache: Cache instance to use (None = use global cache)
        key_prefix: Prefix for cache keys (None = use function name)

    Usage:
        @cached(ttl=300)
        def get_template(euid: str):
            return db.query(Template).filter_by(euid=euid).first()
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        nonlocal cache, key_prefix

        if cache is None:
            cache = _global_cache

        if key_prefix is None:
            key_prefix = f"{func.__module__}.{func.__name__}"

        # Register function for invalidation
        _cached_functions[func.__name__] = func

        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Generate cache key
            key = cache._make_key(key_prefix, args, kwargs)

            # Try to get from cache
            result = cache.get(key)
            if result is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return result

            # Call function and cache result
            logger.debug(f"Cache miss for {func.__name__}")
            result = func(*args, **kwargs)

            # Don't cache None results
            if result is not None:
                cache.set(key, result, ttl)

            return result

        # Attach cache reference for manual invalidation
        wrapper._cache = cache
        wrapper._key_prefix = key_prefix

        return wrapper
    return decorator


def cache_invalidate(
    func_name: str,
    cache: Optional[LRUCache] = None,
    **kwargs
) -> int:
    """
    Invalidate cache entries for a function.

    Args:
        func_name: Name of the cached function
        cache: Cache instance (None = use global cache)
        **kwargs: If provided, invalidate only entries matching these args

    Returns:
        Number of entries invalidated

    Usage:
        # Invalidate all entries for get_template
        cache_invalidate("get_template")

        # Invalidate specific entry
        cache_invalidate("get_template", euid="WF_ABC123_X")
    """
    if cache is None:
        cache = _global_cache

    if kwargs:
        # Invalidate specific entry
        func = _cached_functions.get(func_name)
        if func:
            key_prefix = f"{func.__module__}.{func.__name__}"
            key = cache._make_key(key_prefix, (), kwargs)
            return 1 if cache.invalidate(key) else 0
    else:
        # Invalidate all entries for function
        func = _cached_functions.get(func_name)
        if func:
            key_prefix = f"{func.__module__}.{func.__name__}"
            return cache.invalidate_prefix(key_prefix[:8])  # Use hash prefix

    return 0


def cache_clear(cache: Optional[LRUCache] = None) -> None:
    """Clear all cache entries."""
    if cache is None:
        cache = _global_cache
    cache.clear()


def get_cache_stats(cache: Optional[LRUCache] = None) -> Dict[str, Any]:
    """
    Get cache statistics.

    Returns:
        Dictionary with cache statistics
    """
    if cache is None:
        cache = _global_cache

    stats = cache.stats
    return {
        "size": len(cache),
        "max_size": cache.max_size,
        "default_ttl": cache.default_ttl,
        "hits": stats.hits,
        "misses": stats.misses,
        "hit_rate": f"{stats.hit_rate:.2%}",
        "evictions": stats.evictions,
        "invalidations": stats.invalidations,
    }


def get_global_cache() -> LRUCache:
    """Get the global cache instance."""
    return _global_cache


def create_cache(max_size: int = 1000, default_ttl: float = 300) -> LRUCache:
    """
    Create a new cache instance.

    Use this when you need a separate cache for specific purposes.

    Args:
        max_size: Maximum number of entries
        default_ttl: Default TTL in seconds

    Returns:
        New LRUCache instance
    """
    return LRUCache(max_size=max_size, default_ttl=default_ttl)


def cached_method(
    ttl: Optional[float] = None,
    key_prefix: Optional[str] = None,
    cache: Optional[LRUCache] = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator for caching instance method results.

    Similar to @cached but designed for class methods where 'self'
    should not be part of the cache key.

    Args:
        ttl: Time-to-live in seconds
        key_prefix: Custom key prefix
        cache: Custom cache instance

    Usage:
        class MyClass:
            @cached_method(ttl=300)
            def expensive_query(self, euid: str):
                return self.db.query(euid)
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        target_cache = cache or _global_cache
        prefix = key_prefix or f"{func.__module__}.{func.__qualname__}"

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Build cache key excluding 'self'
            cache_key = target_cache._make_key(prefix, args, kwargs)

            # Try to get from cache
            result = target_cache.get(cache_key)
            if result is not None:
                logger.debug(f"Cache hit for {prefix}")
                return result

            # Call the actual method
            result = func(self, *args, **kwargs)

            # Cache non-None results
            if result is not None:
                effective_ttl = ttl if ttl is not None else target_cache.default_ttl
                target_cache.set(cache_key, result, effective_ttl)
                logger.debug(f"Cached result for {prefix}")

            return result

        # Store reference for invalidation
        wrapper._cache_prefix = prefix
        _cached_functions[prefix] = wrapper

        return wrapper  # type: ignore

    return decorator
