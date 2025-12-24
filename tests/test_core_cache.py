"""
Tests for bloom_lims.core.cache module.
"""

import pytest
import time

from bloom_lims.core.cache import (
    LRUCache,
    CacheEntry,
    CacheStats,
    cached,
    cached_method,
    cache_invalidate,
    cache_clear,
    get_cache_stats,
    create_cache,
)


class TestCacheEntry:
    """Tests for CacheEntry class."""
    
    def test_not_expired(self):
        """Test entry is not expired when within TTL."""
        entry = CacheEntry(value="test", created_at=time.time(), ttl=300)
        assert entry.is_expired is False
    
    def test_expired(self):
        """Test entry is expired when past TTL."""
        entry = CacheEntry(value="test", created_at=time.time() - 400, ttl=300)
        assert entry.is_expired is True
    
    def test_no_expiration(self):
        """Test entry with TTL=0 never expires."""
        entry = CacheEntry(value="test", created_at=time.time() - 10000, ttl=0)
        assert entry.is_expired is False


class TestLRUCache:
    """Tests for LRUCache class."""
    
    def test_set_and_get(self):
        """Test basic set and get operations."""
        cache = LRUCache(max_size=100)
        cache.set("key1", "value1")
        
        assert cache.get("key1") == "value1"
    
    def test_get_missing_key(self):
        """Test get returns None for missing key."""
        cache = LRUCache(max_size=100)
        
        assert cache.get("nonexistent") is None
    
    def test_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        cache = LRUCache(max_size=3)
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        
        # Access key1 to make it recently used
        cache.get("key1")
        
        # Add key4, should evict key2 (least recently used)
        cache.set("key4", "value4")
        
        assert cache.get("key1") == "value1"  # Still present
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"  # Still present
        assert cache.get("key4") == "value4"  # Newly added
    
    def test_ttl_expiration(self):
        """Test TTL-based expiration."""
        cache = LRUCache(max_size=100, default_ttl=0.1)  # 100ms TTL
        cache.set("key1", "value1")
        
        assert cache.get("key1") == "value1"
        
        time.sleep(0.15)  # Wait for expiration
        
        assert cache.get("key1") is None
    
    def test_invalidate(self):
        """Test cache invalidation."""
        cache = LRUCache(max_size=100)
        cache.set("key1", "value1")
        
        assert cache.invalidate("key1") is True
        assert cache.get("key1") is None
        assert cache.invalidate("key1") is False  # Already removed
    
    def test_clear(self):
        """Test cache clear."""
        cache = LRUCache(max_size=100)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        cache.clear()
        
        assert len(cache) == 0
        assert cache.get("key1") is None
    
    def test_stats(self):
        """Test cache statistics."""
        cache = LRUCache(max_size=100)
        
        cache.set("key1", "value1")
        cache.get("key1")  # Hit
        cache.get("key1")  # Hit
        cache.get("nonexistent")  # Miss
        
        stats = cache.stats
        assert stats.hits == 2
        assert stats.misses == 1


class TestCachedDecorator:
    """Tests for @cached decorator."""
    
    def test_caches_result(self, clean_cache):
        """Test that decorator caches function result."""
        call_count = 0
        
        @cached(ttl=300)
        def expensive_function(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2
        
        result1 = expensive_function(5)
        result2 = expensive_function(5)
        
        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # Only called once
    
    def test_different_args_different_cache(self, clean_cache):
        """Test that different arguments use different cache entries."""
        call_count = 0
        
        @cached(ttl=300)
        def expensive_function(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2
        
        result1 = expensive_function(5)
        result2 = expensive_function(10)
        
        assert result1 == 10
        assert result2 == 20
        assert call_count == 2  # Called twice for different args
    
    def test_none_not_cached(self, clean_cache):
        """Test that None results are not cached."""
        call_count = 0
        
        @cached(ttl=300)
        def returns_none() -> None:
            nonlocal call_count
            call_count += 1
            return None
        
        returns_none()
        returns_none()
        
        assert call_count == 2  # Called twice since None not cached


class TestCacheHelpers:
    """Tests for cache helper functions."""
    
    def test_get_cache_stats(self, clean_cache):
        """Test get_cache_stats returns expected structure."""
        stats = get_cache_stats()
        
        assert "size" in stats
        assert "max_size" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate" in stats
    
    def test_create_cache(self):
        """Test create_cache creates new cache instance."""
        cache = create_cache(max_size=50, default_ttl=60)

        assert cache.max_size == 50
        assert cache.default_ttl == 60
        assert len(cache) == 0


class TestCacheInvalidatePrefix:
    """Tests for prefix-based invalidation."""

    def test_invalidate_prefix(self):
        """Test invalidating entries by prefix."""
        cache = LRUCache(max_size=100)

        cache.set("user:1:name", "Alice")
        cache.set("user:1:email", "alice@test.com")
        cache.set("user:2:name", "Bob")
        cache.set("other:key", "value")

        # Invalidate all user:1: entries
        count = cache.invalidate_prefix("user:1:")

        assert count == 2
        assert cache.get("user:1:name") is None
        assert cache.get("user:1:email") is None
        assert cache.get("user:2:name") == "Bob"  # Different prefix
        assert cache.get("other:key") == "value"  # Different prefix

    def test_invalidate_prefix_no_matches(self):
        """Test invalidating with no matching prefix."""
        cache = LRUCache(max_size=100)
        cache.set("key1", "value1")

        count = cache.invalidate_prefix("nonexistent:")

        assert count == 0
        assert cache.get("key1") == "value1"


class TestCachedMethodDecorator:
    """Tests for @cached_method decorator."""

    def test_caches_method_result(self, clean_cache):
        """Test that decorator caches instance method result."""
        call_count = 0

        class MyClass:
            @cached_method(ttl=300)
            def expensive_method(self, x: int) -> int:
                nonlocal call_count
                call_count += 1
                return x * 2

        obj = MyClass()
        result1 = obj.expensive_method(5)
        result2 = obj.expensive_method(5)

        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # Only called once

    def test_different_instances_share_cache(self, clean_cache):
        """Test that different instances share the method cache."""
        call_count = 0

        class MyClass:
            @cached_method(ttl=300)
            def expensive_method(self, x: int) -> int:
                nonlocal call_count
                call_count += 1
                return x * 2

        obj1 = MyClass()
        obj2 = MyClass()

        result1 = obj1.expensive_method(5)
        result2 = obj2.expensive_method(5)  # Same args, should hit cache

        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # Only called once across instances

    def test_different_args_different_cache(self, clean_cache):
        """Test that different arguments create different cache entries."""
        call_count = 0

        class MyClass:
            @cached_method(ttl=300)
            def expensive_method(self, x: int) -> int:
                nonlocal call_count
                call_count += 1
                return x * 2

        obj = MyClass()
        result1 = obj.expensive_method(5)
        result2 = obj.expensive_method(10)

        assert result1 == 10
        assert result2 == 20
        assert call_count == 2  # Called twice for different args

