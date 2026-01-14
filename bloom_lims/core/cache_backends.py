"""
BLOOM LIMS Cache Backends

Provides Redis and Memcached backends for distributed caching.

Usage:
    from bloom_lims.core.cache_backends import RedisCache, MemcachedCache, get_cache_backend
    
    # Auto-select backend based on configuration
    cache = get_cache_backend()
    
    # Or explicitly create Redis cache
    cache = RedisCache(host="localhost", port=6379)
    cache.set("key", {"data": "value"}, ttl=300)
    result = cache.get("key")

The backends implement the same interface as LRUCache for drop-in replacement.
"""

import json
import logging
import time
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

from bloom_lims.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class CacheStats:
    """Statistics for cache backend."""
    hits: int = 0
    misses: int = 0
    errors: int = 0
    
    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class CacheBackend(ABC):
    """Abstract base class for cache backends."""
    
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        pass
    
    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set a value in cache."""
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """Clear all cache entries."""
        pass
    
    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        pass
    
    @property
    @abstractmethod
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        pass


class RedisCache(CacheBackend):
    """
    Redis cache backend for distributed caching.
    
    Features:
        - Distributed cache across multiple application instances
        - Automatic serialization/deserialization with JSON
        - TTL support for automatic expiration
        - Connection pooling
        - Cluster support
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        default_ttl: float = 300,
        key_prefix: str = "bloom:",
        socket_timeout: float = 5.0,
        connection_pool_size: int = 10,
        ssl: bool = False,
        cluster_mode: bool = False,
    ):
        """
        Initialize Redis cache backend.
        
        Args:
            host: Redis server host
            port: Redis server port
            db: Redis database number
            password: Redis password (optional)
            default_ttl: Default TTL in seconds
            key_prefix: Prefix for all cache keys
            socket_timeout: Socket timeout in seconds
            connection_pool_size: Size of connection pool
            ssl: Enable SSL/TLS connection
            cluster_mode: Enable Redis Cluster mode
        """
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.default_ttl = default_ttl
        self.key_prefix = key_prefix
        self.ssl = ssl
        self.cluster_mode = cluster_mode
        self._stats = CacheStats()
        self._client = None
        
        try:
            import redis
            
            if cluster_mode:
                from redis.cluster import RedisCluster
                self._client = RedisCluster(
                    host=host,
                    port=port,
                    password=password,
                    socket_timeout=socket_timeout,
                    ssl=ssl,
                )
            else:
                pool = redis.ConnectionPool(
                    host=host,
                    port=port,
                    db=db,
                    password=password,
                    socket_timeout=socket_timeout,
                    max_connections=connection_pool_size,
                    ssl=ssl,
                )
                self._client = redis.Redis(connection_pool=pool)
            
            # Test connection
            self._client.ping()
            logger.info(f"Connected to Redis at {host}:{port}")

        except ImportError:
            logger.error("redis package not installed. Install with: pip install redis")
            raise
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _make_key(self, key: str) -> str:
        """Generate prefixed cache key."""
        return f"{self.key_prefix}{key}"

    def _serialize(self, value: Any) -> str:
        """Serialize value for storage."""
        return json.dumps(value, default=str)

    def _deserialize(self, data: bytes) -> Any:
        """Deserialize value from storage."""
        if data is None:
            return None
        return json.loads(data.decode('utf-8'))

    def get(self, key: str) -> Optional[Any]:
        """Get a value from Redis cache."""
        try:
            full_key = self._make_key(key)
            data = self._client.get(full_key)

            if data is None:
                self._stats.misses += 1
                return None

            self._stats.hits += 1
            return self._deserialize(data)

        except Exception as e:
            logger.warning(f"Redis GET error for {key}: {e}")
            self._stats.errors += 1
            return None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set a value in Redis cache."""
        try:
            full_key = self._make_key(key)
            data = self._serialize(value)
            effective_ttl = int(ttl if ttl is not None else self.default_ttl)

            if effective_ttl > 0:
                self._client.setex(full_key, effective_ttl, data)
            else:
                self._client.set(full_key, data)

        except Exception as e:
            logger.warning(f"Redis SET error for {key}: {e}")
            self._stats.errors += 1

    def delete(self, key: str) -> bool:
        """Delete a key from Redis cache."""
        try:
            full_key = self._make_key(key)
            return self._client.delete(full_key) > 0
        except Exception as e:
            logger.warning(f"Redis DELETE error for {key}: {e}")
            self._stats.errors += 1
            return False

    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern."""
        try:
            full_pattern = self._make_key(pattern)
            keys = self._client.keys(full_pattern)
            if keys:
                return self._client.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"Redis DELETE pattern error: {e}")
            self._stats.errors += 1
            return 0

    def clear(self) -> None:
        """Clear all cache entries with our prefix."""
        try:
            keys = self._client.keys(f"{self.key_prefix}*")
            if keys:
                self._client.delete(*keys)
                logger.info(f"Cleared {len(keys)} cache entries")
        except Exception as e:
            logger.warning(f"Redis CLEAR error: {e}")
            self._stats.errors += 1

    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        try:
            full_key = self._make_key(key)
            return self._client.exists(full_key) > 0
        except Exception as e:
            logger.warning(f"Redis EXISTS error for {key}: {e}")
            return False

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats

    def get_info(self) -> Dict[str, Any]:
        """Get Redis server info."""
        try:
            info = self._client.info()
            return {
                "connected": True,
                "redis_version": info.get("redis_version"),
                "used_memory": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}


class MemcachedCache(CacheBackend):
    """
    Memcached cache backend for distributed caching.

    Features:
        - Simple and fast distributed caching
        - Automatic serialization with JSON
        - TTL support
        - Connection pooling via pylibmc or pymemcache
    """

    def __init__(
        self,
        servers: List[str] = None,
        default_ttl: float = 300,
        key_prefix: str = "bloom:",
        connect_timeout: float = 5.0,
        timeout: float = 5.0,
    ):
        """
        Initialize Memcached cache backend.

        Args:
            servers: List of server addresses (e.g., ["localhost:11211"])
            default_ttl: Default TTL in seconds
            key_prefix: Prefix for all cache keys
            connect_timeout: Connection timeout in seconds
            timeout: Operation timeout in seconds
        """
        self.servers = servers or ["localhost:11211"]
        self.default_ttl = default_ttl
        self.key_prefix = key_prefix
        self._stats = CacheStats()
        self._client = None

        try:
            from pymemcache.client.hash import HashClient
            from pymemcache import serde

            self._client = HashClient(
                self.servers,
                connect_timeout=connect_timeout,
                timeout=timeout,
                serde=serde.pickle_serde,
                ignore_exc=True,
            )
            logger.info(f"Connected to Memcached at {self.servers}")

        except ImportError:
            logger.error("pymemcache not installed. Install with: pip install pymemcache")
            raise
        except Exception as e:
            logger.error(f"Failed to connect to Memcached: {e}")
            raise

    def _make_key(self, key: str) -> str:
        """Generate prefixed cache key (memcached has key length limits)."""
        full_key = f"{self.key_prefix}{key}"
        if len(full_key) > 250:
            # Hash long keys
            return f"{self.key_prefix}{hashlib.md5(key.encode()).hexdigest()}"
        return full_key

    def get(self, key: str) -> Optional[Any]:
        """Get a value from Memcached."""
        try:
            full_key = self._make_key(key)
            result = self._client.get(full_key)

            if result is None:
                self._stats.misses += 1
                return None

            self._stats.hits += 1
            return result

        except Exception as e:
            logger.warning(f"Memcached GET error for {key}: {e}")
            self._stats.errors += 1
            return None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set a value in Memcached."""
        try:
            full_key = self._make_key(key)
            effective_ttl = int(ttl if ttl is not None else self.default_ttl)
            self._client.set(full_key, value, expire=effective_ttl)
        except Exception as e:
            logger.warning(f"Memcached SET error for {key}: {e}")
            self._stats.errors += 1

    def delete(self, key: str) -> bool:
        """Delete a key from Memcached."""
        try:
            full_key = self._make_key(key)
            return self._client.delete(full_key)
        except Exception as e:
            logger.warning(f"Memcached DELETE error for {key}: {e}")
            self._stats.errors += 1
            return False

    def clear(self) -> None:
        """Clear all cache entries (flushes entire cache)."""
        try:
            self._client.flush_all()
            logger.info("Cleared all Memcached entries")
        except Exception as e:
            logger.warning(f"Memcached CLEAR error: {e}")
            self._stats.errors += 1

    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        return self.get(key) is not None

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats


def get_cache_backend(
    backend_type: Optional[str] = None,
    **kwargs
) -> CacheBackend:
    """
    Factory function to get appropriate cache backend.

    Auto-selects backend based on configuration if backend_type is not specified.

    Args:
        backend_type: "redis", "memcached", or "memory" (None = auto-detect)
        **kwargs: Backend-specific configuration

    Returns:
        Cache backend instance

    Usage:
        # Auto-detect from settings
        cache = get_cache_backend()

        # Explicit Redis
        cache = get_cache_backend("redis", host="redis.example.com")

        # Explicit Memcached
        cache = get_cache_backend("memcached", servers=["mc1:11211", "mc2:11211"])
    """
    settings = get_settings()

    # Auto-detect from settings
    if backend_type is None:
        backend_type = getattr(settings.cache, 'backend', 'memory')

    backend_type = backend_type.lower()

    if backend_type == "redis":
        redis_settings = {
            "host": getattr(settings.cache, 'redis_host', 'localhost'),
            "port": getattr(settings.cache, 'redis_port', 6379),
            "db": getattr(settings.cache, 'redis_db', 0),
            "password": getattr(settings.cache, 'redis_password', None),
            "default_ttl": settings.cache.default_ttl,
        }
        redis_settings.update(kwargs)
        return RedisCache(**redis_settings)

    elif backend_type == "memcached":
        mc_settings = {
            "servers": getattr(settings.cache, 'memcached_servers', ['localhost:11211']),
            "default_ttl": settings.cache.default_ttl,
        }
        mc_settings.update(kwargs)
        return MemcachedCache(**mc_settings)

    else:
        # Fall back to in-memory LRU cache
        from bloom_lims.core.cache import LRUCache
        return LRUCache(
            max_size=settings.cache.max_size,
            default_ttl=settings.cache.default_ttl,
        )

